"""Фильтры рабочего списка остатков и доступность действий в строках."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from spares.models import Company, MeasureMeasurement, Spares, Stock, Warehouses


class StockWorkspaceTests(TestCase):
    """Проверяет фильтрацию, счётчики и ссылки операций над остатками."""

    @classmethod
    def setUpTestData(cls):
        """Создаёт партии разных складов и фирм и пользователей с разными правами."""
        cls.reader = get_user_model().objects.create_user(username='stock-reader')
        cls.operator = get_user_model().objects.create_user(username='stock-operator')
        permissions = Permission.objects.filter(content_type__app_label='spares')
        view_stock = permissions.get(codename='view_stock')
        cls.reader.user_permissions.add(view_stock)
        cls.operator.user_permissions.add(view_stock, *permissions.filter(codename__in=(
            'add_receipt', 'add_stock', 'change_stock', 'add_writeoff', 'add_stockrequest',
        )))
        cls.company = Company.objects.create(name='Главная фирма')
        cls.other_company = Company.objects.create(name='Вторая фирма')
        cls.warehouse = Warehouses.objects.create(name='Основной склад')
        cls.other_warehouse = Warehouses.objects.create(name='Запасной склад')
        measure = MeasureMeasurement.objects.create(name='шт.')
        spare = Spares.objects.create(name='Фильтр [A] ФЛТ')
        cls.match = Stock.objects.create(
            company=cls.company, warehouse=cls.warehouse, spare=spare,
            measure=measure, actual_balance=Decimal('4.25'), inventory=3,
        )
        cls.empty = Stock.objects.create(
            company=cls.other_company, warehouse=cls.warehouse,
            spare=spare, measure=measure, actual_balance=0,
        )
        cls.other = Stock.objects.create(
            company=cls.company, warehouse=cls.other_warehouse,
            spare=spare, measure=measure, actual_balance=3, inventory=3,
        )

    def setUp(self):
        """Сохраняет адрес рабочего списка остатков."""
        self.url = reverse('spares:stock_report')

    def test_filters_combine_and_counts_describe_filtered_rows(self):
        """Проверяет сочетание фильтров и подсчёт показателей по отобранным строкам."""
        self.client.force_login(self.reader)
        response = self.client.get(self.url, {
            'q': 'фильтр [a] флт',
            'warehouse': self.warehouse.pk,
            'company': self.company.pk,
            'discrepancy': '1',
        })
        self.assertQuerySetEqual(response.context['report_data'], [self.match])
        self.assertEqual(response.context['counts'], {'matches': 1, 'discrepancies': 1, 'unavailable': 0})
        self.assertContains(response, '4,25')
        self.assertContains(response, 'data-order="4.25"')
        self.assertNotContains(response, 'Нет данных')

    def test_invalid_filters_and_no_matches_have_distinct_states(self):
        """Проверяет сообщения для ошибочного запроса и отсутствия результатов."""
        self.client.force_login(self.reader)
        self.assertContains(self.client.get(self.url, {'warehouse': 'invalid'}), 'Проверьте фильтры')
        self.assertContains(self.client.get(self.url, {'q': 'Неизвестно'}), 'Подходящих позиций нет')

    def test_action_links_require_permissions_and_positive_stock(self):
        """Проверяет права действий и доступность списания при положительном остатке."""
        writeoff_url = reverse('operations:writeoff_add')
        edit_url = reverse('catalog:stock-edit', args=[self.match.pk])
        self.client.force_login(self.reader)
        response = self.client.get(self.url)
        self.assertNotContains(response, writeoff_url)
        self.assertNotContains(response, edit_url)

        self.client.force_login(self.operator)
        response = self.client.get(self.url)
        self.assertContains(response, f'{writeoff_url}?stock={self.match.pk}')
        self.assertNotContains(response, f'{writeoff_url}?stock={self.empty.pk}')
        self.assertContains(response, edit_url)
