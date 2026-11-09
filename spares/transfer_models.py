"""Перемещения остатков между складами и их отмена."""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, router, transaction
from django.utils import timezone

from .database_lock import lock_warehouse_writes
from .mixins import CompanyMixin, MeasureMixin, PriceMixin, SpareMixin
from .models import Stock, Warehouses
from .validators import require_operation_actor, validate_posting_date


class StockTransfer(CompanyMixin, SpareMixin, MeasureMixin, PriceMixin):
    """Документ перемещения между двумя складами с данными автора и отмены."""

    from_warehouse = models.ForeignKey(
        Warehouses, on_delete=models.PROTECT, related_name='transfers_out', verbose_name='Со склада',
    )
    to_warehouse = models.ForeignKey(
        Warehouses, on_delete=models.PROTECT, related_name='transfers_in', verbose_name='На склад',
    )
    quantity = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name='Количество',
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    date = models.DateField(
        default=timezone.localdate, validators=[validate_posting_date], verbose_name='Дата документа',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Время проведения')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='stock_transfers', verbose_name='Автор',
    )
    actor_name = models.CharField(max_length=150, verbose_name='Имя пользователя при проведении')
    note = models.CharField(max_length=500, blank=True, verbose_name='Примечание')
    cancelled_at = models.DateTimeField(null=True, editable=False, verbose_name='Время отмены')
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False,
        related_name='cancelled_stock_transfers', verbose_name='Кто отменил',
    )
    cancelled_by_name = models.CharField(max_length=150, blank=True, editable=False, verbose_name='Автор отмены')
    cancellation_reason = models.CharField(max_length=500, blank=True, editable=False, verbose_name='Причина отмены')

    class Meta:
        """Задать права, порядок и ограничения на количество и разные склады."""

        default_permissions = ('add', 'delete', 'view')
        ordering = ('-date', '-pk')
        verbose_name = 'Перемещение запчастей'
        verbose_name_plural = 'Перемещения запчастей'
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name='transfer_quantity_positive'),
            models.CheckConstraint(
                condition=~models.Q(from_warehouse=models.F('to_warehouse')),
                name='transfer_warehouses_differ',
            ),
        ]

    def __str__(self):
        """Вернуть подпись перемещения с номером документа."""
        return f'Перемещение № {self.pk}'


def _move_stock(stocks, source_key, destination_id, quantity):
    """Списать количество с исходной позиции и прибавить его к позиции на другом складе."""
    try:
        source = stocks.get(**source_key)
    except Stock.DoesNotExist as error:
        raise ValidationError('Исходный остаток больше не существует.') from error
    except Stock.MultipleObjectsReturned as error:
        raise ValidationError('На исходном складе есть дублирующиеся остатки. Сначала сверьте их.') from error
    if quantity > source.actual_balance:
        raise ValidationError('Количество превышает доступный остаток.')

    destination_key = {**source_key, 'warehouse_id': destination_id}
    try:
        target = stocks.get(**destination_key)
    except Stock.DoesNotExist:
        target = Stock(**destination_key)
    except Stock.MultipleObjectsReturned as error:
        raise ValidationError('На складе назначения есть дублирующиеся остатки. Сначала сверьте их.') from error

    balance_field = Stock._meta.get_field('actual_balance')
    target.actual_balance = balance_field.clean(target.actual_balance + quantity, target)
    source.actual_balance -= quantity
    source.save(using=stocks.db, update_fields={'actual_balance'})
    if target._state.adding:
        target.save(using=stocks.db)
    else:
        target.save(using=stocks.db, update_fields={'actual_balance'})


def post_transfer(*, source, destination, quantity, date, actor, note=''):
    """Проверить реквизиты и сохранить перемещение с обоими изменениями остатков атомарно."""
    require_operation_actor(actor, 'Для проведения перемещения нужен автор.')
    quantity = StockTransfer._meta.get_field('quantity').clean(quantity, None)
    date = StockTransfer._meta.get_field('date').clean(date, None)
    note = StockTransfer._meta.get_field('note').clean((note or '').strip(), None)
    using = router.db_for_write(Stock, instance=source)
    with transaction.atomic(using=using):
        lock_warehouse_writes(using)
        stocks = Stock.objects.using(using).select_for_update()
        try:
            source = stocks.get(pk=source.pk)
        except Stock.DoesNotExist as error:
            raise ValidationError('Исходный остаток больше не существует.') from error
        if source.warehouse_id == destination.pk:
            raise ValidationError('Выберите другой склад назначения.')
        if not Warehouses.objects.using(using).filter(pk=destination.pk).exists():
            raise ValidationError('Склад назначения больше не существует.')
        _move_stock(stocks, Stock.key_for(source), destination.pk, quantity)
        return StockTransfer.objects.using(using).create(
            spare_id=source.spare_id,
            company_id=source.company_id,
            measure_id=source.measure_id,
            price=source.price,
            from_warehouse_id=source.warehouse_id,
            to_warehouse_id=destination.pk,
            quantity=quantity,
            date=date,
            actor=actor,
            actor_name=actor.get_username(),
            note=note,
        )


def cancel_transfer(transfer, *, actor, reason):
    """Вернуть количество на исходный склад и сохранить причину отмены в одной транзакции."""
    require_operation_actor(actor, 'Для отмены нужен автор.')
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError('Укажите причину отмены.')
    reason = StockTransfer._meta.get_field('cancellation_reason').clean(reason, transfer)
    using = router.db_for_write(StockTransfer, instance=transfer)
    with transaction.atomic(using=using):
        lock_warehouse_writes(using)
        try:
            transfer = StockTransfer.objects.using(using).select_for_update().get(pk=transfer.pk)
        except StockTransfer.DoesNotExist as error:
            raise ValidationError('Документ отсутствует.') from error
        if transfer.cancelled_at is not None:
            raise ValidationError('Документ уже отменён.')

        stock_key = {
            'spare_id': transfer.spare_id, 'company_id': transfer.company_id, 'measure_id': transfer.measure_id,
            'price': transfer.price, 'warehouse_id': transfer.to_warehouse_id,
        }
        _move_stock(
            Stock.objects.using(using).select_for_update(), stock_key, transfer.from_warehouse_id, transfer.quantity,
        )
        transfer.cancelled_at = timezone.now()
        transfer.cancelled_by = actor
        transfer.cancelled_by_name = actor.get_username()
        transfer.cancellation_reason = reason
        transfer.save(
            using=using, update_fields={'cancelled_at', 'cancelled_by', 'cancelled_by_name', 'cancellation_reason'},
        )
        return transfer
