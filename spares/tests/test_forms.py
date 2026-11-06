"""Веб-сценарии поступления, списания, отмены и просмотра журналов."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from spares.forms import StockForm, WriteOffForm
from spares.models import (
    Company, Contractors, MachineWorker, Receipt, Spares, Stock, Warehouses,
    Workers, WriteOff,
)
from spares.request_models import StockRequest
from spares.request_services import approve_stock_request


class WarehouseOperationTests(TestCase):
    """Проверяет формы операций и разграничение прав между участниками."""

    @classmethod
    def setUpTestData(cls):
        """Создаёт справочники, данные прихода и две роли для проверки доступа."""
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
            content_type__model__in=['receipt', 'writeoff', 'movement', 'stockrequest'],
        ))
        cls.observer = get_user_model().objects.create_user(username='observer')
        cls.observer.user_permissions.add(Permission.objects.get(
            content_type__app_label='spares', codename='view_receipt',
        ))

    def add_receipt(self):
        """Отправляет корректную форму прихода и возвращает созданный документ."""
        response = self.client.post(reverse('operations:receipt_add'), self.receipt_data)
        self.assertRedirects(response, reverse('operations:receipts'))
        return Receipt.objects.get()

    def log_in_requester(self):
        """Входит под сотрудником, который подаёт заявки на приход и списание."""
        user = get_user_model().objects.create_user(username='requester')
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='spares',
            codename__in=('add_receipt', 'add_writeoff', 'add_stockrequest', 'view_stockrequest'),
        ))
        self.client.force_login(user)
        return user

    def test_permissions_separate_read_and_write_access(self):
        """Проверяет, что право просмотра прихода не даёт создавать документы."""
        receipt_list = reverse('operations:receipts')
        add_receipt = reverse('operations:receipt_add')
        self.assertEqual(self.client.get(receipt_list).status_code, 302)
        self.client.force_login(self.observer)
        self.assertNotContains(self.client.get(receipt_list), add_receipt)
        self.assertEqual(self.client.post(add_receipt, self.receipt_data).status_code, 403)
        self.assertEqual(self.client.get(reverse('operations:movements')).status_code, 403)
        self.assertFalse(Receipt.objects.exists())

    def test_requester_receipt_stays_pending_until_review(self):
        """Проверяет, что заявка на простой приход не меняет остаток до согласования."""
        requester = self.log_in_requester()
        response = self.client.post(reverse('operations:receipt_add'), self.receipt_data)
        stock_request = StockRequest.objects.get()
        self.assertRedirects(response, reverse('stock_requests:detail', args=[stock_request.pk]))
        self.assertEqual((stock_request.status, stock_request.created_by), (StockRequest.Status.PENDING, requester))
        self.assertFalse(Receipt.objects.exists())
        self.assertFalse(Stock.objects.exists())

        approved = approve_stock_request(stock_request.pk, actor=self.operator)
        receipt = Receipt.objects.get()
        self.assertEqual(approved.result['query'], {'entry': receipt.pk})
        self.assertEqual(Stock.objects.get().actual_balance, Decimal('8.00'))

    def test_requester_without_queue_view_returns_to_home(self):
        """Проверяет доступную страницу после подачи заявки с правами добавления."""
        requester = self.log_in_requester()
        requester.user_permissions.remove(Permission.objects.get(
            content_type__app_label='spares', codename='view_stockrequest',
        ))
        response = self.client.post(reverse('operations:receipt_add'), self.receipt_data)
        self.assertRedirects(response, reverse('spares:warehouse_main'))
        self.assertEqual(StockRequest.objects.get().status, StockRequest.Status.PENDING)
        self.assertFalse(Receipt.objects.exists())

    def test_review_rechecks_writeoff_after_stock_changes(self):
        """Оставляет заявку ожидающей, если после подачи товара стало недостаточно."""
        self.client.force_login(self.operator)
        self.add_receipt()
        stock = Stock.objects.get()
        self.log_in_requester()
        response = self.client.post(reverse('operations:writeoff_add'), {
            'spares_list': stock.pk, 'machine_list': self.assignment.pk,
            'date': self.receipt_data['date'], 'quantity': '5',
        })
        stock_request = StockRequest.objects.get(kind=StockRequest.Kind.WRITEOFF)
        self.assertRedirects(response, reverse('stock_requests:detail', args=[stock_request.pk]))
        self.assertFalse(WriteOff.objects.exists())
        self.assertEqual(Stock.objects.get().actual_balance, Decimal('8.00'))
        WriteOff.objects.create(
            spare=self.spare, company=self.company, warehouse=self.warehouse, price=stock.price,
            date=self.receipt_data['date'], quantity=4, worker=self.assignment.worker,
        )

        with self.assertRaisesMessage(ValidationError, 'Количество превышает доступный остаток'):
            approve_stock_request(stock_request.pk, actor=self.operator)
        stock_request.refresh_from_db()
        self.assertEqual(stock_request.status, StockRequest.Status.PENDING)
        self.assertEqual(Stock.objects.get().actual_balance, Decimal('4.00'))
        self.assertEqual(WriteOff.objects.count(), 1)

    def test_review_rejects_changed_assignment(self):
        """Не подменяет выбранного получателя после редактирования назначения."""
        self.client.force_login(self.operator)
        self.add_receipt()
        stock = Stock.objects.get()
        self.log_in_requester()
        self.client.post(reverse('operations:writeoff_add'), {
            'spares_list': stock.pk, 'machine_list': self.assignment.pk,
            'date': self.receipt_data['date'], 'quantity': '2',
        })
        stock_request = StockRequest.objects.get(kind=StockRequest.Kind.WRITEOFF)
        replacement = Workers.objects.create(name='Новый получатель')
        MachineWorker.objects.filter(pk=self.assignment.pk).update(worker=replacement)

        with self.assertRaisesMessage(ValidationError, 'Назначение техники изменилось'):
            approve_stock_request(stock_request.pk, actor=self.operator)
        self.assertFalse(WriteOff.objects.exists())
        self.assertEqual(Stock.objects.get().actual_balance, Decimal('8.00'))

    def test_journal_combines_text_search_and_dates(self):
        """Проверяет сочетание поиска и дат, ошибку периода и ссылку на отдельную запись."""
        self.client.force_login(self.operator)
        receipt = self.add_receipt()
        url = reverse('operations:receipts')
        self.assertContains(self.client.get(url, {'q': 'фильтр', 'date_from': '2026-01-10'}), 'НК-100')
        self.assertNotContains(self.client.get(url, {'q': 'фильтр', 'date_to': '2026-01-09'}), 'НК-100')
        response = self.client.get(url, {'date_from': '2026-02-01', 'date_to': '2026-01-01'})
        self.assertContains(response, 'Конец периода должен быть не раньше начала')
        self.assertNotContains(response, 'НК-100')
        self.client.post(reverse('operations:receipt_add'), {**self.receipt_data, 'invoice_number': 'НК-200'})
        response = self.client.get(url, {'entry': receipt.pk})
        self.assertContains(response, 'НК-100')
        self.assertNotContains(response, 'НК-200')

    def test_operator_can_create_and_cancel_receipt_without_overwriting_it(self):
        """Проверяет отмену прихода с возвратом остатка и сохранением исходного документа."""
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
        """Проверяет доступное количество и возврат остатка при отмене списания."""
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
        """Проверяет подстановку выбранной позиции и показ её количества и цены."""
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
        """Проверяет, что форма остатка принимает правку плана и сохраняет исходную позицию."""
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
        """Проверяет форму списания и поиск назначений техники в админке."""
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
