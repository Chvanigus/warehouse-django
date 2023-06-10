"""Модели приложения Spares."""
import datetime

from django.db import models
from django.db.models import Sum
from django.db.models.signals import post_save
from django.dispatch import receiver
from datetime import date

class Spares(models.Model):
    """Модель запчастей."""
    spare_name = models.CharField(max_length=255, verbose_name='Наименование')

    def __str__(self):
        return self.spare_name

    class Meta:
        verbose_name_plural = 'Запчасти'
        verbose_name = 'Запчасть'


class Warehouses(models.Model):
    """Модель складов."""
    warehouse_name = models.CharField(max_length=255, verbose_name='Склад')

    def __str__(self):
        return self.warehouse_name

    class Meta:
        verbose_name_plural = 'Склады'
        verbose_name = 'Склад'


class Company(models.Model):
    """Модель фирмы."""
    company_name = models.CharField(max_length=255, verbose_name='Фирма')

    def __str__(self):
        return self.company_name

    class Meta:
        verbose_name_plural = 'Фирмы'
        verbose_name = 'Фирма'


class Contractors(models.Model):
    """Модель контрагентов."""
    contractor_name = models.CharField(max_length=255, verbose_name='Контрагент')

    def __str__(self):
        return self.contractor_name

    class Meta:
        verbose_name_plural = 'Контрагенты'
        verbose_name = 'Контрагент'


class Workers(models.Model):
    """Модель работников."""
    worker_name = models.CharField(max_length=255, verbose_name='Работник')

    def __str__(self):
        return self.worker_name

    class Meta:
        verbose_name_plural = 'Работники'
        verbose_name = 'Работник'


class Machines(models.Model):
    """Модель машин."""
    machine_name = models.CharField(max_length=255, verbose_name='Машина')

    def __str__(self):
        return self.machine_name

    class Meta:
        verbose_name_plural = 'Машины'
        verbose_name = 'Машина'


class MachineWorker(models.Model):
    """Модель отношения машина-работник."""
    machine = models.ForeignKey(Machines, on_delete=models.CASCADE, verbose_name='Машина')
    worker = models.ForeignKey(Workers, on_delete=models.CASCADE, verbose_name='Работник')

    def __str__(self):
        return f"{self.machine.machine_name} - {self.worker.worker_name}"

    class Meta:
        verbose_name_plural = 'Водители-транспорт'
        verbose_name = 'Водитель-транспорт'


class Receipt(models.Model):
    """Модель таблицы прихода."""
    spare = models.ForeignKey(Spares, on_delete=models.CASCADE, verbose_name='Наименование')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, verbose_name='Фирма')
    date = models.DateField(verbose_name='Дата', default=date.today)
    warehouse = models.ForeignKey(Warehouses, on_delete=models.CASCADE, verbose_name='Склад')
    quantity = models.PositiveIntegerField(verbose_name='Количество')
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена')
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Итого')
    invoice_number = models.CharField(max_length=255, verbose_name='Номер накладной')
    contractor = models.ForeignKey(Contractors, on_delete=models.CASCADE, verbose_name='Контрагент')
    year = models.PositiveIntegerField(verbose_name='Год', blank=True, null=True)

    def save(self, *args, **kwargs):
        self.amount = self.price * self.quantity
        super(Receipt, self).save(*args, **kwargs)

        if self.date and not self.year:
            self.year = self.date.year

        stock, created = Stock.objects.get_or_create(spare=self.spare, warehouse=self.warehouse, price=self.price)

        if created:
            stock.input_quantity = self.quantity
        else:
            stock.input_quantity += self.quantity

        stock.save()

    class Meta:
        verbose_name_plural = 'Приход'
        verbose_name = 'Приход'


