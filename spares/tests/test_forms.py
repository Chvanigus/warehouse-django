from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from spares.forms import StockForm, WriteOffForm
from spares.models import (
    Company, Contractors, MachineWorker, Receipt, Spares, Stock, Warehouses,
    Workers, WriteOff,
)


class WarehouseOperationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.spare = Spares.objects.create(name='Фильтр')
        cls.company = Company.objects.create(name='Организация')
        cls.warehouse = Warehouses.objects.create(name='Основной склад')
        cls.destination = Warehouses.objects.create(name='Запасной склад')
        cls.contractor = Contractors.objects.create(name='Поставщик', contact='123', contact_name='Иван')
        cls.assignment = MachineWorker.objects.create(worker=Workers.objects.create(name='Алексей'))
        cls.receipt_data = {
            'spare': cls.spare.pk,
            'company': cls.company.pk,
            'warehouse': cls.warehouse.pk,
            'date': '2026-01-10',
            'quantity': '8',
            'price': '7.50',
            'invoice_number': 'НК-100',
            'contractor': cls.contractor.pk,
        }
        cls.operator = get_user_model().objects.create_user(username='operator')
        cls.operator.user_permissions.set(Permission.objects.filter(
            content_type__app_label='spares',
            content_type__model__in=['receipt', 'writeoff', 'movement'],
        ))
        cls.observer = get_user_model().objects.create_user(username='observer')
        cls.observer.user_permissions.add(Permission.objects.get(
            content_type__app_label='spares', codename='view_receipt',
        ))

    def add_receipt(self):
        response = self.client.post(reverse('operations:receipt_add'), self.receipt_data)
        self.assertRedirects(response, reverse('operations:receipts'))
        return Receipt.objects.get()

    def test_permissions_separate_read_and_write_access(self):
        receipt_list = reverse('operations:receipts')
        add_receipt = reverse('operations:receipt_add')
        self.assertEqual(self.client.get(receipt_list).status_code, 302)
        self.client.force_login(self.observer)
        self.assertNotContains(self.client.get(receipt_list), add_receipt)
        self.assertEqual(self.client.post(add_receipt, self.receipt_data).status_code, 403)
        self.assertEqual(self.client.get(reverse('operations:movements')).status_code, 403)
        self.assertFalse(Receipt.objects.exists())

    def test_journal_combines_text_search_and_dates(self):
        self.client.force_login(self.operator)
        self.add_receipt()
        url = reverse('operations:receipts')
        self.assertContains(self.client.get(url, {'q': 'фильтр', 'date_from': '2026-01-10'}), 'НК-100')
        self.assertNotContains(self.client.get(url, {'q': 'фильтр', 'date_to': '2026-01-09'}), 'НК-100')
        response = self.client.get(url, {'date_from': '2026-02-01', 'date_to': '2026-01-01'})
        self.assertContains(response, 'Конец периода должен быть не раньше начала')
        self.assertNotContains(response, 'НК-100')

    def test_operator_can_create_and_cancel_receipt_without_overwriting_it(self):
        self.client.force_login(self.operator)
        receipt = self.add_receipt()
        self.assertEqual(receipt.amount, Decimal('60.00'))
        self.assertContains(self.client.get(reverse('operations:receipts'), {'q': 'нк-100'}), 'НК-100')
        self.assertNotContains(self.client.get(reverse('operations:receipts'), {'q': 'НК-200'}), 'НК-100')
        self.assertNotContains(self.client.get(reverse('operations:receipts'), {'q': '('}), 'НК-100')
        response = self.client.post(
            reverse('operations:receipt_edit', args=[receipt.pk]),
            {**self.receipt_data, 'warehouse': self.destination.pk},
        )
        self.assertRedirects(response, reverse('operations:receipts'))
        receipt.refresh_from_db()
        self.assertEqual(receipt.warehouse, self.warehouse)
        self.assertFalse(Stock.objects.filter(warehouse=self.destination).exists())

        cancel_url = reverse('operations:receipt_cancel', args=[receipt.pk])
        self.assertContains(self.client.get(cancel_url), 'Отмена документа')
        self.assertEqual(self.client.post(cancel_url).status_code, 200)
        self.assertRedirects(self.client.post(cancel_url, {'reason': 'Ошибочная накладная'}), reverse('operations:receipts'))
        receipt.refresh_from_db()
        self.assertEqual(receipt.cancelled_by, self.operator)
        self.assertEqual(receipt.cancellation_reason, 'Ошибочная накладная')
        self.assertEqual(receipt.quantity, Decimal('8'))
        self.assertEqual(Stock.objects.get(warehouse=self.warehouse).actual_balance, Decimal('0'))
        self.assertEqual(self.client.post(cancel_url, {'reason': 'Повтор'}).status_code, 404)
        self.assertContains(self.client.get(reverse('operations:receipts')), 'Ошибочная накладная')

    def test_writeoff_validation_and_cancellation(self):
        self.client.force_login(self.operator)
        receipt = self.add_receipt()
        stock = Stock.objects.get()
        writeoff_data = {
            'spares_list': stock.pk,
            'machine_list': self.assignment.pk,
            'date': '2026-01-10',
            'quantity': '8',
        }
        add_writeoff = reverse('operations:writeoff_add')
        response = self.client.post(add_writeoff, {**writeoff_data, 'quantity': '9'})
        self.assertContains(response, 'Количество превышает доступный остаток')
        self.assertFalse(WriteOff.objects.exists())

        self.assertRedirects(self.client.post(add_writeoff, writeoff_data), reverse('operations:writeoffs'))
        writeoff = WriteOff.objects.get()
        self.assertEqual(writeoff.worker, self.assignment.worker)
        self.assertEqual(writeoff.total_amount, Decimal('60.00'))
        form = WriteOffForm(instance=writeoff)
        self.assertEqual(form.initial['spares_list'], stock)
        self.assertEqual(form.initial['machine_list'], self.assignment)

        response = self.client.post(reverse('operations:receipt_cancel', args=[receipt.pk]), {'reason': 'Отмена'})
        self.assertContains(response, 'Количество превышает доступный остаток')
        self.assertTrue(Receipt.objects.filter(pk=receipt.pk).exists())

        MachineWorker.objects.filter(pk=self.assignment.pk).delete()
        stale_assignment_form = WriteOffForm(instance=writeoff, data={
            **writeoff_data, 'machine_list': '', 'quantity': '7',
        })
        self.assertTrue(stale_assignment_form.is_valid(), stale_assignment_form.errors)
        self.assertRedirects(
            self.client.post(reverse('operations:writeoff_cancel', args=[writeoff.pk]), {'reason': 'Ошибочная выдача'}),
            reverse('operations:writeoffs'),
        )
        stock.refresh_from_db()
        self.assertEqual(stock.actual_balance, Decimal('8'))

    def test_writeoff_from_stock_prefills_and_previews_available_quantity(self):
        self.client.force_login(self.operator)
        self.add_receipt()
        stock = Stock.objects.get()
        url = reverse('operations:writeoff_add')
        response = self.client.get(url, {'stock': stock.pk})
        self.assertEqual(response.context['form']['spares_list'].value(), stock.pk)
        self.assertContains(response, 'data-balance="8.00"')
        self.assertContains(response, 'data-price="7.50"')
        self.assertIsNone(self.client.get(url, {'stock': 'invalid'}).context['form']['spares_list'].value())

        self.client.post(url, {
            'spares_list': stock.pk,
            'machine_list': self.assignment.pk,
            'date': '2026-01-10',
            'quantity': '8',
        })
        self.assertIsNone(self.client.get(url, {'stock': stock.pk}).context['form']['spares_list'].value())
        edit_url = reverse('operations:writeoff_edit', args=[WriteOff.objects.get().pk])
        self.assertRedirects(self.client.get(edit_url), reverse('operations:writeoffs'))

    def test_stock_form_keeps_existing_identity(self):
        self.client.force_login(self.operator)
        self.add_receipt()
        stock = Stock.objects.get()
        form = StockForm(instance=stock, data={
            'spare': self.spare.pk,
            'company': self.company.pk,
            'warehouse': self.destination.pk,
            'price': '1',
            'actual_balance': '8',
            'inventory': '7',
            'plan': 'Сверить',
        })
        self.assertTrue(form.is_valid(), form.errors)
        updated = form.save()
        self.assertEqual(updated.warehouse, self.warehouse)
        self.assertEqual(updated.price, Decimal('7.50'))
        self.assertIsNone(updated.inventory)
        self.assertEqual(updated.plan, 'Сверить')

    def test_admin_uses_shared_writeoff_form_and_searchable_assignments(self):
        staff = get_user_model().objects.create_superuser(username='warehouse-admin')
        self.client.force_login(staff)
        receipt = self.add_receipt()
        stock = Stock.objects.get()
        change_list = self.client.get(reverse('admin:spares_machineworker_changelist'), {'q': 'Алексей'})
        self.assertContains(change_list, self.assignment.worker.name)

        add_url = reverse('admin:spares_writeoff_add')
        self.assertContains(self.client.get(add_url), 'warehouse-choice.js')
        response = self.client.post(add_url, {
            'spares_list': stock.pk,
            'machine_list': self.assignment.pk,
            'date': '2026-01-10',
            'quantity': '8',
        })
        self.assertRedirects(response, reverse('admin:spares_writeoff_changelist'))

        delete_url = reverse('admin:spares_receipt_delete', args=[receipt.pk])
        response = self.client.post(delete_url, {'post': 'yes'})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Receipt.objects.filter(pk=receipt.pk).exists())
