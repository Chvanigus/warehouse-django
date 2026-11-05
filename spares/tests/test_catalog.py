from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from spares.models import Company, Spares, Stock, Warehouses


class CatalogTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('catalog-operator', password='test-pass')
        self.client.force_login(self.user)

    def grant(self, *codenames):
        self.user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='spares', codename__in=codenames,
        ))

    def test_catalog_workflow_without_staff_access(self):
        self.grant('view_contractors', 'add_contractors', 'change_contractors', 'delete_contractors')
        list_url = reverse('catalog:list', args=['contractors'])
        data = {'name': 'Снабжение', 'contact': '+7 123 456', 'contact_name': 'Иван'}
        self.assertContains(self.client.get(reverse('catalog:index')), list_url)
        self.assertRedirects(self.client.post(reverse('catalog:add', args=['contractors']), data), list_url)
        response = self.client.get(list_url, {'q': 'снаб'})
        self.assertContains(response, 'Снабжение')
        self.assertContains(response, 'Иван')
        pk, _ = response.context['rows'][0]
        data['contact_name'] = 'Анна'
        self.assertRedirects(self.client.post(reverse('catalog:edit', args=['contractors', pk]), data), list_url)
        self.assertContains(self.client.get(list_url), 'Анна')
        delete_url = reverse('catalog:delete', args=['contractors', pk])
        self.assertContains(self.client.get(delete_url), 'Снабжение')
        self.assertRedirects(self.client.post(delete_url), list_url)
        self.assertNotContains(self.client.get(list_url), 'Снабжение')

    def test_permissions_apply_to_get_and_post(self):
        url = reverse('catalog:add', args=['warehouses'])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {'name': 'Основной'}).status_code, 403)
        self.assertFalse(Warehouses.objects.exists())
        self.client.logout()
        self.assertRedirects(self.client.get(url), f"{reverse('spares:login')}?next={url}")

    def test_used_warehouse_cannot_be_deleted(self):
        self.grant('view_warehouses', 'delete_warehouses')
        warehouse = Warehouses.objects.create(name='Основной')
        Stock.objects.create(
            warehouse=warehouse,
            company=Company.objects.create(name='Тест'),
            spare=Spares.objects.create(name='Фильтр'),
        )
        url = reverse('catalog:delete', args=['warehouses', warehouse.pk])
        self.assertContains(self.client.post(url), 'Запись используется')
        self.assertTrue(Warehouses.objects.filter(pk=warehouse.pk).exists())

    def test_stock_form_preserves_identity_and_counters(self):
        self.grant('view_stock', 'add_stock', 'change_stock')
        warehouse = Warehouses.objects.create(name='Основной')
        other_warehouse = Warehouses.objects.create(name='Запасной')
        data = {
            'warehouse': warehouse.pk,
            'company': Company.objects.create(name='Тест').pk,
            'spare': Spares.objects.create(name='Фильтр').pk,
            'price': '12.00',
            'actual_balance': '4.00',
            'plan': '5',
            'inventory': '4',
        }
        stock_report = reverse('spares:stock_report')
        self.assertRedirects(self.client.post(reverse('catalog:stock-add'), data), stock_report)
        stock = Stock.objects.get()
        edit_url = reverse('catalog:stock-edit', args=[stock.pk])
        revision = self.client.get(edit_url).context['form']['revision'].value()
        data.update(
            warehouse=other_warehouse.pk, actual_balance='6', input_quantity='999', inventory='4.25',
            revision=revision,
        )
        self.assertRedirects(self.client.post(edit_url, data), stock_report)
        stock.refresh_from_db()
        self.assertEqual(stock.warehouse_id, warehouse.pk)
        self.assertEqual(stock.actual_balance, 6)
        self.assertEqual(stock.input_quantity, 0)
        self.assertEqual(stock.inventory, Decimal('4.25'))
        self.assertTrue(stock.discrepancy)

    def test_stock_form_refuses_a_stale_balance(self):
        self.grant('view_stock', 'change_stock')
        stock = Stock.objects.create(
            warehouse=Warehouses.objects.create(name='Основной'),
            company=Company.objects.create(name='Фирма'),
            spare=Spares.objects.create(name='Фильтр'),
            actual_balance=10,
        )
        edit_url = reverse('catalog:stock-edit', args=[stock.pk])
        revision = self.client.get(edit_url).context['form']['revision'].value()
        stock.actual_balance = 8
        stock.output_quantity = 2
        stock.save(update_fields=['actual_balance', 'output_quantity'])

        response = self.client.post(edit_url, {'actual_balance': '10', 'plan': '15', 'revision': revision})
        self.assertContains(response, 'Откройте актуальную запись')
        self.assertEqual(response.context['form']['revision'].value(), revision)
        stock.refresh_from_db()
        self.assertEqual(stock.actual_balance, 8)
        self.assertEqual(stock.plan, '')
