"""Конкурирующие складские операции через отдельные подключения PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from time import sleep
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from django.utils import timezone

from spares import transfer_models
from spares.models import Company, Contractors, MeasureMeasurement, Receipt, Spares, Stock, Warehouses, Workers, WriteOff
from spares.transfer_models import StockTransfer, post_transfer


@skipUnless(connection.vendor == 'postgresql', 'Проверка настоящих блокировок PostgreSQL.')
class PostgreSQLConcurrencyTests(TransactionTestCase):
    """Проверяет целостность остатков при параллельных транзакциях разных сотрудников."""

    def setUp(self):
        """Создаёт справочники и двух независимых авторов без общей блокировки строки пользователя."""
        self.company = Company.objects.create(name='Фирма')
        self.warehouse = Warehouses.objects.create(name='Основной')
        self.other_warehouse = Warehouses.objects.create(name='Второй')
        self.spare = Spares.objects.create(name='Подшипник')
        self.measure = MeasureMeasurement.objects.create(name='шт.')
        self.contractor = Contractors.objects.create(name='Поставщик')
        self.worker = Workers.objects.create(name='Механик')
        self.actors = [get_user_model().objects.create_user(username=f'operator-{index}') for index in range(2)]
        self.key = {
            'company_id': self.company.pk, 'warehouse_id': self.warehouse.pk,
            'spare_id': self.spare.pk, 'price': Decimal('1.25'),
        }

    def _parallel(self, *operations):
        """Запускает операции на отдельных соединениях и ограничивает ожидание блокировок и потоков."""
        ready = Barrier(len(operations))

        def run(operation):
            """Открывает собственное соединение с ограничением времени и гарантированно закрывает его."""
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '3s'")
                    cursor.execute("SET statement_timeout = '8s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    backend_pid = cursor.fetchone()[0]
                ready.wait(timeout=5)
                return backend_pid, operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures = [executor.submit(run, operation) for operation in operations]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(len({backend_pid for backend_pid, _ in results}), len(operations))
        return [result for _, result in results]

    def _receipt(self, quantity, *, measure_id=None, warehouse_id=None):
        """Проводит приход с заданной единицей и складом в текущем соединении потока."""
        return Receipt.objects.create(
            **{**self.key, 'warehouse_id': warehouse_id or self.warehouse.pk},
            contractor_id=self.contractor.pk, invoice_number='Параллельный приход',
            quantity=quantity, measure_id=measure_id,
        ).pk

    @staticmethod
    def _slow_new_key_validation(stock, previous, using, update_fields=None):
        """Расширяет окно между проверкой отсутствия нового остатка и его вставкой."""
        PostgreSQLConcurrencyTests.original_key_validation(stock, previous, using, update_fields)
        if previous is None:
            sleep(0.15)

    original_key_validation = Stock._validate_key

    def test_concurrent_first_receipts_create_one_stock_with_and_without_measure(self):
        """Складывает оба первых прихода в одну позицию, включая ключ с пустой единицей измерения."""
        for measure_id in (None, self.measure.pk):
            with self.subTest(measure_id=measure_id), patch.object(
                Stock, '_validate_key', self._slow_new_key_validation,
            ):
                receipt_ids = self._parallel(
                    lambda: self._receipt('2.00', measure_id=measure_id),
                    lambda: self._receipt('3.00', measure_id=measure_id),
                )
                self.assertEqual(len(set(receipt_ids)), 2)
                stock = Stock.objects.get(**self.key, measure_id=measure_id)
                self.assertEqual((stock.input_quantity, stock.actual_balance), (Decimal('5.00'), Decimal('5.00')))

    def test_concurrent_manual_creation_rejects_duplicate_stock(self):
        """При прямом создании позиции сохраняет один остаток и сообщает об уже созданном втором."""
        def create_stock():
            """Возвращает результат ручного создания позиции без обхода модельных проверок."""
            try:
                Stock.objects.create(**self.key, actual_balance=5)
                return 'created'
            except ValidationError:
                return 'duplicate'

        with patch.object(Stock, '_validate_key', self._slow_new_key_validation):
            results = self._parallel(create_stock, create_stock)
        self.assertCountEqual(results, ['created', 'duplicate'])
        self.assertEqual(Stock.objects.filter(**self.key).count(), 1)

    def test_concurrent_writeoffs_cannot_overdraw_stock(self):
        """Проводит только одно из двух списаний, если суммарный запрос превышает остаток."""
        self._receipt('5.00')

        def write_off():
            """Пытается списать количество и возвращает ожидаемый бизнес-результат."""
            try:
                WriteOff.objects.create(
                    **self.key, worker_id=self.worker.pk, date=timezone.localdate(), quantity=Decimal('4.00'),
                )
                return 'posted'
            except ValidationError:
                return 'insufficient'

        self.assertCountEqual(self._parallel(write_off, write_off), ['posted', 'insufficient'])
        stock = Stock.objects.get(**self.key)
        self.assertEqual((stock.output_quantity, stock.actual_balance), (Decimal('4.00'), Decimal('1.00')))
        self.assertEqual(WriteOff.objects.count(), 1)

    def test_opposing_transfers_finish_without_deadlock(self):
        """Проводит встречные перемещения и сохраняет общий остаток при противоположном порядке складов."""
        self._receipt('10.00')
        self._receipt('10.00', warehouse_id=self.other_warehouse.pk)
        sources = [
            Stock.objects.get(**{**self.key, 'warehouse_id': warehouse.pk})
            for warehouse in (self.warehouse, self.other_warehouse)
        ]
        original_move = transfer_models._move_stock

        def slow_move(*args, **kwargs):
            """Даёт второй транзакции время начать после блокировки исходного остатка."""
            sleep(0.15)
            return original_move(*args, **kwargs)

        with patch('spares.transfer_models._move_stock', side_effect=slow_move):
            self._parallel(
                lambda: post_transfer(
                    source=sources[0], destination=self.other_warehouse, quantity=Decimal('2.50'),
                    date=timezone.localdate(), actor=self.actors[0],
                ).pk,
                lambda: post_transfer(
                    source=sources[1], destination=self.warehouse, quantity=Decimal('3.00'),
                    date=timezone.localdate(), actor=self.actors[1],
                ).pk,
            )
        for stock in sources:
            stock.refresh_from_db()
        self.assertEqual([stock.actual_balance for stock in sources], [Decimal('10.50'), Decimal('9.50')])
        self.assertEqual(StockTransfer.objects.count(), 2)

    def test_transfers_from_different_sources_create_one_destination_stock(self):
        """Объединяет одновременные перемещения с разных складов в один новый целевой остаток."""
        destination = Warehouses.objects.create(name='Общий получатель')
        self._receipt('5.00')
        self._receipt('5.00', warehouse_id=self.other_warehouse.pk)
        sources = [
            Stock.objects.get(**{**self.key, 'warehouse_id': warehouse.pk})
            for warehouse in (self.warehouse, self.other_warehouse)
        ]
        with patch.object(Stock, '_validate_key', self._slow_new_key_validation):
            self._parallel(*[
                lambda source=source, actor=actor: post_transfer(
                    source=source, destination=destination, quantity=Decimal('2.00'),
                    date=timezone.localdate(), actor=actor,
                ).pk
                for source, actor in zip(sources, self.actors)
            ])
        target = Stock.objects.get(**{**self.key, 'warehouse_id': destination.pk})
        self.assertEqual(target.actual_balance, Decimal('4.00'))
        self.assertEqual(StockTransfer.objects.count(), 2)
