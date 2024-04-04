"""Модели приложения Spares."""
from django.db import models
from datetime import date
from spares.mixins import NameMixin, CompanyMixin, SpareMixin, MeasureMixin, WarehouseMixin, \
    MachinesWorkersTrailersMixin, PriceMixin


class MeasureMeasurement(NameMixin):
    """Модель мер измерений."""
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Меры измерений'
        verbose_name = 'Мера измерения'
        managed = False


class Spares(NameMixin):
    """Модель запчастей."""
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Запчасти'
        verbose_name = 'Запчасть'
        managed = False


class Warehouses(NameMixin):
    """Модель складов."""
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Склады'
        verbose_name = 'Склад'
        managed = False


class Company(NameMixin):
    """Модель фирмы."""
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Фирмы'
        verbose_name = 'Фирма'
        managed = False


class Contractors(NameMixin):
    """Модель контрагентов."""
    contact = models.CharField(max_length=255, verbose_name='Номер телефона')
    contact_name = models.CharField(max_length=255, verbose_name='Имя контакта')

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Контрагенты'
        verbose_name = 'Контрагент'
        managed = False


class Workers(NameMixin):
    """Модель работников."""
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Работники'
        verbose_name = 'Работник'
        managed = False


class Machines(NameMixin):
    """Модель техники."""

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Техника'
        verbose_name = 'Техника'
        managed = False


class Trailers(NameMixin):
    """Модель прицепов."""
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Прицепное'
        verbose_name = 'Прицепное'
        managed = False


class MachineWorker(MachinesWorkersTrailersMixin):
    """Модель отношения техника-работник-прицеп."""
    def __str__(self):
        components = [getattr(component, 'name', '') for component in [self.worker, self.machine, self.trailer]]
        valid_components = [component for component in components if component]
        return ' | '.join(valid_components)

    class Meta:
        verbose_name_plural = 'Водители-транспорт-прицепы'
        verbose_name = 'Водитель-транспорт-прицеп'
        managed = False


class Receipt(CompanyMixin, SpareMixin, MeasureMixin, WarehouseMixin, PriceMixin):
    """Модель таблицы прихода."""
    date = models.DateField(verbose_name='Дата', default=date.today)
    quantity = models.DecimalField(verbose_name='Количество', max_digits=15, decimal_places=2)
    amount = models.DecimalField(verbose_name='Итого', max_digits=15, decimal_places=2)
    invoice_number = models.CharField(max_length=255, verbose_name='Номер накладной')
    contractor = models.ForeignKey(Contractors, on_delete=models.CASCADE, verbose_name='Контрагент')

    def save(self, *args, **kwargs):
        self.amount = self.price * self.quantity

        try:
            warehouse = Receipt.objects.get(pk=self.pk).warehouse
        except Receipt.DoesNotExist:
            warehouse = self.warehouse

        stock, created = Stock.objects.get_or_create(
            spare=self.spare,
            warehouse=warehouse,
            price=self.price,
            measure=self.measure,
            company=self.company
        )

        if created:
            stock.input_quantity = self.quantity
        else:
            stock.input_quantity += self.quantity

        if warehouse != self.warehouse:
            Movement.objects.create(
                spare=self.spare,
                from_warehouse=warehouse,
                to_warehouse=self.warehouse
            )
            stock.warehouse = self.warehouse

        stock.save()
        super(Receipt, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural = 'Приход'
        verbose_name = 'Приход'
        managed = False

    def __str__(self):
        return f"Приход: {self.spare} | {self.amount}"


class Stock(SpareMixin, MeasureMixin, WarehouseMixin, PriceMixin):
    """Модель таблицы остатков."""
    company = models.ForeignKey(
        'spares.Company',
        on_delete=models.CASCADE,
        verbose_name='Фирма',
        default=Company.objects.get(id=5)
    )
    input_quantity = models.DecimalField(default=0, verbose_name='Приход', max_digits=15, decimal_places=2)
    output_quantity = models.DecimalField(default=0, verbose_name='Расход', max_digits=15, decimal_places=2)
    actual_balance = models.DecimalField(default=0, verbose_name='Фактический остаток', max_digits=15, decimal_places=2)
    plan = models.CharField(max_length=255, blank=True, verbose_name='План')
    discrepancy = models.BooleanField(default=False, verbose_name='Расхождение с инвентаризацией')
    inventory = models.PositiveIntegerField(blank=True, null=True, verbose_name='По инвентаризации')

    def save(self, *args, **kwargs):
        if self.input_quantity != 0:
            self.actual_balance = self.input_quantity - self.output_quantity
        elif self.input_quantity == 0 and self.output_quantity != 0:
            self.actual_balance = self.actual_balance - self.output_quantity

        self.discrepancy = True if self.inventory == self.actual_balance else False

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
        managed = False


class WriteOff(MachinesWorkersTrailersMixin, WarehouseMixin, SpareMixin, MeasureMixin, CompanyMixin, PriceMixin):
    """Модель таблицы списания."""
    date = models.DateField(verbose_name='Дата списания')
    quantity = models.DecimalField(verbose_name='Списываемое количество', default=0, max_digits=15, decimal_places=2)
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
        managed = False

    def __str__(self):
        return f'Списание запчасти: {self.spare}'


class Movement(SpareMixin):
    """Модель перемещений."""
    from_warehouse = models.ForeignKey(
        'spares.Warehouses',
        on_delete=models.CASCADE,
        related_name='movements_from',
        verbose_name='Откуда'
    )
    to_warehouse = models.ForeignKey(
        'spares.Warehouses',
        on_delete=models.CASCADE,
        related_name='movements_to',
        verbose_name='Куда'
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='Время перемещения')

    def __str__(self):
        return f"Из {self.from_warehouse} в {self.to_warehouse} | {self.timestamp}"

    class Meta:
        verbose_name_plural = 'Перемещения'
        verbose_name = 'Перемещение'
