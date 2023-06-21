"""Модели приложения reports."""
import datetime

from django.db import models

from reports.utils import calculate_total_company
from spares.models import Company, Workers


class IncomeReport(models.Model):
    """Модель таблицы отчёта по приходу."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, verbose_name='Фирма')
    total_company = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Итого')
    january = models.DecimalField(verbose_name='Январь', max_digits=10, decimal_places=2, null=True, blank=True)
    february = models.DecimalField(verbose_name='Февраль', max_digits=10, decimal_places=2, null=True, blank=True)
    march = models.DecimalField(verbose_name='Март', max_digits=10, decimal_places=2, null=True, blank=True)
    april = models.DecimalField(verbose_name='Апрель', max_digits=10, decimal_places=2, null=True, blank=True)
    may = models.DecimalField(verbose_name='Май', max_digits=10, decimal_places=2, null=True, blank=True)
    june = models.DecimalField(verbose_name='Июнь', max_digits=10, decimal_places=2, null=True, blank=True)
    july = models.DecimalField(verbose_name='Июль', max_digits=10, decimal_places=2, null=True, blank=True)
    august = models.DecimalField(verbose_name='Август', max_digits=10, decimal_places=2, null=True, blank=True)
    september = models.DecimalField(verbose_name='Сентябрь', max_digits=10, decimal_places=2, null=True, blank=True)
    october = models.DecimalField(verbose_name='Октябрь', max_digits=10, decimal_places=2, null=True, blank=True)
    november = models.DecimalField(verbose_name='Ноябрь', max_digits=10, decimal_places=2, null=True, blank=True)
    december = models.DecimalField(verbose_name='Декабрь', max_digits=10, decimal_places=2, null=True, blank=True)
    year = models.IntegerField(verbose_name='Год', default=datetime.datetime.now().year)

    class Meta:
        verbose_name_plural = 'Отчёты по приходу'
        verbose_name = 'Отчёт по приходу'

    def save(self, *args, **kwargs):
        self.total_company = calculate_total_company(self)
        super(IncomeReport, self).save(*args, **kwargs)


class OutcomeReport(models.Model):
    """Модель таблицы отчёта по расходу."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, verbose_name='Фирма')
    total_company = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Итого')
    january = models.DecimalField(verbose_name='Январь', max_digits=10, decimal_places=2, null=True, blank=True)
    february = models.DecimalField(verbose_name='Февраль', max_digits=10, decimal_places=2, null=True, blank=True)
    march = models.DecimalField(verbose_name='Март', max_digits=10, decimal_places=2, null=True, blank=True)
    april = models.DecimalField(verbose_name='Апрель', max_digits=10, decimal_places=2, null=True, blank=True)
    may = models.DecimalField(verbose_name='Май', max_digits=10, decimal_places=2, null=True, blank=True)
    june = models.DecimalField(verbose_name='Июнь', max_digits=10, decimal_places=2, null=True, blank=True)
    july = models.DecimalField(verbose_name='Июль', max_digits=10, decimal_places=2, null=True, blank=True)
    august = models.DecimalField(verbose_name='Август', max_digits=10, decimal_places=2, null=True, blank=True)
    september = models.DecimalField(verbose_name='Сентябрь', max_digits=10, decimal_places=2, null=True, blank=True)
    october = models.DecimalField(verbose_name='Октябрь', max_digits=10, decimal_places=2, null=True, blank=True)
    november = models.DecimalField(verbose_name='Ноябрь', max_digits=10, decimal_places=2, null=True, blank=True)
    december = models.DecimalField(verbose_name='Декабрь', max_digits=10, decimal_places=2, null=True, blank=True)
    year = models.IntegerField(verbose_name='Год', default=datetime.datetime.now().year)

    class Meta:
        verbose_name_plural = 'Отчёты по расходу'
        verbose_name = 'Отчёт по расходу'

    def save(self, *args, **kwargs):
        self.total_company = calculate_total_company(self)
        super(OutcomeReport, self).save(*args, **kwargs)
