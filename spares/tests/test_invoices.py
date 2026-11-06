"""Ручные и импортированные накладные с несколькими строками."""

from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from spares.invoice_models import ReceiptInvoice
from spares.invoice_xlsx import HEADERS
from spares.models import Company, Contractors, MeasureMeasurement, Receipt, Spares, Stock, Warehouses
from spares.request_models import StockRequest
from spares.request_services import approve_stock_request


class InvoiceWorkflowTests(TestCase):
    """Проверяет проведение, отмену и валидацию импорта XLSX."""

    @classmethod
    def setUpTestData(cls):
        """Создаёт пользователя, поставщика, склады и позиции накладной."""
        cls.user = get_user_model().objects.create_superuser('invoice-operator')
        cls.company = Company.objects.create(name='Компания')
        cls.supplier = Contractors.objects.create(name='Поставщик')
        cls.warehouse = Warehouses.objects.create(name='Склад')
        cls.first = Spares.objects.create(name='Масляный фильтр', sku='FL-1')
        cls.second = Spares.objects.create(name='Ремень', sku='BELT-1')
        cls.measure = MeasureMeasurement.objects.create(name='шт.')

    def setUp(self):
        """Входит в приложение и подготавливает реквизиты тестового документа."""
        self.client.force_login(self.user)
        self.header = {
            'number': 'РН-100', 'date': timezone.localdate().isoformat(), 'company': self.company.pk,
            'contractor': self.supplier.pk, 'warehouse': self.warehouse.pk,
        }

    def line_data(self):
        """Возвращает параметры формы со строками ручного прихода."""
        return {
            **self.header,
            'form-TOTAL_FORMS': '2', 'form-INITIAL_FORMS': '0',
            'form-0-spare': self.first.pk, 'form-0-measure': self.measure.pk,
            'form-0-quantity': '2.50', 'form-0-price': '4.00',
            'form-1-spare': self.second.pk, 'form-1-measure': self.measure.pk,
            'form-1-quantity': '3', 'form-1-price': '2',
        }

    def workbook(self, rows):
        """Создаёт загружаемый файл XLSX из заданных строк."""
        book = Workbook()
        book.active.append(HEADERS)
        for row in rows:
            book.active.append(row)
        file = BytesIO()
        book.save(file)
        book.close()
        return SimpleUploadedFile('invoice.xlsx', file.getvalue())

    def log_in_operator(self):
        """Входит под автором, которому требуется согласование накладной."""
        user = get_user_model().objects.create_user('receipt-requester')
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='spares', codename__in=('add_receipt', 'add_stockrequest', 'view_stockrequest'),
        ))
        self.client.force_login(user)
        return user

    def test_manual_invoice_cancels_all_lines_and_preserves_the_document(self):
        """Проверяет создание многострочной накладной и её отмену без потери строк."""
        add = reverse('invoices:add')
        response = self.client.post(add, self.line_data())
        invoice = ReceiptInvoice.objects.get()
        self.assertRedirects(response, reverse('invoices:detail', args=[invoice.pk]))
        stock_request = StockRequest.objects.get()
        self.assertTrue(stock_request.applied_automatically)
        self.assertEqual(stock_request.reviewed_by, self.user)
        self.assertContains(self.client.get(reverse('invoices:list')), 'РН-100')
        self.assertEqual(invoice.lines.count(), 2)
        self.assertEqual(Stock.objects.get(spare=self.first).actual_balance, Decimal('2.50'))

        cancel = reverse('invoices:cancel', args=[invoice.pk])
        self.assertContains(self.client.post(cancel, {'reason': ''}), 'Обязательное поле')
        self.assertRedirects(
            self.client.post(cancel, {'reason': 'Ошибка в поставке'}),
            reverse('invoices:detail', args=[invoice.pk]),
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.cancellation_reason, 'Ошибка в поставке')
        self.assertEqual(invoice.cancelled_by_name, self.user.username)
        self.assertEqual(invoice.lines.filter(cancelled_at__isnull=False).count(), 2)
        self.assertFalse(Stock.objects.exclude(actual_balance=0).exists())
        replacement = self.client.post(add, self.line_data())
        self.assertEqual(replacement.status_code, 302)
        self.assertEqual(ReceiptInvoice.objects.count(), 2)
        self.assertEqual(ReceiptInvoice.objects.filter(cancelled_at__isnull=True).count(), 1)

    def test_failed_cancellation_rolls_back_all_invoice_lines(self):
        """Проверяет полный откат отмены при ошибке сторнирования одной из строк."""
        self.client.post(reverse('invoices:add'), self.line_data())
        invoice = ReceiptInvoice.objects.get()
        second_stock = Stock.objects.get(spare=self.second)
        second_stock.actual_balance = 1
        second_stock.save(update_fields=['actual_balance'])
        response = self.client.post(
            reverse('invoices:cancel', args=[invoice.pk]), {'reason': 'Ошибка'},
        )
        self.assertContains(response, 'остаток')
        invoice.refresh_from_db()
        self.assertIsNone(invoice.cancelled_at)
        self.assertEqual(invoice.lines.filter(cancelled_at__isnull=True).count(), 2)
        self.assertEqual(Stock.objects.get(spare=self.first).actual_balance, Decimal('2.50'))

    def test_invoice_line_with_overflow_shows_validation_error(self):
        """Проверяет ошибку формы при допустимых цене и количестве с недопустимой суммой."""
        data = self.line_data()
        data.update({'form-0-price': '9999999999999.99', 'form-0-quantity': '9999999999999.99'})

        response = self.client.post(reverse('invoices:add'), data)

        self.assertContains(response, 'Сумма строки превышает допустимое значение.')
        self.assertFalse(ReceiptInvoice.objects.exists())
        self.assertFalse(StockRequest.objects.exists())
        self.assertFalse(Stock.objects.exists())

    def test_future_date_and_duplicate_legacy_number_are_rejected(self):
        """Проверяет запрет будущей даты и повторного номера исторического прихода."""
        add = reverse('invoices:add')
        future = (timezone.localdate() + timedelta(days=1)).isoformat()
        self.assertContains(self.client.post(add, {**self.line_data(), 'date': future}), 'будущей датой')
        Receipt.objects.create(
            company=self.company, contractor=self.supplier, warehouse=self.warehouse,
            spare=self.first, measure=self.measure, invoice_number=' рн-100 ', quantity=1, price=1,
        )
        response = self.client.post(add, self.line_data())
        self.assertContains(response, 'с таким номером')
        self.assertFalse(ReceiptInvoice.objects.exists())

    def test_import_preview_posts_only_after_confirmation_and_rechecks_duplicates(self):
        """Проверяет проведение после подтверждения и повторную проверку номера."""
        upload = reverse('invoices:upload')
        workbook = self.workbook([('fl-1', 'масляный фильтр', 'шт.', '2,50', '4,00'), (None, 'Ремень', 'шт.', 3, 2)])
        preview = self.client.post(upload, {**self.header, 'workbook': workbook})
        self.assertContains(preview, 'Предпросмотр накладной')
        self.assertFalse(Receipt.objects.exists())
        self.assertFalse(Stock.objects.exists())
        confirmation = preview.context['confirmation']
        self.assertEqual(self.client.post(upload, {'confirmation': confirmation}).status_code, 302)
        invoice = ReceiptInvoice.objects.get()
        self.assertEqual(invoice.lines.count(), 2)
        self.assertEqual(invoice.lines.get(spare=self.first).quantity, Decimal('2.50'))
        self.assertContains(self.client.post(upload, {'confirmation': confirmation}), 'с таким номером')
        self.client.post(reverse('invoices:cancel', args=[invoice.pk]), {'reason': 'Ошибка импорта'})
        self.assertContains(self.client.post(upload, {'confirmation': confirmation}), 'История этой накладной изменилась')
        self.assertEqual(ReceiptInvoice.objects.count(), 1)

    def test_formula_unknown_part_and_repeated_lines_are_rejected(self):
        """Проверяет отказ для формулы, неизвестной запчасти и повторяющейся строки."""
        upload = reverse('invoices:upload')
        tests = [
            ([('FL-1', None, None, 1, '=1+2')], 'Замените формулы'),
            ([('UNKNOWN', None, None, 1, 2)], 'Строка 2'),
            ([('FL-1', None, None, 1, 2), ('FL-1', None, None, 3, 2)], 'Объедините строки'),
        ]
        for rows, error in tests:
            with self.subTest(error=error):
                response = self.client.post(upload, {**self.header, 'workbook': self.workbook(rows)})
                self.assertContains(response, error)
        self.assertFalse(Stock.objects.exists())

    def test_invalid_xlsx_compression_shows_validation_error(self):
        """Возвращает ошибку загрузки при повреждённом потоке сжатия XLSX."""
        file = BytesIO()
        content_types = '[Content_Types].xml'
        with ZipFile(file, 'w', compression=ZIP_DEFLATED) as archive:
            archive.writestr(content_types, '<Types/>')
            archive.writestr('xl/workbook.xml', '<workbook/>')
        damaged = bytearray(file.getvalue())
        # Подменяем тип блока DEFLATE на зарезервированный после заголовка и имени файла.
        damaged[30 + len(content_types)] = 0x07
        upload = SimpleUploadedFile('invoice.xlsx', bytes(damaged))

        response = self.client.post(reverse('invoices:upload'), {**self.header, 'workbook': upload})

        self.assertContains(response, 'Не удалось прочитать файл XLSX.')
        self.assertFalse(StockRequest.objects.exists())

    def test_import_requires_receipt_permission_and_template_is_xlsx(self):
        """Проверяет права импорта и формат загружаемого шаблона."""
        response = self.client.get(reverse('invoices:template'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'PK'))
        self.client.force_login(get_user_model().objects.create_user('no-receipts'))
        self.assertEqual(self.client.get(reverse('invoices:upload')).status_code, 403)
        self.assertEqual(self.client.get(reverse('invoices:list')).status_code, 403)

    def test_operator_invoice_waits_for_another_employee(self):
        """Проверяет, что строки накладной проводятся только после согласования."""
        operator = self.log_in_operator()
        response = self.client.post(reverse('invoices:add'), self.line_data())
        stock_request = StockRequest.objects.get()
        self.assertRedirects(response, reverse('stock_requests:detail', args=[stock_request.pk]))
        self.assertEqual((stock_request.status, stock_request.created_by), (StockRequest.Status.PENDING, operator))
        self.assertFalse(ReceiptInvoice.objects.exists())
        self.assertFalse(Stock.objects.exists())

        approve_stock_request(stock_request.pk, actor=self.user)
        invoice = ReceiptInvoice.objects.get()
        self.assertEqual(invoice.posted_by, self.user)
        self.assertEqual(invoice.lines.count(), 2)
        self.assertEqual(Stock.objects.get(spare=self.first).actual_balance, Decimal('2.50'))

    def test_operator_import_confirmation_creates_only_one_pending_request(self):
        """Проверяет, что повторная отправка предпросмотра не дублирует заявку."""
        self.log_in_operator()
        upload = reverse('invoices:upload')
        preview = self.client.post(
            upload, {**self.header, 'workbook': self.workbook([('fl-1', None, None, 1, 2)])},
        )
        confirmation = preview.context['confirmation']
        self.assertEqual(self.client.post(upload, {'confirmation': confirmation}).status_code, 302)
        self.assertContains(
            self.client.post(upload, {'confirmation': confirmation}), 'Заявка по этому предпросмотру уже существует.',
        )
        self.assertEqual(StockRequest.objects.count(), 1)
        self.assertEqual(StockRequest.objects.get().status, StockRequest.Status.PENDING)
        self.assertFalse(Stock.objects.exists())
