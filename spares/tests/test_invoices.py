from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from spares.invoice_models import ReceiptInvoice
from spares.invoice_xlsx import HEADERS
from spares.models import Company, Contractors, MeasureMeasurement, Receipt, Spares, Stock, Warehouses


class InvoiceWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser('invoice-operator')
        cls.company = Company.objects.create(name='Компания')
        cls.supplier = Contractors.objects.create(name='Поставщик')
        cls.warehouse = Warehouses.objects.create(name='Склад')
        cls.first = Spares.objects.create(name='Масляный фильтр', sku='FL-1')
        cls.second = Spares.objects.create(name='Ремень', sku='BELT-1')
        cls.measure = MeasureMeasurement.objects.create(name='шт.')

    def setUp(self):
        self.client.force_login(self.user)
        self.header = {
            'number': 'РН-100', 'date': timezone.localdate().isoformat(), 'company': self.company.pk,
            'contractor': self.supplier.pk, 'warehouse': self.warehouse.pk,
        }

    def line_data(self):
        return {
            **self.header,
            'form-TOTAL_FORMS': '2', 'form-INITIAL_FORMS': '0',
            'form-0-spare': self.first.pk, 'form-0-measure': self.measure.pk,
            'form-0-quantity': '2.50', 'form-0-price': '4.00',
            'form-1-spare': self.second.pk, 'form-1-measure': self.measure.pk,
            'form-1-quantity': '3', 'form-1-price': '2',
        }

    def workbook(self, rows):
        book = Workbook()
        book.active.append(HEADERS)
        for row in rows:
            book.active.append(row)
        file = BytesIO()
        book.save(file)
        book.close()
        return SimpleUploadedFile('invoice.xlsx', file.getvalue())

    def test_manual_invoice_cancels_all_lines_and_preserves_the_document(self):
        add = reverse('invoices:add')
        response = self.client.post(add, self.line_data())
        invoice = ReceiptInvoice.objects.get()
        self.assertRedirects(response, reverse('invoices:detail', args=[invoice.pk]))
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

    def test_future_date_and_duplicate_legacy_number_are_rejected(self):
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

    def test_import_requires_receipt_permission_and_template_is_xlsx(self):
        response = self.client.get(reverse('invoices:template'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'PK'))
        self.client.force_login(get_user_model().objects.create_user('no-receipts'))
        self.assertEqual(self.client.get(reverse('invoices:upload')).status_code, 403)
        self.assertEqual(self.client.get(reverse('invoices:list')).status_code, 403)
