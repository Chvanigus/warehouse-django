"""Согласованность складских остатков и объединение старых дублей."""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.db import transaction
from django.db.models import ProtectedError
from django.test import TestCase

from spares.models import (
    Company, Contractors, MeasureMeasurement, Movement, Receipt, Spares, Stock,
    Warehouses, Workers, WriteOff,
)


class InventoryTests(TestCase):
    """Проверяет изменение накопленных приходов, расходов и доступного количества."""

    @classmethod
    def setUpTestData(cls):
        """Создаёт справочники, склады и единицы для операций с остатками."""
        cls.spare = Spares.objects.create(name='Болт')
        cls.warehouse = Warehouses.objects.create(name='Основной')
        cls.other_warehouse = Warehouses.objects.create(name='Запасной')
        cls.company = Company.objects.create(name='Фирма')
        cls.measure = MeasureMeasurement.objects.create(name='шт.')
        cls.contractor = Contractors.objects.create(
            name='Поставщик', contact_name='Сотрудник', contact='123456',
        )
        cls.worker = Workers.objects.create(name='Механик')
        cls.stock_key = {
            'spare': cls.spare, 'warehouse': cls.warehouse, 'company': cls.company, 'price': Decimal('1.25'),
        }

    def receipt(self, quantity, **fields):
        """Создаёт приход с типовыми реквизитами и переданными переопределениями."""
        return Receipt.objects.create(
            contractor=self.contractor, invoice_number='001', quantity=quantity,
            **(self.stock_key | fields),
        )

    def writeoff(self, quantity, **fields):
        """Создаёт списание с типовыми реквизитами и переданными переопределениями."""
        return WriteOff.objects.create(
            worker=self.worker, date=date(2026, 1, 2), quantity=quantity,
            **(self.stock_key | fields),
        )

    def assert_stock(self, operation, *, received, used, balance):
        """Сверяет накопленный приход, расход и остаток выбранной позиции."""
        stock = Stock.matching(operation).get()
        self.assertEqual((stock.input_quantity, stock.output_quantity, stock.actual_balance),
                         (received, used, balance))

    def test_receipt_updates_amount_and_applies_only_quantity_difference(self):
        """Проверяет пересчёт суммы прихода и применение только разницы количества."""
        receipt = self.receipt('2.50')
        self.assertEqual(receipt.amount, Decimal('3.13'))
        receipt.save()
        self.assert_stock(receipt, received=Decimal('2.50'), used=0, balance=Decimal('2.50'))

        receipt.quantity = Decimal('3.75')
        receipt.save(update_fields={'invoice_number'})
        self.assertEqual(receipt.amount, Decimal('3.13'))
        self.assert_stock(receipt, received=Decimal('2.50'), used=0, balance=Decimal('2.50'))

        receipt.save(update_fields={'quantity'})
        receipt.refresh_from_db()
        self.assertEqual(receipt.amount, Decimal('4.69'))
        self.assert_stock(receipt, received=Decimal('3.75'), used=0, balance=Decimal('3.75'))
        receipt.delete()
        self.assert_stock(receipt, received=0, used=0, balance=0)

    def test_move_only_selected_receipt_into_existing_stock(self):
        """Проверяет перенос одного прихода с сохранением прочих поступлений."""
        original = self.receipt(7)
        moved = self.receipt(2)
        self.receipt(3, warehouse=self.other_warehouse)

        moved.warehouse = self.other_warehouse
        moved.save(update_fields={'warehouse'})
        moved.save()
        self.assert_stock(original, received=7, used=0, balance=7)
        self.assert_stock(moved, received=5, used=0, balance=5)
        audit = Movement.objects.get()
        self.assertEqual((audit.spare, audit.from_warehouse, audit.to_warehouse),
                         (self.spare, self.warehouse, self.other_warehouse))

    def test_writeoff_uses_measure_and_restores_balance_on_bulk_delete(self):
        """Проверяет учёт единицы измерения и возврат остатка при групповом удалении."""
        counted = self.receipt(5, measure=self.measure)
        unmeasured = self.receipt(4)
        entry = self.writeoff(3, measure=self.measure)
        entry.quantity = 4
        entry.save()

        self.assert_stock(counted, received=5, used=4, balance=1)
        self.assert_stock(unmeasured, received=4, used=0, balance=4)
        self.assertEqual(entry.total_amount, Decimal('5.00'))
        WriteOff.objects.filter(pk=entry.pk).delete()
        self.assert_stock(counted, received=5, used=0, balance=5)

    def test_failed_writeoff_change_rolls_back_both_stock_keys(self):
        """Проверяет откат остатков обеих позиций при ошибке изменения списания."""
        original = self.receipt(5)
        target = self.receipt(2, warehouse=self.other_warehouse)
        entry = self.writeoff(3)

        entry.warehouse = self.other_warehouse
        with self.assertRaises(ValidationError):
            entry.save()
        entry.refresh_from_db()
        self.assertEqual(entry.warehouse, self.warehouse)
        self.assert_stock(original, received=5, used=3, balance=2)
        self.assert_stock(target, received=2, used=0, balance=2)

    def test_cannot_reduce_or_delete_receipt_if_stock_has_been_used(self):
        """Проверяет запрет уменьшения или удаления уже израсходованного поступления."""
        receipt = self.receipt(5)
        self.writeoff(4)

        receipt.quantity = 3
        with self.assertRaises(ValidationError):
            receipt.save()
        with self.assertRaises(ValidationError), transaction.atomic():
            Receipt.objects.filter(pk=receipt.pk).delete()
        receipt.refresh_from_db()
        self.assertEqual(receipt.quantity, 5)
        self.assert_stock(receipt, received=5, used=4, balance=1)

    def test_manual_balance_and_inventory_are_preserved(self):
        """Проверяет сохранение ручного остатка и сведений пересчёта."""
        stock = Stock.objects.create(**self.stock_key, actual_balance=7, inventory=7)
        self.assertFalse(stock.discrepancy)

        receipt = self.receipt(3)
        entry = self.writeoff(2)
        self.assert_stock(receipt, received=3, used=2, balance=8)
        stock.refresh_from_db()
        self.assertTrue(stock.discrepancy)

        entry.delete()
        receipt.delete()
        self.assert_stock(receipt, received=0, used=0, balance=7)
        stock.refresh_from_db()
        self.assertFalse(stock.discrepancy)

    def test_writeoff_requires_existing_stock_and_positive_quantity(self):
        """Проверяет отказ для списания без остатка или с неположительным количеством."""
        with self.assertRaises(ValidationError):
            self.writeoff(1)
        self.receipt(4)
        with self.assertRaises(ValidationError):
            self.writeoff(0)
        with self.assertRaises(ValidationError):
            self.writeoff(5)
        self.assertFalse(WriteOff.objects.exists())

    def test_catalog_references_are_protected_and_duplicate_stock_is_rejected(self):
        """Проверяет защиту используемых справочников и уникальность остатка."""
        self.receipt(1)
        with self.assertRaises(ProtectedError):
            self.contractor.delete()
        with self.assertRaises(ProtectedError):
            self.warehouse.delete()
        with self.assertRaises(ValidationError):
            Stock.objects.create(**self.stock_key)

    def test_reconcile_legacy_duplicates_retains_totals_and_metadata(self):
        """Проверяет суммирование количества и сохранение метаданных при объединении дублей."""
        receipt = self.receipt(5)
        retained = Stock.matching(receipt).get()
        # A legacy import or bulk operation can bypass Stock.save().
        duplicate = Stock.objects.bulk_create([
            Stock(**self.stock_key, input_quantity=3, output_quantity=1, actual_balance=2, plan='Проверить'),
        ])[0]
        listed = StringIO()
        call_command('reconcile_stock', stdout=listed)
        self.assertIn(f'#{retained.pk}', listed.getvalue())
        self.assertIn(f'#{duplicate.pk}', listed.getvalue())

        with self.assertRaises(ValidationError):
            self.writeoff(1)
        call_command('reconcile_stock', '--merge', str(retained.pk), str(duplicate.pk), stdout=StringIO())
        self.assert_stock(receipt, received=8, used=1, balance=7)
        retained.refresh_from_db()
        self.assertEqual(retained.plan, 'Проверить')
        self.assertFalse(Stock.objects.filter(pk=duplicate.pk).exists())
        self.writeoff(2)
        self.assert_stock(receipt, received=8, used=3, balance=5)

    def test_reconcile_legacy_duplicates_requires_complete_group_and_compatible_inventory(self):
        """Проверяет отказ для неполной группы дублей или несовместимых пересчётов."""
        stocks = Stock.objects.bulk_create([
            Stock(**self.stock_key, actual_balance=2, inventory=count)
            for count in (2, 3, None)
        ])
        ids = [str(stock.pk) for stock in stocks]
        with self.assertRaisesMessage(CommandError, 'ровно все записи'):
            call_command('reconcile_stock', '--merge', *ids[:2])
        with self.assertRaisesMessage(CommandError, 'разные планы или результаты'):
            call_command('reconcile_stock', '--merge', *ids)
        self.assertEqual(Stock.objects.count(), 3)
