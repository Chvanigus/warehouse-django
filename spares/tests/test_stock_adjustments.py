from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from spares.models import (
    Company, Contractors, MeasureMeasurement, Receipt, Spares, Stock, StockAdjustment, Warehouses, Workers, WriteOff,
)
from spares.stock_adjustments import save_manual_stock


class StockAdjustmentServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user(username='storekeeper')
        cls.key = {
            'spare': Spares.objects.create(name='Фильтр'),
            'warehouse': Warehouses.objects.create(name='Основной склад'),
            'company': Company.objects.create(name='Фирма'),
            'measure': MeasureMeasurement.objects.create(name='шт.'),
            'price': Decimal('12.50'),
        }

    def test_records_opening_and_correction_with_actor_and_position_snapshots(self):
        stock = Stock(**self.key, actual_balance=Decimal('5.50'))
        start = timezone.now()
        save_manual_stock(stock, actor=self.actor, reason='  Начальная сверка  ')
        stock.actual_balance = Decimal('4.25')
        save_manual_stock(stock, actor=self.actor, reason='Уточнение пересчёта')

        correction, opening = StockAdjustment.objects.all()
        self.assertEqual((opening.before, opening.after, opening.delta), (0, Decimal('5.50'), Decimal('5.50')))
        self.assertEqual(opening.reason, 'Начальная сверка')
        self.assertEqual(
            (correction.before, correction.after, correction.delta),
            (Decimal('5.50'), Decimal('4.25'), Decimal('-1.25')),
        )
        self.assertEqual(correction.actor, self.actor)
        self.assertEqual(correction.actor_name, 'storekeeper')
        self.assertEqual(correction.stock, stock)
        self.assertEqual(correction.stock_label, 'Фильтр · Основной склад · Фирма · шт. · Цена 12.50')
        self.assertGreaterEqual(correction.created_at, start)

        self.actor.delete()
        stock.delete()
        correction.refresh_from_db()
        self.assertIsNone(correction.actor)
        self.assertIsNone(correction.stock)
        self.assertEqual(correction.actor_name, 'storekeeper')
        self.assertIn('Фильтр', correction.stock_label)

    def test_metadata_and_normal_operations_are_not_manual_adjustments(self):
        stock = save_manual_stock(Stock(**self.key), actor=self.actor, reason='')
        stock.plan = 'Проверить'
        stock.inventory = Decimal('3.50')
        save_manual_stock(stock, actor=self.actor, reason='')
        stock.refresh_from_db()
        self.assertEqual(stock.plan, 'Проверить')
        self.assertEqual(stock.inventory, Decimal('3.50'))
        self.assertTrue(stock.discrepancy)

        Receipt.objects.create(
            **self.key, quantity=5, invoice_number='1',
            contractor=Contractors.objects.create(name='Поставщик'),
        )
        WriteOff.objects.create(
            **self.key, quantity=2, worker=Workers.objects.create(name='Механик'), date=date(2026, 1, 2),
        )
        self.assertFalse(StockAdjustment.objects.exists())

        # An older object must not overwrite the counters changed by operations.
        stock.actual_balance = Decimal('4.25')
        save_manual_stock(stock, actor=self.actor, reason='Фактический пересчёт')
        stock.refresh_from_db()
        adjustment = StockAdjustment.objects.get()
        self.assertEqual((stock.input_quantity, stock.output_quantity), (5, 2))
        self.assertEqual((adjustment.before, adjustment.after), (3, Decimal('4.25')))

    def test_rejects_missing_reason_and_rolls_back_if_audit_insert_fails(self):
        stock = Stock.objects.create(**self.key, actual_balance=5)
        stock.actual_balance = 2
        with self.assertRaisesMessage(ValidationError, 'Укажите причину изменения остатка'):
            save_manual_stock(stock, actor=self.actor, reason='  ')
        self.assertEqual(Stock.objects.get(pk=stock.pk).actual_balance, 5)

        with patch('spares.stock_adjustments.StockAdjustment.objects.using') as manager:
            manager.return_value.create.side_effect = RuntimeError('Audit unavailable')
            with self.assertRaisesMessage(RuntimeError, 'Audit unavailable'):
                save_manual_stock(stock, actor=self.actor, reason='Сверка')
        self.assertEqual(Stock.objects.get(pk=stock.pk).actual_balance, 5)
        self.assertFalse(StockAdjustment.objects.exists())
