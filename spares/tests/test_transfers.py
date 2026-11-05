from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from spares.models import Company, Contractors, MeasureMeasurement, Movement, Receipt, Spares, Stock, Warehouses
from spares.transfer_models import StockTransfer, cancel_transfer, post_transfer


class TransferTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user(username='operator')
        cls.company = Company.objects.create(name='Фирма')
        cls.source_warehouse = Warehouses.objects.create(name='Основной склад')
        cls.destination = Warehouses.objects.create(name='Мастерская')
        cls.spare = Spares.objects.create(name='Подшипник')
        cls.measure = MeasureMeasurement.objects.create(name='шт.')
        cls.receipt = Receipt.objects.create(
            company=cls.company, spare=cls.spare, measure=cls.measure, warehouse=cls.source_warehouse,
            contractor=Contractors.objects.create(name='Поставщик'), invoice_number='17',
            date=timezone.localdate(), quantity=10, price=Decimal('45.50'),
        )
        cls.source = Stock.matching(cls.receipt).get()

    def transfer(self, **overrides):
        data = {
            'source': self.source, 'destination': self.destination, 'quantity': '2.50',
            'date': timezone.localdate(), 'actor': self.actor, 'note': '  Для ремонта  ',
        }
        return post_transfer(**{**data, **overrides})

    def destination_stocks(self):
        return Stock.objects.filter(warehouse=self.destination, spare=self.spare)

    def grant(self, *codenames):
        self.actor.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='spares', content_type__model='stocktransfer', codename__in=codenames,
        ))

    def test_transfer_preserves_receipt_and_merges_only_matching_identity(self):
        unrelated = Stock.objects.create(
            spare=self.spare, company=self.company, warehouse=self.destination,
            measure=self.measure, price=Decimal('48.00'), actual_balance=3,
        )
        transfer = self.transfer()
        self.transfer(quantity='1.25')

        self.source.refresh_from_db()
        self.receipt.refresh_from_db()
        target = self.destination_stocks().exclude(pk=unrelated.pk).get()
        unrelated.refresh_from_db()
        self.assertEqual(self.source.actual_balance, Decimal('6.25'))
        self.assertEqual((self.source.input_quantity, self.source.output_quantity), (10, 0))
        self.assertEqual((target.actual_balance, target.input_quantity, target.output_quantity), (Decimal('3.75'), 0, 0))
        self.assertEqual((target.price, target.measure, target.company), (self.source.price, self.measure, self.company))
        self.assertEqual(unrelated.actual_balance, 3)
        self.assertEqual((self.receipt.warehouse, self.receipt.quantity), (self.source_warehouse, 10))
        self.assertFalse(Movement.objects.exists())
        self.assertEqual((transfer.actor_name, transfer.note), ('operator', 'Для ремонта'))

    def test_invalid_or_stale_requests_do_not_overdraw(self):
        with self.assertRaisesMessage(ValidationError, 'Дата проведения не может быть в будущем.'):
            self.transfer(date=timezone.localdate() + timedelta(days=1))
        with self.assertRaisesMessage(ValidationError, 'Выберите другой склад назначения.'):
            self.transfer(destination=self.source_warehouse)
        self.transfer(quantity=6)
        with self.assertRaisesMessage(ValidationError, 'Количество превышает доступный остаток.'):
            self.transfer(quantity=5)

        self.source.refresh_from_db()
        self.assertEqual(self.source.actual_balance, 4)
        self.assertEqual(self.destination_stocks().get().actual_balance, 6)
        self.assertEqual(StockTransfer.objects.count(), 1)

    def test_failed_document_save_rolls_back_both_balances(self):
        with patch.object(StockTransfer, 'save', side_effect=ValidationError('Ошибка записи')):
            with self.assertRaisesMessage(ValidationError, 'Ошибка записи'):
                self.transfer()
        self.source.refresh_from_db()
        self.assertEqual(self.source.actual_balance, 10)
        self.assertFalse(self.destination_stocks().exists())
        self.assertFalse(StockTransfer.objects.exists())

    def test_cancellation_fails_if_destination_no_longer_has_quantity(self):
        transfer = self.transfer()
        third_warehouse = Warehouses.objects.create(name='Резерв')
        self.transfer(source=self.destination_stocks().get(), destination=third_warehouse, quantity=1)

        with self.assertRaisesMessage(ValidationError, 'Количество превышает доступный остаток.'):
            cancel_transfer(transfer, actor=self.actor, reason='Неверный склад')

        transfer.refresh_from_db()
        self.source.refresh_from_db()
        self.assertIsNone(transfer.cancelled_at)
        self.assertEqual(self.source.actual_balance, Decimal('7.50'))
        self.assertEqual(self.destination_stocks().get().actual_balance, Decimal('1.50'))

    def test_cancellation_restores_balances_and_preserves_original_document(self):
        transfer = self.transfer()
        self.client.force_login(self.actor)
        self.grant('view_stocktransfer')
        cancel_url = reverse('transfers:cancel', args=[transfer.pk])
        detail = reverse('transfers:detail', args=[transfer.pk])
        reason = {'reason': '  Ошибка склада  '}
        self.assertEqual(self.client.post(cancel_url, reason).status_code, 403)
        self.grant('delete_stocktransfer')
        self.assertContains(self.client.post(cancel_url, {'reason': ' '}), 'Обязательное поле')

        self.assertRedirects(self.client.post(cancel_url, reason), detail)
        self.assertContains(self.client.get(detail), 'Ошибка склада')
        self.assertContains(self.client.get(reverse('transfers:list')), 'Отменено')
        with self.assertRaisesMessage(ValidationError, 'Документ уже отменён.'):
            cancel_transfer(transfer, actor=self.actor, reason='Повтор')
        self.assertEqual(self.client.post(cancel_url, reason).status_code, 404)

        transfer.refresh_from_db()
        self.source.refresh_from_db()
        target = self.destination_stocks().get()
        self.assertEqual((self.source.actual_balance, self.source.input_quantity, self.source.output_quantity), (10, 10, 0))
        self.assertEqual((target.actual_balance, target.input_quantity, target.output_quantity), (0, 0, 0))
        self.assertIsNotNone(transfer.cancelled_at)
        self.assertEqual((transfer.cancelled_by, transfer.cancelled_by_name, transfer.cancellation_reason),
                         (self.actor, 'operator', 'Ошибка склада'))
        self.assertEqual((transfer.quantity, transfer.from_warehouse, transfer.to_warehouse),
                         (Decimal('2.50'), self.source_warehouse, self.destination))
        self.assertEqual(StockTransfer.objects.count(), 1)

    def test_web_permissions_posting_and_read_only_history(self):
        self.client.force_login(self.actor)
        list_url = reverse('transfers:list')
        add_url = reverse('transfers:add')
        data = {
            'source': self.source.pk, 'destination': self.destination.pk,
            'quantity': '2.5', 'date': timezone.localdate().isoformat(), 'note': 'Для ремонта',
        }
        self.assertEqual(self.client.get(list_url).status_code, 403)
        self.assertEqual(self.client.post(add_url, data).status_code, 403)
        self.grant('view_stocktransfer')
        self.assertContains(self.client.get(list_url), 'Перемещений пока нет')
        self.assertEqual(self.client.post(add_url, data).status_code, 403)

        self.grant('add_stocktransfer')
        form = self.client.get(add_url, {'stock': self.source.pk}).context['form']
        self.assertEqual(form.initial['source'], self.source.pk)
        response = self.client.post(add_url, data)
        transfer = StockTransfer.objects.get()
        detail = reverse('transfers:detail', args=[transfer.pk])
        self.assertRedirects(response, detail)
        self.assertContains(self.client.get(detail), 'Для ремонта')
        self.assertContains(self.client.get(list_url, {'q': 'подшипник'}), 'Мастерская')
        self.assertEqual(self.client.post(detail, data).status_code, 405)
