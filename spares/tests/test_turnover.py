"""Проверка отчёта оборота, его прав и выгрузки отобранных строк."""

from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from spares.models import Company, Contractors, MeasureMeasurement, Receipt, Spares, Stock, Warehouses, Workers, WriteOff
from spares.turnover_views import TurnoverView


class TurnoverTests(TestCase):
    """Проверяет группировку запчастей и доступность страницы и книги."""

    @classmethod
    def setUpTestData(cls):
        """Готовит две единицы одного артикула, несколько цен и позицию только со списаниями."""
        cls.reader = get_user_model().objects.create_user(username='turnover-reader')
        cls.reader.user_permissions.set(Permission.objects.filter(
            content_type__app_label='spares', codename__in=('view_receipt', 'view_writeoff'),
        ))
        cls.company = Company.objects.create(name='Автопарк')
        cls.warehouse = Warehouses.objects.create(name='Основной склад')
        cls.other_warehouse = Warehouses.objects.create(name='Внешний склад')
        part = Spares.objects.create(name='=1+2', sku='MIX-001')
        other = Spares.objects.create(name='Уплотнитель', sku='OTHER-001')
        pieces = MeasureMeasurement.objects.create(name='шт.')
        litres = MeasureMeasurement.objects.create(name='л')
        contractor = Contractors.objects.create(name='Поставщик', contact='123', contact_name='Склад')
        worker = Workers.objects.create(name='Механик')
        base = {'company': cls.company, 'warehouse': cls.warehouse, 'spare': part}
        for unit, quantity, price, day in (
            (pieces, 3, '2.00', date(2024, 2, 29)),
            (pieces, 2, '5.00', date(2024, 2, 3)),
            (litres, 10, '2.00', date(2024, 2, 5)),
            (pieces, 10, '2.00', date(2024, 3, 1)),
        ):
            Receipt.objects.create(
                contractor=contractor, measure=unit, price=Decimal(price), quantity=quantity, date=day, **base,
            )
        canceled = Receipt.objects.create(
            contractor=contractor, measure=pieces, price=Decimal('2.00'), quantity=10, date=date(2024, 2, 4), **base,
        )
        canceled.cancel(actor=cls.reader, reason='Повторная строка')
        Receipt.objects.create(
            contractor=contractor, measure=pieces, price=Decimal('2.00'), quantity=10, date=date(2024, 2, 2),
            **{**base, 'warehouse': cls.other_warehouse},
        )
        WriteOff.objects.create(
            worker=worker, measure=pieces, price=Decimal('2.00'), quantity=1, date=date(2024, 2, 6), **base,
        )
        other_base = {**base, 'spare': other, 'price': Decimal('4.00')}
        Stock.objects.create(actual_balance=2, **other_base)
        WriteOff.objects.create(worker=worker, quantity=1, date=date(2024, 2, 10), **other_base)

    def setUp(self):
        """Входит под пользователем отчётов и выбирает один склад за февраль."""
        self.client.force_login(self.reader)
        self.params = {'start': '2024-02', 'end': '2024-02', 'warehouse': self.warehouse.pk}

    def test_groups_by_part_and_measure_across_prices(self):
        """Суммирует цены внутри одной единицы, сохраняя нулевую сторону и денежные итоги."""
        response = self.client.get(reverse('spares:turnover'), self.params)
        self.assertContains(response, 'Оборот по запчастям')
        rows = response.context['rows']
        self.assertEqual([
            (row['sku'], row['measure'], row['receipts_quantity'], row['writeoffs_quantity'])
            for row in rows
        ], [
            ('MIX-001', 'л', 10, 0), ('MIX-001', 'шт.', 5, 1), ('OTHER-001', None, 0, 1),
        ])
        self.assertEqual(response.context['receipts_total'], Decimal('36.00'))
        self.assertEqual(response.context['writeoffs_total'], Decimal('6.00'))

    def test_export_keeps_filters_and_writes_safe_text(self):
        """Выгружает все страницы по тем же фильтрам и оставляет формулоподобное название текстом."""
        params = {**self.params, 'q': 'mix-001', 'page': 2}
        with patch.object(TurnoverView, 'paginate_by', 1):
            page = self.client.get(reverse('spares:turnover'), params)
        self.assertEqual(len(page.context['rows']), 1)
        self.assertEqual(page.context['paginator'].count, 2)
        self.assertEqual(page.context['rows'][0]['measure'], 'шт.')
        self.assertEqual(page.context['receipts_total'], Decimal('36.00'))
        self.assertEqual(page.context['writeoffs_total'], Decimal('2.00'))
        self.assertContains(page, 'Скачать XLSX')
        with patch('spares.turnover_data.EXPORT_BATCH_SIZE', 1):
            response = self.client.get(reverse('spares:turnover_export'), params)
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(b''.join(response.streaming_content)))
        self.addCleanup(workbook.close)
        sheet = workbook['Оборот']
        self.assertEqual(sheet.max_row, 3)
        self.assertEqual(sheet['A2'].value, '=1+2')
        self.assertEqual(sheet['A2'].data_type, 's')
        self.assertEqual([cell.value for cell in sheet[3]][3:], [5, 1, 16, 2])
        self.assertEqual(workbook['Параметры']['B2'].value, '2024-02-29')

    def test_rejects_invalid_filters_and_requires_both_permissions(self):
        """Не выгружает ошибочную область и закрывает обе страницы с неполными правами."""
        url = reverse('spares:turnover')
        export = reverse('spares:turnover_export')
        response = self.client.get(url, {'company': 'несуществующая'})
        self.assertIn('company', response.context['form'].errors)
        self.assertFalse(response.context['rows'])
        self.assertEqual(self.client.get(export, {'start': '2024-01', 'end': '2023-12'}).status_code, 400)
        self.reader.user_permissions.remove(Permission.objects.get(
            content_type__app_label='spares', codename='view_writeoff',
        ))
        for path in (url, export):
            self.assertEqual(self.client.get(path).status_code, 403)
