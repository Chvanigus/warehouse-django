from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from spares.models import Company, MeasureMeasurement, Spares, Stock, Warehouses
from spares.threshold_models import StockMinimum


class StockMinimumTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = get_user_model().objects.create_user(username='minimum-operator')
        cls.operator.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='spares',
            codename__in=(
                'view_stock', 'view_stockminimum', 'add_stockminimum', 'change_stockminimum',
                'delete_stockminimum', 'view_spares', 'add_spares',
            ),
        ))
        cls.spare = Spares.objects.create(name='Масляный фильтр', sku=' ФЛТ-1 ')
        cls.company = Company.objects.create(name='Фирма')
        cls.other_company = Company.objects.create(name='Филиал')
        cls.warehouse = Warehouses.objects.create(name='Основной')
        cls.other_warehouse = Warehouses.objects.create(name='Запасной')
        cls.measure = MeasureMeasurement.objects.create(name='шт.')

    def setUp(self):
        self.client.force_login(self.operator)
        self.key = dict(spare=self.spare, company=self.company, warehouse=self.warehouse, measure=self.measure)

    def test_minimum_counts_only_matching_stock_across_prices(self):
        for quantity, price in (('0.10', 1), ('0.70', 2)):
            Stock.objects.create(**self.key, actual_balance=Decimal(quantity), price=price)
        for overrides in ({'company': self.other_company}, {'warehouse': self.other_warehouse}, {'measure': None}):
            Stock.objects.create(**(self.key | overrides), actual_balance=20)
        exact = StockMinimum.objects.create(**self.key, minimum=Decimal('0.80'))
        without_unit = StockMinimum.objects.create(**(self.key | {'measure': None}), minimum=19)
        missing = StockMinimum.objects.create(
            **(self.key | {'company': self.other_company, 'warehouse': self.other_warehouse}), minimum=1,
        )

        rules = StockMinimum.objects.with_available()
        self.assertEqual(rules.get(pk=exact.pk).available, Decimal('0.80'))
        self.assertEqual(rules.get(pk=without_unit.pk).available, 20)
        self.assertEqual(rules.get(pk=missing.pk).available, 0)
        self.assertQuerySetEqual(rules.below_minimum(), [missing], ordered=False)

        exact.minimum = Decimal('0.81')
        exact.save()
        self.assertQuerySetEqual(rules.below_minimum(), [exact, missing], ordered=False)

    def test_stock_and_minimum_lists_search_by_sku_and_link_to_filtered_shortage(self):
        stock = Stock.objects.create(**self.key, actual_balance=2)
        rule = StockMinimum.objects.create(**self.key, minimum=3)
        filters = {'q': 'флт-1', 'warehouse': self.warehouse.pk}
        stock_response = self.client.get(reverse('spares:stock_report'), filters)
        self.assertQuerySetEqual(stock_response.context['report_data'], [stock])
        self.assertContains(stock_response, 'ФЛТ-1')
        self.assertContains(stock_response, 'К пополнению 1')
        minimums_response = self.client.get(reverse('catalog:minimums'), filters | {'low': 1})
        self.assertQuerySetEqual(minimums_response.context['rules'], [rule])
        self.assertContains(minimums_response, 'К пополнению')

    def test_minimum_crud_rejects_duplicate_without_measure(self):
        data = {'spare': self.spare.pk, 'company': self.company.pk, 'warehouse': self.warehouse.pk, 'minimum': '2.5'}
        add_url = reverse('catalog:add', args=['minimums'])
        index = reverse('catalog:minimums')
        self.assertRedirects(self.client.post(add_url, data), index)
        self.assertContains(self.client.post(add_url, data), 'Минимум для этой позиции уже задан.')
        rule = StockMinimum.objects.get()
        self.assertRedirects(
            self.client.post(reverse('catalog:edit', args=['minimums', rule.pk]), data | {'minimum': '5'}),
            index,
        )
        rule.refresh_from_db()
        self.assertEqual(rule.minimum, 5)
        self.assertRedirects(self.client.post(reverse('catalog:delete', args=['minimums', rule.pk])), index)
        self.assertFalse(StockMinimum.objects.exists())

    def test_catalog_sku_is_optional_normalized_and_unique(self):
        add_url = reverse('catalog:add', args=['spares'])
        index = reverse('catalog:list', args=['spares'])
        self.assertEqual(Spares.objects.get(pk=self.spare.pk).sku, 'ФЛТ-1')
        self.assertContains(self.client.get(index, {'q': 'флт-1'}), self.spare.name)
        duplicate = self.client.post(add_url, {'name': 'Повтор', 'sku': 'флт-1'}).context['form']
        self.assertEqual(duplicate.errors.as_data()['sku'][0].code, 'unique')
        for name in ('Гайка', 'Болт'):
            self.assertRedirects(self.client.post(add_url, {'name': name, 'sku': ''}), index)
        self.assertEqual(Spares.objects.filter(sku__isnull=True).count(), 2)

    def test_rule_permissions_are_independent_of_stock_view_permission(self):
        viewer = get_user_model().objects.create_user(username='stock-viewer')
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label='spares', codename='view_stock'))
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(reverse('catalog:minimums')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('spares:stock_report')), 'Минимальные остатки')
