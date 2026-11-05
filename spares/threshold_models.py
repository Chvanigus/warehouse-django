"""Minimum stock rules aggregated across price lots."""

from decimal import Decimal

from django.apps import apps
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Round
from django.db.models.lookups import IsNull


class StockMinimumQuerySet(models.QuerySet):
    def with_available(self):
        stock = apps.get_model('spares', 'Stock')
        totals = (
            stock.objects.filter(
                spare_id=OuterRef('spare_id'),
                company_id=OuterRef('company_id'),
                warehouse_id=OuterRef('warehouse_id'),
            )
            .filter(
                Q(measure_id=OuterRef('measure_id'))
                | Q(IsNull(OuterRef('measure_id'), True), measure__isnull=True),
            )
            .order_by()
            .values('spare_id')
            .annotate(total=Round(Sum('actual_balance'), precision=2))
            .values('total')
        )
        return self.annotate(available=Coalesce(
            Subquery(totals), Value(Decimal('0.00')),
            output_field=models.DecimalField(max_digits=24, decimal_places=2),
        ))

    def below_minimum(self):
        return self.filter(available__lt=F('minimum'))


class StockMinimum(models.Model):
    spare = models.ForeignKey('spares.Spares', on_delete=models.PROTECT, verbose_name='Запчасть')
    company = models.ForeignKey('spares.Company', on_delete=models.PROTECT, verbose_name='Фирма')
    warehouse = models.ForeignKey('spares.Warehouses', on_delete=models.PROTECT, verbose_name='Склад')
    measure = models.ForeignKey(
        'spares.MeasureMeasurement', on_delete=models.PROTECT, blank=True, null=True,
        verbose_name='Единица измерения',
        help_text='Если оставить пустым, в расчёт войдут только остатки без единицы измерения.',
    )
    minimum = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name='Минимальный остаток',
        validators=[MinValueValidator(Decimal('0.01'))],
    )

    objects = StockMinimumQuerySet.as_manager()

    def __str__(self):
        unit = f' ({self.measure})' if self.measure_id else ''
        return f'{self.spare} · {self.warehouse} · {self.company}{unit}'

    class Meta:
        verbose_name = 'Минимальный остаток'
        verbose_name_plural = 'Минимальные остатки'
        constraints = [
            models.UniqueConstraint(
                fields=('spare', 'company', 'warehouse', 'measure'),
                condition=Q(measure__isnull=False), name='stock_minimum_with_measure',
                violation_error_message='Минимум для этой позиции уже задан.',
            ),
            models.UniqueConstraint(
                fields=('spare', 'company', 'warehouse'),
                condition=Q(measure__isnull=True), name='stock_minimum_without_measure',
                violation_error_message='Минимум для этой позиции уже задан.',
            ),
            models.CheckConstraint(condition=Q(minimum__gt=0), name='stock_minimum_positive'),
        ]
