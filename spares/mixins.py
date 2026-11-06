"""Абстрактные поля, общие для справочников, остатков и складских документов."""

from django.core.validators import MinValueValidator
from django.db import models


class NameMixin(models.Model):
    """Добавить справочное название записи."""

    name = models.CharField(max_length=255, verbose_name='Название')

    class Meta:
        """Объявить абстрактный набор полей без отдельной таблицы."""

        abstract = True


class CompanyMixin(models.Model):
    """Добавить ссылку на фирму с защитой от удаления используемой записи."""

    company = models.ForeignKey('spares.Company', on_delete=models.PROTECT, verbose_name='Фирма')

    class Meta:
        """Объявить абстрактный набор полей без отдельной таблицы."""

        abstract = True


class SpareMixin(models.Model):
    """Добавить ссылку на запчасть с защитой от удаления используемой записи."""

    spare = models.ForeignKey(
        'spares.Spares',
        on_delete=models.PROTECT,
        verbose_name='Наименование'
    )

    class Meta:
        """Объявить абстрактный набор полей без отдельной таблицы."""

        abstract = True


class MeasureMixin(models.Model):
    """Добавить необязательную единицу измерения."""

    measure = models.ForeignKey(
        'spares.MeasureMeasurement',
        on_delete=models.PROTECT,
        verbose_name='Мера',
        null=True,
        blank=True
    )

    class Meta:
        """Объявить абстрактный набор полей без отдельной таблицы."""

        abstract = True


class WarehouseMixin(models.Model):
    """Добавить склад, к которому относится документ или остаток."""

    warehouse = models.ForeignKey('spares.Warehouses', on_delete=models.PROTECT, verbose_name='Склад')

    class Meta:
        """Объявить абстрактный набор полей без отдельной таблицы."""

        abstract = True


class MachinesWorkersTrailersMixin(models.Model):
    """Добавить работника и необязательные ссылки на технику и прицеп."""

    machine = models.ForeignKey(
        'spares.Machines',
        on_delete=models.PROTECT,
        verbose_name='Техника',
        null=True,
        blank=True
    )
    worker = models.ForeignKey(
        'spares.Workers',
        on_delete=models.PROTECT,
        verbose_name='Работник'
    )
    trailer = models.ForeignKey(
        'spares.Trailers',
        on_delete=models.PROTECT,
        verbose_name='Прицепное',
        null=True,
        blank=True
    )

    class Meta:
        """Объявить абстрактный набор полей без отдельной таблицы."""

        abstract = True


class PriceMixin(models.Model):
    """Добавить неотрицательную цену с точностью до копеек."""

    price = models.DecimalField(
        verbose_name='Цена', default=0, max_digits=15, decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    class Meta:
        """Объявить абстрактный набор полей без отдельной таблицы."""

        abstract = True
