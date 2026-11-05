"""Модели приложения Spares."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, router, transaction

from spares.mixins import NameMixin, CompanyMixin, SpareMixin, MeasureMixin, WarehouseMixin, \
    MachinesWorkersTrailersMixin, PriceMixin


class MeasureMeasurement(NameMixin):
    """Модель мер измерений."""
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Меры измерений'
        verbose_name = 'Мера измерения'


class Spares(NameMixin):
    """Модель запчастей."""
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Запчасти'
        verbose_name = 'Запчасть'


class Warehouses(NameMixin):
    """Модель складов."""
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Склады'
        verbose_name = 'Склад'


class Company(NameMixin):
    """Модель фирмы."""
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Фирмы'
        verbose_name = 'Фирма'


class Contractors(NameMixin):
    """Модель контрагентов."""
    contact = models.CharField(max_length=255, verbose_name='Номер телефона')
    contact_name = models.CharField(max_length=255, verbose_name='Имя контакта')

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Контрагенты'
        verbose_name = 'Контрагент'


class Workers(NameMixin):
    """Модель работников."""
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Работники'
        verbose_name = 'Работник'


class Machines(NameMixin):
    """Модель техники."""

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Техника'
        verbose_name = 'Техника'


class Trailers(NameMixin):
    """Модель прицепов."""
    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = 'Прицепное'
        verbose_name = 'Прицепное'


class MachineWorker(MachinesWorkersTrailersMixin):
    """Модель отношения техника-работник-прицеп."""
    def __str__(self):
        components = [getattr(component, 'name', '') for component in [self.worker, self.machine, self.trailer]]
        valid_components = [component for component in components if component]
        return ' | '.join(valid_components)

    class Meta:
        verbose_name_plural = 'Водители-транспорт-прицепы'
        verbose_name = 'Водитель-транспорт-прицеп'


class StockOperation(CompanyMixin, SpareMixin, MeasureMixin, WarehouseMixin, PriceMixin):
    class Meta:
        abstract = True

    def _stored(self, using, *, lock=False):
        if self.pk is None:
            return None
        entries = type(self).objects.using(using)
        if lock:
            entries = entries.select_for_update()
        return entries.filter(pk=self.pk).first()

    def _changes(self, previous):
        if previous is None:
            return [(self, self.quantity)]
        if Stock.key_for(previous) == Stock.key_for(self):
            return [(self, self.quantity - previous.quantity)]
        return [(previous, -previous.quantity), (self, self.quantity)]

    def _calculate_total(self, price, quantity):
        total = (price * quantity).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        try:
            return self._meta.get_field(self.total_field).clean(total, self)
        except ValidationError as error:
            raise ValidationError('Итоговая сумма превышает допустимое значение.') from error

    def clean(self):
        super().clean()
        if None in (self.spare_id, self.warehouse_id, self.company_id, self.price, self.quantity):
            return
        try:
            price = self._meta.get_field('price').clean(self.price, self)
            quantity = self._meta.get_field('quantity').clean(self.quantity, self)
        except ValidationError:
            return  # The field validation already reports these errors.
        self._calculate_total(price, quantity)
        using = router.db_for_write(type(self), instance=self)
        for operation, delta in self._changes(self._stored(using)):
            Stock.adjust(operation, delta, using, persist=False)

    def save(self, *, force_insert=False, force_update=False, using=None, update_fields=None):
        if update_fields is not None:
            update_fields = set(update_fields)
            if not update_fields:
                return

        using = using or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            previous = self._stored(using, lock=True)
            values = {}
            for field in ('price', 'quantity'):
                if previous is None or update_fields is None or field in update_fields:
                    values[field] = self._meta.get_field(field).clean(getattr(self, field), self)
                else:
                    values[field] = getattr(previous, field)
            setattr(self, self.total_field, self._calculate_total(**values))
            if update_fields is not None:
                update_fields.add(self.total_field)
            super().save(
                force_insert=force_insert, force_update=force_update, using=using, update_fields=update_fields,
            )

            current = self._stored(using)
            for operation, delta in current._changes(previous):
                Stock.adjust(operation, delta, using, persist=True)
            if (
                isinstance(self, Receipt) and previous
                and previous.warehouse_id != current.warehouse_id
                and previous.spare_id == current.spare_id
            ):
                Movement.objects.using(using).create(
                    spare_id=current.spare_id,
                    from_warehouse_id=previous.warehouse_id,
                    to_warehouse_id=current.warehouse_id,
                )


class Receipt(StockOperation):
    """Модель таблицы прихода."""
    stock_field = 'input_quantity'
    total_field = 'amount'
    date = models.DateField(verbose_name='Дата', default=date.today)
    quantity = models.DecimalField(
        verbose_name='Количество', max_digits=15, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    amount = models.DecimalField(verbose_name='Итого', max_digits=15, decimal_places=2)
    invoice_number = models.CharField(max_length=255, verbose_name='Номер накладной')
    contractor = models.ForeignKey(Contractors, on_delete=models.PROTECT, verbose_name='Контрагент')

    class Meta:
        verbose_name_plural = 'Приход'
        verbose_name = 'Приход'

    def __str__(self):
        return f"Приход: {self.spare} | {self.amount}"


class Stock(CompanyMixin, SpareMixin, MeasureMixin, WarehouseMixin, PriceMixin):
    """Модель таблицы остатков."""
    key_fields = ('spare_id', 'warehouse_id', 'company_id', 'measure_id', 'price')
    input_quantity = models.DecimalField(default=0, verbose_name='Приход', max_digits=15, decimal_places=2)
    output_quantity = models.DecimalField(default=0, verbose_name='Расход', max_digits=15, decimal_places=2)
    actual_balance = models.DecimalField(default=0, verbose_name='Фактический остаток', max_digits=15, decimal_places=2)
    plan = models.CharField(max_length=255, blank=True, verbose_name='План')
    discrepancy = models.BooleanField(default=False, verbose_name='Расхождение с инвентаризацией')
    inventory = models.PositiveIntegerField(blank=True, null=True, verbose_name='По инвентаризации')

    @classmethod
    def key_for(cls, item):
        key = {field: getattr(item, field) for field in cls.key_fields}
        key['price'] = item._meta.get_field('price').to_python(item.price)
        return key

    @classmethod
    def matching(cls, item, using=None):
        return cls.objects.using(using).filter(**cls.key_for(item))

    @classmethod
    def adjust(cls, operation, delta, using, *, persist, missing_ok=False):
        if not delta:
            return
        matches = cls.matching(operation, using)
        if persist:
            matches = matches.select_for_update()
        try:
            stock = matches.get()
        except cls.MultipleObjectsReturned as error:
            raise ValidationError('Найдены дублирующиеся остатки. Сверьте записи перед операцией.') from error
        except cls.DoesNotExist:
            if missing_ok:
                return
            if operation.stock_field != 'input_quantity' or delta < 0:
                raise ValidationError('Для выбранной позиции нет записи об остатке.')
            stock = cls(**cls.key_for(operation))

        field = operation.stock_field
        balance_delta = delta if field == 'input_quantity' else -delta
        new_balance = stock.actual_balance + balance_delta
        if balance_delta < 0 and new_balance < 0:
            raise ValidationError('Количество превышает доступный остаток.')

        try:
            new_quantity = cls._meta.get_field(field).clean(getattr(stock, field) + delta, stock)
            stock.actual_balance = cls._meta.get_field('actual_balance').clean(new_balance, stock)
        except ValidationError as error:
            raise ValidationError('Остаток превышает допустимое значение.') from error
        if persist:
            setattr(stock, field, new_quantity)
            if stock.pk is None:
                stock.save(using=using)
            else:
                stock.save(using=using, update_fields={field, 'actual_balance'})

    def _validate_key(self, previous, using, update_fields=None):
        if previous is None:
            if self.matching(self, using).exists():
                raise ValidationError('Остаток с такими запчастью, складом, фирмой, мерой и ценой уже есть.')
            return
        previous_key = self.key_for(previous)
        for field, value in self.key_for(self).items():
            if update_fields is None or field in update_fields or field.removesuffix('_id') in update_fields:
                if value != previous_key[field]:
                    raise ValidationError('Изменение реквизитов существующего остатка недоступно.')

    def clean(self):
        super().clean()
        using = router.db_for_write(type(self), instance=self)
        previous = Stock.objects.using(using).filter(pk=self.pk).first()
        self._validate_key(previous, using)

    def save(self, *, force_insert=False, force_update=False, using=None, update_fields=None):
        if update_fields is not None:
            update_fields = set(update_fields)
            if not update_fields:
                return
        using = using or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            previous = Stock.objects.using(using).select_for_update().filter(pk=self.pk).first()
            self._validate_key(previous, using, update_fields)
            if update_fields is None or previous is None:
                balance, inventory = self.actual_balance, self.inventory
            else:
                balance = self.actual_balance if 'actual_balance' in update_fields else previous.actual_balance
                inventory = self.inventory if 'inventory' in update_fields else previous.inventory
                update_fields.add('discrepancy')
            self.discrepancy = inventory is not None and Decimal(inventory) != Decimal(balance)
            super().save(
                force_insert=force_insert, force_update=force_update, using=using, update_fields=update_fields,
            )

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


class WriteOff(MachinesWorkersTrailersMixin, StockOperation):
    """Модель таблицы списания."""
    date = models.DateField(verbose_name='Дата списания')
    stock_field = 'output_quantity'
    total_field = 'total_amount'
    quantity = models.DecimalField(
        verbose_name='Списываемое количество', default=0, max_digits=15, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    total_amount = models.DecimalField(verbose_name='Итоговая сумма', max_digits=15, decimal_places=2)

    class Meta:
        verbose_name_plural = 'Списания'
        verbose_name = 'Списание'

    def __str__(self):
        return f'Списание запчасти: {self.spare}'


class Movement(SpareMixin):
    """Модель перемещений."""
    from_warehouse = models.ForeignKey(
        'spares.Warehouses',
        on_delete=models.PROTECT,
        related_name='movements_from',
        verbose_name='Откуда'
    )
    to_warehouse = models.ForeignKey(
        'spares.Warehouses',
        on_delete=models.PROTECT,
        related_name='movements_to',
        verbose_name='Куда'
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='Время перемещения')

    def __str__(self):
        return f"Из {self.from_warehouse} в {self.to_warehouse} | {self.timestamp}"

    class Meta:
        verbose_name_plural = 'Перемещения'
        verbose_name = 'Перемещение'
