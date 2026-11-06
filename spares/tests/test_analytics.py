"""Проверка периодов, складских показателей и прав доступа к аналитике."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from spares.analytics_forms import AnalyticsFilterForm
from spares.analytics_views import AnalyticsView
from spares.models import Company, Contractors, MeasureMeasurement, Receipt, Spares, Stock, Warehouses, Workers, WriteOff
from spares.threshold_models import StockMinimum


class AnalyticsFilterTests(SimpleTestCase):
    """Проверяет календарные границы без обращения к складу."""

    def test_default_range_and_leap_month_boundary(self):
        """Включает шесть месяцев, ограничивает текущий день и учитывает високосный год."""
        today = date(2024, 3, 12)
        self.assertEqual(
            AnalyticsFilterForm(today=today).filters()['date_range'], (date(2023, 10, 1), today),
        )
        self.assertEqual(
            AnalyticsFilterForm({'start': '2024-02', 'end': '2024-02'}, today=today).filters()['date_range'],
            (date(2024, 2, 1), date(2024, 2, 29)),
        )
        self.assertEqual(
            AnalyticsFilterForm({'start': '2024-03', 'end': '2024-03'}, today=today).filters()['date_range'],
            (date(2024, 3, 1), today),
        )

    def test_invalid_and_oversized_ranges(self):
        """Отклоняет неверные месяцы, обратный порядок, будущий месяц и диапазон свыше двух лет."""
        for start, end in (
            ('2024-04', '2024-03'), ('2024-02', '2024-04'), ('2022-03', '2024-03'), ('2024-03', '2024-13'),
        ):
            with self.subTest(start=start, end=end):
                form = AnalyticsFilterForm({'start': start, 'end': end}, today=date(2024, 3, 12))
                self.assertIsNone(form.filters())
                self.assertIn('end', form.errors)


class AnalyticsViewTests(TestCase):
    """Проверяет выдачу разрешённых показателей и расчёты на проведённых документах."""

    @classmethod
    def setUpTestData(cls):
        """Готовит партии двух единиц измерения, отмену, будущую строку и отдельные области."""
        cls.reader = get_user_model().objects.create_user(username='analytics-reader')
        cls.company = Company.objects.create(name='Первый автопарк')
        cls.warehouse = Warehouses.objects.create(name='Основной склад')
        cls.other_warehouse = Warehouses.objects.create(name='Внешний склад')
        cls.other_company = Company.objects.create(name='Второй автопарк')
        cls.part = Spares.objects.create(name='Смазка', sku='GREASE-001')
        cls.pieces = MeasureMeasurement.objects.create(name='шт.')
        cls.liters = MeasureMeasurement.objects.create(name='л')
        cls.contractor = Contractors.objects.create(name='Поставщик', contact='123', contact_name='Иван')
        cls.worker = Workers.objects.create(name='Механик')
        base = {'company': cls.company, 'warehouse': cls.warehouse, 'spare': cls.part}
        receipt_base = {**base, 'contractor': cls.contractor}
        for day, measure, quantity, price, number in (
            (date(2024, 2, 29), cls.pieces, 5, '2.00', 'A-01'),
            (date(2024, 2, 3), cls.liters, 6, '3.00', 'A-02'),
            (date(2024, 3, 12), cls.pieces, 1, '2.00', 'A-03'),
            (date(2024, 3, 13), cls.pieces, 10, '2.00', 'A-04'),
        ):
            Receipt.objects.create(
                date=day, measure=measure, quantity=quantity, price=Decimal(price), invoice_number=number, **receipt_base,
            )
        canceled = Receipt.objects.create(
            date=date(2024, 2, 10), measure=cls.pieces, quantity=2, price=Decimal('2.00'),
            invoice_number='A-05', **receipt_base,
        )
        canceled.cancel(actor=cls.reader, reason='Дублирующий документ')
        for scope in ({'warehouse': cls.other_warehouse}, {'company': cls.other_company}):
            Receipt.objects.create(
                date=date(2024, 2, 5), quantity=10, price=Decimal('2.00'), invoice_number='A-06',
                **{**receipt_base, **scope},
            )
        WriteOff.objects.create(
            date=date(2024, 2, 15), measure=cls.pieces, quantity=2, price=Decimal('2.00'), worker=cls.worker, **base,
        )
        WriteOff.objects.create(
            date=date(2024, 3, 10), measure=cls.liters, quantity=3, price=Decimal('3.00'), worker=cls.worker, **base,
        )
        Stock.objects.create(
            company=cls.company, warehouse=cls.warehouse, spare=Spares.objects.create(name='Ремень'),
            actual_balance=0,
        )
        StockMinimum.objects.create(measure=cls.liters, minimum=Decimal('4.00'), **base)
        StockMinimum.objects.create(measure=cls.pieces, minimum=Decimal('1.00'), **{**base, 'warehouse': cls.other_warehouse})

    def _view(self, permissions, filters=None):
        """Возвращает ответ представления под выбранным набором прав без привязки к шаблону."""
        self.reader.user_permissions.set(Permission.objects.filter(content_type__app_label='spares', codename__in=permissions))
        request = RequestFactory().get('/analytics/', filters or {})
        request.user = get_user_model().objects.get(pk=self.reader.pk)
        with patch('spares.analytics_forms.timezone.localdate', return_value=date(2024, 3, 12)):
            return AnalyticsView.as_view()(request)

    def test_summary_and_trend_respect_dates_status_and_scope(self):
        """Считает строки и суммы, исключая отмену, будущее и соседние области."""
        context = self._view(
            ('view_receipt', 'view_writeoff'),
            {'start': '2024-01', 'end': '2024-03', 'company': self.company.pk, 'warehouse': self.warehouse.pk},
        ).context_data
        self.assertEqual(context['receipts'], {'amount': Decimal('30.00'), 'count': 3})
        self.assertEqual(context['writeoffs'], {'amount': Decimal('13.00'), 'count': 2})
        self.assertEqual(context['period']['end'], date(2024, 3, 12))
        self.assertEqual([point['receipts']['amount'] for point in context['trend']], [0, 28, 2])
        self.assertEqual([point['writeoffs']['amount'] for point in context['trend']], [0, 4, 9])
        self.assertEqual(context['trend_ticks'][-1]['height'], 100)
        self.assertTrue(all(0 <= point['receipts']['height'] <= 100 for point in context['trend']))
        self.assertIsNone(context['stock'])

    def test_top_writeoffs_keeps_units_separate(self):
        """Группирует разные единицы одной запчасти отдельно и сортирует по сумме."""
        context = self._view(('view_writeoff',)).context_data
        rows = context['top_writeoffs']
        self.assertEqual(
            [(row['sku'], row['measure'], row['quantity'], row['amount']) for row in rows],
            [('GREASE-001', 'л', Decimal('3.00'), Decimal('9.00')), ('GREASE-001', 'шт.', Decimal('2.00'), Decimal('4.00'))],
        )
        self.assertIsNone(context['receipts'])
        self.assertTrue(all(point['receipts'] is None for point in context['trend']))

    def test_stock_only_queries_current_positions_and_scoped_minimums(self):
        """Показывает текущие партии даже с устаревшими месяцами и не читает закрытые операции."""
        with CaptureQueriesContext(connection) as queries:
            context = self._view(
                ('view_stock', 'view_stockminimum'),
                {'start': 'старый-параметр', 'end': '9999-01', 'company': self.company.pk, 'warehouse': self.warehouse.pk},
            ).context_data
        sql = '\n'.join(query['sql'] for query in queries.captured_queries)
        self.assertNotIn('"spares_receipt"', sql)
        self.assertNotIn('"spares_writeoff"', sql)
        self.assertEqual(context['stock'], {
            'positions': 3, 'in_stock': 2, 'unavailable': 1, 'discrepancies': 0, 'below_minimum': 1,
        })
        self.assertEqual([row['name'] for row in context['warehouses']], [self.warehouse.name])
        self.assertFalse(context['trend'])
        self.assertEqual(self._view(('view_stock',)).context_data['stock']['below_minimum'], None)

    def test_invalid_filters_and_missing_permissions_do_not_expose_analytics(self):
        """Отклоняет постороннего пользователя и не строит показатели по неверной области."""
        with self.assertRaises(PermissionDenied):
            self._view(('view_stockminimum',))
        with CaptureQueriesContext(connection) as queries:
            context = self._view(('view_receipt',), {'warehouse': '999999'}).context_data
        self.assertFalse(context['ready'])
        self.assertIn('warehouse', context['form'].errors)
        self.assertNotIn('receipts', context)
        self.assertFalse(any('"spares_receipt"' in query['sql'] for query in queries.captured_queries))
