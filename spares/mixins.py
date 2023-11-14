"""Миксины приложения spares."""

from django.db import models


class NameMixin(models.Model):
    name = models.CharField(max_length=255, verbose_name='Название')

    class Meta:
        abstract = True


class CompanyMixin(models.Model):
    company = models.ForeignKey('spares.Company', on_delete=models.CASCADE, verbose_name='Фирма')

    class Meta:
        abstract = True


class SpareMixin(models.Model):
    spare = models.ForeignKey('spares.Spares', on_delete=models.CASCADE, verbose_name='Наименование')

    class Meta:
        abstract = True


class MeasureMixin(models.Model):
    measure = models.ForeignKey(
        'spares.MeasureMeasurement',
        on_delete=models.DO_NOTHING,
        verbose_name='Мера',
        null=True,
        blank=True
    )

    class Meta:
        abstract = True


class WarehouseMixin(models.Model):
    warehouse = models.ForeignKey('spares.Warehouses', on_delete=models.CASCADE, verbose_name='Склад')

    class Meta:
        abstract = True


class MachinesWorkersTrailersMixin(models.Model):
    machine = models.ForeignKey(
        'spares.Machines',
        on_delete=models.CASCADE,
        verbose_name='Техника',
        null=True,
        blank=True
    )
    worker = models.ForeignKey(
        'spares.Workers',
        on_delete=models.DO_NOTHING,
        verbose_name='Работник'
    )
    trailer = models.ForeignKey(
        'spares.Trailers',
        on_delete=models.DO_NOTHING,
        verbose_name='Прицепное',
        null=True,
        blank=True
    )

    class Meta:
        abstract = True


class PriceMixin(models.Model):
    price = models.DecimalField(verbose_name='Цена', default=0, max_digits=15, decimal_places=2)

    class Meta:
        abstract = True
