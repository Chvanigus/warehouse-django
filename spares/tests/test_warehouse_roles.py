from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from spares.management.commands.configure_warehouse_roles import CONTROLLER_GROUP, OPERATOR_GROUP
from spares.models import Company, Spares, Stock, Warehouses


class WarehouseRoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = get_user_model().objects.create_user('operator')
        cls.controller = get_user_model().objects.create_user('controller')
        cls.stock = Stock.objects.create(
            company=Company.objects.create(name='Фирма'),
            warehouse=Warehouses.objects.create(name='Основной склад'),
            spare=Spares.objects.create(name='Фильтр'),
        )

    def test_standard_roles_allow_their_workflows(self):
        call_command('configure_warehouse_roles', operator=['operator'], controller=['controller'], stdout=StringIO())
        edit_stock = reverse('catalog:stock-edit', args=[self.stock.pk])

        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse('invoices:add')).status_code, 200)
        self.assertEqual(self.client.get(reverse('inventory_sheets:add')).status_code, 200)
        self.assertEqual(self.client.post(edit_stock, {'actual_balance': 50}).status_code, 403)
        self.assertFalse(self.operator.has_perm('spares.approve_inventorysheet'))
        self.assertFalse(self.operator.has_perm('spares.delete_receipt'))

        self.client.force_login(self.controller)
        self.assertEqual(self.client.get(reverse('inventory_sheets:list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('purchases:list')).status_code, 200)
        self.assertEqual(self.client.get(edit_stock).status_code, 200)
        self.assertEqual(self.client.post(reverse('invoices:add'), {}).status_code, 403)
        self.assertTrue(self.controller.has_perm('spares.approve_inventorysheet'))
        self.assertTrue(self.controller.has_perm('spares.delete_receipt'))
        self.assertFalse(self.controller.is_staff)

    def test_reapplying_role_policy_removes_unexpected_group_privileges(self):
        output = StringIO()
        call_command('configure_warehouse_roles', stdout=output)
        operator = Group.objects.get(name=OPERATOR_GROUP)
        extra = Permission.objects.get(content_type__app_label='spares', codename='change_stock')
        operator.permissions.add(extra)
        call_command('configure_warehouse_roles', stdout=output)
        self.assertFalse(operator.permissions.filter(pk=extra.pk).exists())

    def test_unknown_account_leaves_role_setup_atomic(self):
        with self.assertRaises(CommandError):
            call_command(
                'configure_warehouse_roles', operator=['operator'], controller=['missing'], stdout=StringIO(),
            )
        self.assertFalse(Group.objects.filter(name__in=[OPERATOR_GROUP, CONTROLLER_GROUP]).exists())
        self.assertFalse(self.operator.groups.exists())
