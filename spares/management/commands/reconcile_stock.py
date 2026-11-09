"""Поиск и объединение дубликатов складских остатков."""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from spares.database_lock import lock_warehouse_writes
from spares.models import Stock


class Command(BaseCommand):
    """Команда Django для просмотра дубликатов и ручного объединения одного набора остатков."""

    help = 'Показывает дубли остатков или объединяет указанные записи одного остатка.'

    def add_arguments(self, parser):
        """Добавить параметр со всеми номерами дубликатов, начиная с сохраняемого."""
        parser.add_argument(
            '--merge', nargs='+', type=int, metavar='ID',
            help='Укажите все ID одного остатка. Сохраняется запись с первым указанным ID.',
        )

    def handle(self, *args, **options):
        """Вывести дубликаты или атомарно объединить указанную группу."""
        ids = options['merge']
        if ids is None:
            self.list_duplicates()
            return
        if len(ids) < 2 or len(ids) != len(set(ids)):
            raise CommandError('Укажите минимум два разных ID.')
        try:
            with transaction.atomic():
                self.merge(ids)
        except ValidationError as error:
            raise CommandError(' '.join(error.messages)) from error
        self.stdout.write(f'Записи объединены. Сохранён остаток #{ids[0]}.')

    def list_duplicates(self):
        """Показать дублирующиеся позиции со счётчиками, планом и результатом пересчёта."""
        groups = (
            Stock.objects.values(*Stock.key_fields)
            .annotate(count=Count('pk'))
            .filter(count__gt=1)
            .order_by(*Stock.key_fields)
        )
        if not groups:
            self.stdout.write('Дубли остатков не найдены.')
            return
        for group in groups:
            key = {field: group[field] for field in Stock.key_fields}
            stocks = Stock.objects.filter(**key).select_related(
                'spare', 'warehouse', 'measure', 'company',
            ).order_by('pk')
            for stock in stocks:
                self.stdout.write(
                    f'#{stock.pk} {stock} | Приход: {stock.input_quantity} | Расход: {stock.output_quantity}'
                    f' | Инвентаризация: {stock.inventory} | План: {stock.plan}'
                )
            self.stdout.write('')

    def merge(self, ids):
        """Сложить количества всей группы после проверки совместимости и удалить лишние записи."""
        lock_warehouse_writes()
        retained = Stock.objects.select_for_update().filter(pk=ids[0]).first()
        if retained is None:
            raise CommandError(f'Остаток #{ids[0]} не найден.')
        group = list(Stock.matching(retained).select_for_update().order_by('pk'))
        if set(ids) != {stock.pk for stock in group}:
            group_ids = ', '.join(str(stock.pk) for stock in group)
            raise CommandError(f'Укажите ровно все записи одного остатка. ID этой группы: {group_ids}.')

        plans = {stock.plan for stock in group if stock.plan}
        inventories = {stock.inventory for stock in group if stock.inventory is not None}
        if len(plans) > 1 or len(inventories) > 1:
            raise CommandError(
                'Записи содержат разные планы или результаты инвентаризации. '
                'Сверьте эти поля перед объединением.'
            )

        retained.plan = next(iter(plans), '')
        if any(stock.inventory_book_balance is not None for stock in group):
            retained.inventory = retained.inventory_book_balance = None
        else:
            retained.inventory = next(iter(inventories), None)
        totals = ('input_quantity', 'output_quantity', 'actual_balance')
        for field in totals:
            total = sum(getattr(stock, field) for stock in group)
            total = retained._meta.get_field(field).clean(total, retained)
            setattr(retained, field, total)
        retained.save(update_fields={*totals, 'plan', 'inventory', 'inventory_book_balance'})
        Stock.objects.filter(pk__in=ids[1:]).delete()
