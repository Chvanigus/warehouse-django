"""Модели приложения Spares."""
from django.db import models
from datetime import date


class MeasureMeasurement(models.Model):
    measure_name = models.CharField(max_length=255, verbose_name='Мера')

    def __str__(self):
        return self.measure_name

    class Meta:
        verbose_name_plural = 'Меры измерений'
        verbose_name = 'Мера измерения'


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
    contact = models.CharField(max_length=255, verbose_name='Номер телефона')
    name = models.CharField(max_length=255, verbose_name='Имя контакта')

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
    """Модель техники."""
    machine_name = models.CharField(max_length=255, verbose_name='Техника')

    def __str__(self):
        return self.machine_name

    class Meta:
        verbose_name_plural = 'Техника'
        verbose_name = 'Техника'


class Trailers(models.Model):
    """Модель прицепов."""
    trailer_name = models.CharField(max_length=255, verbose_name='Прицепное оборудование')

    def __str__(self):
        return self.trailer_name

    class Meta:
        verbose_name_plural = 'Прицепное'
        verbose_name = 'Прицепное'


class MachineWorker(models.Model):
    """Модель отношения техника-работник-прицеп."""
    machine = models.ForeignKey(Machines, on_delete=models.CASCADE, verbose_name='Техника', null=True, blank=True)
    worker = models.ForeignKey(Workers, on_delete=models.DO_NOTHING, verbose_name='Работник')
    trailer = models.ForeignKey(Trailers, on_delete=models.DO_NOTHING, verbose_name='Прицепное', null=True, blank=True)

    def __str__(self):
        if self.worker and self.trailer and self.machine:
            return f"{self.worker.worker_name} | {self.machine.machine_name}  | {self.trailer.trailer_name}"
        elif self.worker and self.trailer:
            return f"{self.worker.worker_name} | {self.trailer.trailer_name}"
        else:
            return f"{self.worker.worker_name} | {self.machine.machine_name}"

    class Meta:
        verbose_name_plural = 'Водители-транспорт-прицепы'
        verbose_name = 'Водитель-транспорт-прицеп'


class Receipt(models.Model):
    """Модель таблицы прихода."""
    spare = models.ForeignKey(Spares, on_delete=models.CASCADE, verbose_name='Наименование')
    measure = models.ForeignKey(
        MeasureMeasurement,
        on_delete=models.DO_NOTHING,
        verbose_name='Мера',
        null=True,
        blank=True
    )
    company = models.ForeignKey(Company, on_delete=models.CASCADE, verbose_name='Фирма')
    date = models.DateField(verbose_name='Дата', default=date.today)
    warehouse = models.ForeignKey(Warehouses, on_delete=models.CASCADE, verbose_name='Склад')
    quantity = models.DecimalField(verbose_name='Количество', max_digits=15, decimal_places=2)
    price = models.DecimalField(verbose_name='Цена', max_digits=15, decimal_places=2)
    amount = models.DecimalField(verbose_name='Итого', max_digits=15, decimal_places=2)
    invoice_number = models.CharField(max_length=255, verbose_name='Номер накладной')
    contractor = models.ForeignKey(Contractors, on_delete=models.CASCADE, verbose_name='Контрагент')

    def save(self, *args, **kwargs):
        self.amount = self.price * self.quantity

        stock, created = Stock.objects.get_or_create(
            spare=self.spare,
            warehouse=self.warehouse,
            price=self.price,
            measure=self.measure,
            company=self.company
        )

        if created:
            stock.input_quantity = self.quantity
        else:
            stock.input_quantity += self.quantity

        stock.save()
        super(Receipt, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural = 'Приход'
        verbose_name = 'Приход'


class Stock(models.Model):
    """Модель таблицы остатков."""
    spare = models.ForeignKey(Spares, on_delete=models.CASCADE, verbose_name='Наименование')
    measure = models.ForeignKey(
        MeasureMeasurement,
        on_delete=models.DO_NOTHING,
        verbose_name='Мера',
        null=True,
        blank=True
    )
    company = models.ForeignKey(Company, on_delete=models.CASCADE, verbose_name='Фирма')
    warehouse = models.ForeignKey(Warehouses, on_delete=models.CASCADE, verbose_name='Склад')
    input_quantity = models.DecimalField(default=0, verbose_name='Приход', max_digits=15, decimal_places=2)
    output_quantity = models.DecimalField(default=0, verbose_name='Расход', max_digits=15, decimal_places=2)
    actual_balance = models.DecimalField(default=0, verbose_name='Фактический остаток', max_digits=15, decimal_places=2)
    price = models.DecimalField(max_digits=20, decimal_places=2, verbose_name='Цена')
    plan = models.CharField(max_length=255, blank=True, verbose_name='План')
    discrepancy = models.BooleanField(default=False, verbose_name='Расхождение с инвентаризацией')
    inventory = models.PositiveIntegerField(blank=True, null=True, verbose_name='По инвентаризации')

    def save(self, *args, **kwargs):
        self.actual_balance = self.input_quantity - self.output_quantity
        self.discrepancy = True if self.inventory == self.inventory else False
        super(Stock, self).save(*args, **kwargs)

    def __str__(self):
        if self.measure:
            measure = f'({self.measure})'
        else:
            measure = ''
        return f"{self.spare} |" \
               f" Количество: {self.actual_balance} {measure} |" \
               f" Склад: {self.warehouse} |" \
               f" Цена: {self.price} |" \
               f" Фирма: {self.company}"

    class Meta:
        verbose_name_plural = 'Остатки'
        verbose_name = 'Остаток'


class WriteOff(models.Model):
    """Модель таблицы списания."""
    spare = models.ForeignKey(Spares, on_delete=models.CASCADE, verbose_name='Наименование')
    measure = models.ForeignKey(
        MeasureMeasurement,
        on_delete=models.DO_NOTHING,
        verbose_name='Мера',
        null=True,
        blank=True
    )
    company = models.ForeignKey(Company, on_delete=models.DO_NOTHING, verbose_name='Фирма')
    date = models.DateField(verbose_name='Дата списания')
    machine = models.ForeignKey(Machines, on_delete=models.DO_NOTHING, verbose_name='Техника', null=True, blank=True)
    trailer = models.ForeignKey(Trailers, on_delete=models.DO_NOTHING, verbose_name='Прицепное', null=True, blank=True)
    worker = models.ForeignKey(Workers, on_delete=models.CASCADE, verbose_name='Механизатор')
    warehouse = models.ForeignKey(Warehouses, on_delete=models.DO_NOTHING, verbose_name='Склад')
    quantity = models.DecimalField(verbose_name='Списываемое количество', default=0, max_digits=15, decimal_places=2)
    price = models.DecimalField(verbose_name='Цена', default=0, max_digits=15, decimal_places=2)
    total_amount = models.DecimalField(verbose_name='Итоговая сумма', max_digits=15, decimal_places=2)

    def save(self, *args, **kwargs):
        self.total_amount = self.price * self.quantity
        stock = Stock.objects.get(
            spare=self.spare,
            warehouse=self.warehouse,
            price=self.price,
            company=self.company
        )

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
