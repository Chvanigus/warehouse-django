"""Настройка и границы стандартных ролей склада."""

from io import StringIO

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from spares.catalog_views import StockUpdateView
from spares.management.commands.configure_warehouse_roles import CONTROLLER_GROUP, OPERATOR_GROUP
from spares.models import Company, Receipt, Spares, Stock, Warehouses
from spares.warehouse_roles import WAREHOUSE_ROLES


class WarehouseRoleTests(TestCase):
    """Проверяет применение групповых прав оператора и контролёра."""

    @classmethod
    def setUpTestData(cls):
        """Создаёт участников без прав админки и контрольную позицию склада."""
        cls.operator = get_user_model().objects.create_user('operator')
        cls.controller = get_user_model().objects.create_user('controller')
        cls.administrator = get_user_model().objects.create_user('warehouse-admin')
        cls.stock = Stock.objects.create(
            company=Company.objects.create(name='Фирма'),
            warehouse=Warehouses.objects.create(name='Основной склад'),
            spare=Spares.objects.create(name='Фильтр'),
        )

    def test_standard_roles_allow_their_workflows(self):
        """Проверяет, какие действия каждой роли доступны через веб-интерфейс."""
        call_command(
            'configure_warehouse_roles', operator=['operator'], controller=['controller'],
            admin=['warehouse-admin'], stdout=StringIO(),
        )
        edit_stock = reverse('catalog:stock-edit', args=[self.stock.pk])

        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse('invoices:add')).status_code, 200)
        self.assertEqual(self.client.get(reverse('inventory_sheets:add')).status_code, 200)
        self.assertContains(self.client.get(reverse('spares:warehouse_main')), 'Мои заявки')
        self.assertEqual(self.client.get(reverse('warehouse_admin:users')).status_code, 403)
        self.assertEqual(self.client.post(edit_stock, {'actual_balance': 50}).status_code, 403)
        self.assertFalse(self.operator.has_perm('spares.approve_inventorysheet'))
        self.assertFalse(self.operator.has_perm('spares.delete_receipt'))

        self.client.force_login(self.controller)
        self.assertEqual(self.client.get(reverse('inventory_sheets:list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('purchases:list')).status_code, 200)
        self.assertEqual(self.client.get(edit_stock).status_code, 200)
        self.assertEqual(self.client.get(reverse('invoices:add')).status_code, 200)
        self.assertContains(self.client.get(reverse('spares:warehouse_main')), 'На проверке')
        self.assertEqual(self.client.get(reverse('warehouse_admin:users')).status_code, 403)
        self.assertTrue(self.controller.has_perm('spares.approve_inventorysheet'))
        self.assertTrue(self.controller.has_perm('spares.approve_stockrequest'))
        self.assertTrue(self.controller.has_perm('spares.delete_receipt'))
        self.assertFalse(self.controller.is_staff)

        self.client.force_login(self.administrator)
        self.assertContains(self.client.get(reverse('spares:warehouse_main')), 'Пользователи и роли')
        self.assertEqual(self.client.get(reverse('warehouse_admin:users')).status_code, 200)
        self.assertTrue(self.administrator.has_perm('spares.approve_stockrequest'))
        self.assertFalse(self.administrator.is_staff)

    def test_operator_with_admin_site_access_cannot_post_operations(self):
        """Проверяет запрет обхода очереди даже через форму добавления в Django Admin."""
        call_command('configure_warehouse_roles', operator=['operator'], stdout=StringIO())
        self.operator.is_staff = True
        self.operator.save(update_fields=['is_staff'])
        self.client.force_login(self.operator)
        for url_name in ('admin:spares_receipt_add', 'admin:spares_writeoff_add'):
            self.assertEqual(self.client.post(reverse(url_name)).status_code, 403)

    def test_stock_correction_checks_permissions_after_role_revocation(self):
        """Запрещает менять остаток запросом с сохранёнными в памяти правами."""
        call_command('configure_warehouse_roles', controller=['controller'], stdout=StringIO())
        actor = get_user_model().objects.get(pk=self.controller.pk)
        self.assertTrue(actor.has_perm('spares.change_stock'))
        call_command('configure_warehouse_roles', operator=['controller'], stdout=StringIO())
        url = reverse('catalog:stock-edit', args=[self.stock.pk])
        request = RequestFactory().post(url, {'actual_balance': '100', 'reason': 'Корректировка'})
        request.user = actor
        with self.assertRaises(PermissionDenied):
            StockUpdateView.as_view()(request, pk=self.stock.pk)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.actual_balance, 0)

    def test_admin_post_checks_if_staff_access_was_revoked(self):
        """Запрещает приход в Django Admin после отзыва статуса сотрудника."""
        self.controller.is_staff = True
        self.controller.save(update_fields=['is_staff'])
        call_command('configure_warehouse_roles', controller=['controller'], stdout=StringIO())
        model_admin = admin.site.get_model_admin(Receipt)
        request = RequestFactory().post(reverse('admin:spares_receipt_add'))
        request.user = self.controller
        self.assertTrue(model_admin.has_add_permission(request))
        get_user_model().objects.filter(pk=self.controller.pk).update(is_staff=False)
        with self.assertRaises(PermissionDenied):
            model_admin.changeform_view(request)
        self.assertFalse(Receipt.objects.exists())

    def test_assigning_role_replaces_previous_warehouse_group(self):
        """Проверяет смену роли с сохранением внешней группы существующей записи."""
        external = Group.objects.create(name='Внешняя группа')
        self.operator.groups.add(external)
        call_command('configure_warehouse_roles', operator=['operator'], stdout=StringIO())
        call_command('configure_warehouse_roles', controller=['operator'], stdout=StringIO())
        self.assertSetEqual(
            set(self.operator.groups.values_list('name', flat=True)), {external.name, WAREHOUSE_ROLES['reviewer']},
        )

    def test_reapplying_role_policy_removes_unexpected_group_privileges(self):
        """Проверяет восстановление заданного набора разрешений при повторной настройке."""
        output = StringIO()
        call_command('configure_warehouse_roles', stdout=output)
        operator = Group.objects.get(name=OPERATOR_GROUP)
        extra = Permission.objects.get(content_type__app_label='spares', codename='change_stock')
        operator.permissions.add(extra)
        call_command('configure_warehouse_roles', stdout=output)
        self.assertFalse(operator.permissions.filter(pk=extra.pk).exists())

    def test_unknown_account_leaves_role_setup_atomic(self):
        """Проверяет откат всех групп и назначений при неизвестной учётной записи."""
        with self.assertRaises(CommandError):
            call_command(
                'configure_warehouse_roles', operator=['operator'], controller=['missing'], stdout=StringIO(),
            )
        self.assertFalse(Group.objects.filter(name__in=[OPERATOR_GROUP, CONTROLLER_GROUP]).exists())
        self.assertFalse(self.operator.groups.exists())