class Stock(models.Model):
    """Модель таблицы остатков."""
    spare = models.ForeignKey(Spares, on_delete=models.CASCADE, verbose_name='Наименование')
    warehouse = models.ForeignKey(Warehouses, on_delete=models.CASCADE, verbose_name='Склад')
    input_quantity = models.PositiveIntegerField(default=0, verbose_name='Приход')
    output_quantity = models.PositiveIntegerField(default=0, verbose_name='Расход')
    actual_balance = models.PositiveIntegerField(default=0, verbose_name='Фактический остаток')
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена')
    plan = models.CharField(max_length=255, blank=True, verbose_name='План')
    discrepancy = models.BooleanField(default=False, verbose_name='Расхождение с инвентаризацией')
    inventory = models.PositiveIntegerField(blank=True, null=True, verbose_name='По инвентаризации')

    def save(self, *args, **kwargs):
        self.actual_balance = self.input_quantity - self.output_quantity
        self.discrepancy = True if self.inventory == self.inventory else False
        super(Stock, self).save(*args, **kwargs)

    def __str__(self):
        return f"{self.spare} | {self.actual_balance} шт. | Склад: {self.warehouse} | Цена: {self.price}"

    class Meta:
        verbose_name_plural = 'Остатки'
        verbose_name = 'Остаток'


class WriteOff(models.Model):
    """Модель таблицы списания."""
    spare = models.ForeignKey(Spares, on_delete=models.CASCADE, verbose_name='Наименование')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, verbose_name='Фирма')
    date = models.DateField(verbose_name='Дата списания')
    machine = models.ForeignKey(Machines, on_delete=models.CASCADE, verbose_name='Техника')
    worker = models.ForeignKey(Workers, on_delete=models.CASCADE, verbose_name='Механизатор')
    warehouse = models.ForeignKey(Warehouses, on_delete=models.CASCADE, verbose_name='Склад')
    quantity = models.PositiveIntegerField(verbose_name='Списываемое количество', default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Цена', default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Итоговая сумма')
    year = models.PositiveIntegerField(verbose_name='Год', blank=True, null=True)

    def save(self, *args, **kwargs):
        self.total_amount = self.price * self.quantity

        if self.date and not self.year:
            self.year = self.date.year

        stock = Stock.objects.get(spare=self.spare, warehouse=self.warehouse, price=self.price)

        if self.pk is None and stock:
            stock.output_quantity += self.quantity
            stock.save()
            super(WriteOff, self).save(*args, **kwargs)
        elif stock:
            original_writeoff = WriteOff.objects.get(pk=self.pk)

            quantity_diff = self.quantity - original_writeoff.quantity

            if quantity_diff != 0:
                stock.output_quantity += quantity_diff
                stock.save()

        super(WriteOff, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural = 'Списания'
        verbose_name = 'Списание'


class IncomeReport(models.Model):
    """Модель таблицы отчёта по приходу."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, verbose_name='Фирма')
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

    class Meta:
        verbose_name_plural = 'Отчёты по приходу'
        verbose_name = 'Отчёт по приходу'

    @receiver(post_save, sender=Receipt)
    def update_income_report(sender, instance, created, **kwargs):
        if created or instance.date.year != instance.year:
            report, _ = IncomeReport.objects.get_or_create(company=instance.company)

            expenses = Receipt.objects.filter(company=instance.company, year=instance.date.year) \
                .aggregate(total_price=Sum('price'))['total_price']

            if expenses is not None:
                setattr(report, instance.date.strftime('%B').lower(), expenses)
                report.save()

    @property
    def total_company(self):
        total = sum(
            [getattr(self, field.name) or 0 for field in self._meta.fields if field.name not in ['id', 'company']])
        return total
    total_company.fget.short_description = 'Итого'


class OutcomeReport(models.Model):
    """Модель таблицы отчёта по расходу."""
    company = models.ForeignKey(Company, on_delete=models.CASCADE, verbose_name='Фирма')
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

    class Meta:
        verbose_name_plural = 'Отчёты по расходу'
        verbose_name = 'Отчёт по расходу'

    @receiver(post_save, sender=WriteOff)
    def update_outcome_report(sender, instance, created, **kwargs):
        if created or instance.date.year != instance.year:
            report, _ = OutcomeReport.objects.get_or_create(company=instance.company)

            expenses = WriteOff.objects.filter(company=instance.company, year=instance.date.year) \
                .aggregate(total_price=Sum('price'))['total_price']

            if expenses is not None:
                setattr(report, instance.date.strftime('%B').lower(), expenses)
                report.save()

    @property
    def total_company(self):
        total = sum(
            [getattr(self, field.name) or 0 for field in self._meta.fields if field.name not in ['id', 'company']])
        return total
    total_company.fget.short_description = 'Итого'
