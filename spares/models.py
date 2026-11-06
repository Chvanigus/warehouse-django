"""Справочники, складские документы, остатки и история их изменений."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, router, transaction
from django.utils import timezone

from spares.mixins import (
    CompanyMixin,
    MachinesWorkersTrailersMixin,
    MeasureMixin,
    NameMixin,
    PriceMixin,
    SpareMixin,
    WarehouseMixin,
)
from spares.validators import require_operation_actor, validate_posting_date


class MeasureMeasurement(NameMixin):
    """Справочная единица, в которой учитывается количество запчасти."""

    def __str__(self):
        """Вернуть название единицы для форм и журналов."""
        return self.name

    class Meta:
        """Задать отображаемые названия единиц измерения."""

        verbose_name_plural = 'Меры измерений'
        verbose_name = 'Мера измерения'


class Spares(NameMixin):
    """Справочная запчасть с необязательным уникальным артикулом."""

    sku = models.CharField(max_length=64, blank=True, null=True, unique=True, verbose_name='Артикул')

    def __str__(self):
        """Добавить артикул к названию, если он задан."""
        return f'{self.name} · {self.sku}' if self.sku else self.name

    @staticmethod
    def normalize_sku(value):
        """Привести артикул к верхнему регистру и заменить пустое значение на None."""
        return (value or '').strip().upper() or None

    def clean_fields(self, exclude=None):
        """Нормализовать артикул перед модельной проверкой полей и уникальности."""
        self.sku = self.normalize_sku(self.sku)
        super().clean_fields(exclude=exclude)

    def save(self, *args, **kwargs):
        """Проверить нормализованный артикул при любом сохранении запчасти."""
        self.sku = self._meta.get_field('sku').clean(self.normalize_sku(self.sku), self)
        super().save(*args, **kwargs)

    class Meta:
        """Задать отображаемые названия запчастей."""

        verbose_name_plural = 'Запчасти'
        verbose_name = 'Запчасть'


class Warehouses(NameMixin):
    """Склад, на котором хранятся остатки и оформляются движения."""

    def __str__(self):
        """Вернуть название склада для форм и журналов."""
        return self.name

    class Meta:
        """Задать отображаемые названия складов."""

        verbose_name_plural = 'Склады'
        verbose_name = 'Склад'


class Company(NameMixin):
    """Фирма, в разрезе которой ведётся складской учёт."""

    def __str__(self):
        """Вернуть название фирмы для форм и журналов."""
        return self.name

    class Meta:
        """Задать отображаемые названия фирм."""

        verbose_name_plural = 'Фирмы'
        verbose_name = 'Фирма'


class Contractors(NameMixin):
    """Контрагент с контактным лицом и телефоном."""

    contact = models.CharField(max_length=255, verbose_name='Номер телефона')
    contact_name = models.CharField(max_length=255, verbose_name='Имя контакта')

    def __str__(self):
        """Вернуть название контрагента для документов."""
        return self.name

    class Meta:
        """Задать отображаемые названия контрагентов."""

        verbose_name_plural = 'Контрагенты'
        verbose_name = 'Контрагент'


class Workers(NameMixin):
    """Работник, на которого можно оформить складской расход."""

    def __str__(self):
        """Вернуть имя работника для форм и журналов."""
        return self.name

    class Meta:
        """Задать отображаемые названия работников."""

        verbose_name_plural = 'Работники'
        verbose_name = 'Работник'


class Machines(NameMixin):
    """Справочная единица техники, на которую можно отнести расход."""

    def __str__(self):
        """Вернуть название техники для документов."""
        return self.name

    class Meta:
        """Задать отображаемые названия техники."""

        verbose_name_plural = 'Техника'
        verbose_name = 'Техника'


class Trailers(NameMixin):
    """Справочный прицеп для указания в назначении расхода."""

    def __str__(self):
        """Вернуть название прицепа для документов."""
        return self.name

    class Meta:
        """Задать отображаемые названия прицепного оборудования."""

        verbose_name_plural = 'Прицепное'
        verbose_name = 'Прицепное'


class MachineWorker(MachinesWorkersTrailersMixin):
    """Назначение работника с необязательной техникой и прицепом."""

    def __str__(self):
        """Собрать названия заполненных участников назначения в порядке следования полей."""
        names = (getattr(component, 'name', '') for component in (self.worker, self.machine, self.trailer))
        return ' | '.join(filter(None, names))

    class Meta:
        """Задать отображаемые названия назначений работников и техники."""

        verbose_name_plural = 'Водители-транспорт-прицепы'
        verbose_name = 'Водитель-транспорт-прицеп'


class StockOperation(CompanyMixin, SpareMixin, MeasureMixin, WarehouseMixin, PriceMixin):
    """Общая модель проведения и отмены прихода или расхода."""

    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name='Дата отмены')
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, editable=False, on_delete=models.SET_NULL,
        related_name='cancelled_%(class)ss', verbose_name='Кто отменил',
    )
    cancelled_by_name = models.CharField(max_length=150, blank=True, editable=False, verbose_name='Автор отмены')
    cancellation_reason = models.CharField(max_length=500, blank=True, editable=False, verbose_name='Причина отмены')

    class Meta:
        """Определить общие поля документов без отдельной таблицы."""

        abstract = True

    def _stored(self, using, *, lock=False):
        """Прочитать сохранённую версию документа, при необходимости с блокировкой строки."""
        if self.pk is None:
            return None
        entries = type(self).objects.using(using)
        if lock:
            entries = entries.select_for_update()
        return entries.filter(pk=self.pk).first()

    def _changes(self, previous):
        """Рассчитать изменения количества для новой или изменённой позиции документа."""
        if previous is None:
            return [(self, self.quantity)]
        if Stock.key_for(previous) == Stock.key_for(self):
            return [(self, self.quantity - previous.quantity)]
        return [(previous, -previous.quantity), (self, self.quantity)]

    def _calculate_total(self, price, quantity):
        """Умножить цену на количество, округлить до копеек и проверить диапазон суммы."""
        try:
            total = (price * quantity).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            return self._meta.get_field(self.total_field).clean(total, self)
        except (InvalidOperation, ValidationError) as error:
            raise ValidationError('Итоговая сумма превышает допустимое значение.') from error

    def clean(self):
        """Проверить сумму и возможность проведения без записи в остатки."""
        super().clean()
        if None in (self.spare_id, self.warehouse_id, self.company_id, self.price, self.quantity):
            return
        try:
            price = self._meta.get_field('price').clean(self.price, self)
            quantity = self._meta.get_field('quantity').clean(self.quantity, self)
        except ValidationError:
            return  # Ошибки уже зарегистрированы при проверке полей.
        self._calculate_total(price, quantity)
        using = router.db_for_write(type(self), instance=self)
        for operation, delta in self._changes(self._stored(using)):
            Stock.adjust(operation, delta, using, persist=False)

    def _validate_posting(self, previous, using, update_fields):
        """Проверить состояние документа, дату и отсутствие дублирующей накладной."""
        if self.cancelled_at is not None or (previous is not None and previous.cancelled_at is not None):
            raise ValidationError('Отменённый документ нельзя изменить.')
        if previous is None or (
            (update_fields is None or 'date' in update_fields) and self.date != previous.date
        ):
            self.date = self._meta.get_field('date').clean(self.date, self)
        if (
            previous is None and isinstance(self, Receipt) and self.invoice_id is None and self.invoice_number
            and ReceiptInvoice.objects.using(using).filter(
                company_id=self.company_id, contractor_id=self.contractor_id, cancelled_at__isnull=True,
                number_key=ReceiptInvoice.normalize_number(self.invoice_number),
            ).exists()
        ):
            raise ValidationError('Такая накладная уже проведена. Откройте её в журнале накладных.')

    def _total_for_save(self, previous, update_fields):
        """Рассчитать сумму по значениям, которые сохранятся в базе при этой записи."""
        values = {}
        for field in ('price', 'quantity'):
            if previous is None or update_fields is None or field in update_fields:
                values[field] = self._meta.get_field(field).clean(getattr(self, field), self)
            else:
                values[field] = getattr(previous, field)
        return self._calculate_total(**values)

    def save(self, *, force_insert=False, force_update=False, using=None, update_fields=None):
        """Провести документ и изменения остатков в одной транзакции."""
        if update_fields is not None:
            update_fields = set(update_fields)
            if not update_fields:
                return

        using = using or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            previous = self._stored(using, lock=True)
            self._validate_posting(previous, using, update_fields)
            setattr(self, self.total_field, self._total_for_save(previous, update_fields))
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

    def cancel(self, *, actor, reason, allow_invoice=False):
        """Отменить проведённый документ, обратить его движение и сохранить причину и автора."""
        reason = (reason or '').strip()
        if not reason:
            raise ValidationError('Укажите причину отмены.')
        reason = self._meta.get_field('cancellation_reason').clean(reason, self)
        require_operation_actor(actor, 'Для отмены нужен автор.')

        using = router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            previous = self._stored(using, lock=True)
            if previous is None or previous.cancelled_at is not None:
                raise ValidationError('Документ уже отменён или отсутствует.')
            if getattr(previous, 'invoice_id', None) is not None and not allow_invoice:
                raise ValidationError('Откройте накладную, чтобы отменить все её позиции.')
            Stock.adjust(previous, -previous.quantity, using, persist=True)
            cancellation = {
                'cancelled_at': timezone.now(), 'cancelled_by_id': actor.pk,
                'cancelled_by_name': actor.get_username(), 'cancellation_reason': reason,
            }
            type(self).objects.using(using).filter(pk=previous.pk).update(**cancellation)
            for field, value in cancellation.items():
                setattr(self, field, value)


class Receipt(StockOperation):
    """Приход одной запчасти, отдельно или в составе накладной поставщика."""

    stock_field = 'input_quantity'
    total_field = 'amount'
    date = models.DateField(verbose_name='Дата', default=timezone.localdate, validators=[validate_posting_date])
    quantity = models.DecimalField(
        verbose_name='Количество', max_digits=15, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    amount = models.DecimalField(verbose_name='Итого', max_digits=15, decimal_places=2)
    invoice_number = models.CharField(max_length=255, verbose_name='Номер накладной')
    contractor = models.ForeignKey(Contractors, on_delete=models.PROTECT, verbose_name='Контрагент')
    invoice = models.ForeignKey(
        'spares.ReceiptInvoice', null=True, blank=True, on_delete=models.PROTECT,
        related_name='lines', verbose_name='Многострочная накладная',
    )

    class Meta:
        """Задать названия приходов и индекс для журнала проведённых строк."""

        verbose_name_plural = 'Приход'
        verbose_name = 'Приход'
        indexes = [models.Index(
            fields=('-date', '-id'), condition=models.Q(cancelled_at__isnull=True), name='receipt_active_date_idx',
        )]

    def __str__(self):
        """Вернуть название запчасти и сумму для краткой подписи прихода."""
        return f"Приход: {self.spare} | {self.amount}"


class Stock(CompanyMixin, SpareMixin, MeasureMixin, WarehouseMixin, PriceMixin):
    """Остаток по точному сочетанию запчасти, склада, фирмы, единицы и цены."""

    key_fields = ('spare_id', 'warehouse_id', 'company_id', 'measure_id', 'price')
    input_quantity = models.DecimalField(default=0, verbose_name='Приход', max_digits=15, decimal_places=2)
    output_quantity = models.DecimalField(default=0, verbose_name='Расход', max_digits=15, decimal_places=2)
    actual_balance = models.DecimalField(default=0, verbose_name='Фактический остаток', max_digits=15, decimal_places=2)
    plan = models.CharField(max_length=255, blank=True, verbose_name='План')
    discrepancy = models.BooleanField(default=False, verbose_name='Расхождение с инвентаризацией')
    inventory = models.DecimalField(
        blank=True, null=True, max_digits=15, decimal_places=2, verbose_name='По инвентаризации',
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    inventory_book_balance = models.DecimalField(
        blank=True, null=True, max_digits=15, decimal_places=2, editable=False,
        verbose_name='Учётный остаток на момент пересчёта',
    )

    @classmethod
    def key_for(cls, item):
        """Собрать ключ позиции с ценой, приведённой к типу модельного поля."""
        key = {field: getattr(item, field) for field in cls.key_fields}
        key['price'] = item._meta.get_field('price').to_python(item.price)
        return key

    @classmethod
    def matching(cls, item, using=None):
        """Найти записи остатков по точному ключу позиции."""
        return cls.objects.using(using).filter(**cls.key_for(item))

    @classmethod
    def adjust(cls, operation, delta, using, *, persist, missing_ok=False):
        """Проверить изменение остатка и при проведении записать количество и счётчик операции."""
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
        """Запретить дубликат нового остатка и изменение ключа существующей позиции."""
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
        """Проверить, что ключ остатка можно сохранить."""
        super().clean()
        using = router.db_for_write(type(self), instance=self)
        previous = Stock.objects.using(using).filter(pk=self.pk).first()
        self._validate_key(previous, using)

    def save(self, *, force_insert=False, force_update=False, using=None, update_fields=None):
        """Сохранить остаток с учётом заблокированной версии и актуализировать признак расхождения."""
        if update_fields is not None:
            update_fields = set(update_fields)
            if not update_fields:
                return
        using = using or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            previous = Stock.objects.using(using).select_for_update().filter(pk=self.pk).first()
            self._validate_key(previous, using, update_fields)
            if update_fields is None or previous is None:
                balance, inventory, book = self.actual_balance, self.inventory, self.inventory_book_balance
            else:
                balance = self.actual_balance if 'actual_balance' in update_fields else previous.actual_balance
                inventory = self.inventory if 'inventory' in update_fields else previous.inventory
                book = (
                    self.inventory_book_balance
                    if 'inventory_book_balance' in update_fields else previous.inventory_book_balance
                )
                update_fields.add('discrepancy')
            self.discrepancy = inventory is not None and Decimal(inventory) != Decimal(
                balance if book is None else book,
            )
            super().save(
                force_insert=force_insert, force_update=force_update, using=using, update_fields=update_fields,
            )

    def __str__(self):
        """Вернуть подпись с количеством, единицей, складом, ценой и фирмой."""
        if self.measure:
            measure = f'({self.measure})'
        else:
            measure = ''
        return (
            f'{self.spare} | Количество: {self.actual_balance} {measure} |'
            f' Склад: {self.warehouse} | Цена: {self.price} | Фирма: {self.company}'
        )

    class Meta:
        """Задать отображаемые названия остатков."""

        verbose_name_plural = 'Остатки'
        verbose_name = 'Остаток'


class StockAdjustment(models.Model):
    """Аудит ручного изменения остатка с причиной, автором и значениями до и после."""

    stock = models.ForeignKey(
        Stock, on_delete=models.SET_NULL, null=True, related_name='adjustments', verbose_name='Остаток',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='stock_adjustments', verbose_name='Автор',
    )
    stock_label = models.TextField(verbose_name='Позиция на момент корректировки')
    actor_name = models.CharField(max_length=150, verbose_name='Имя пользователя на момент корректировки')
    before = models.DecimalField(max_digits=15, decimal_places=2, verbose_name='До корректировки')
    after = models.DecimalField(max_digits=15, decimal_places=2, verbose_name='После корректировки')
    reason = models.CharField(max_length=500, verbose_name='Причина')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Время корректировки')

    @property
    def delta(self):
        """Вернуть изменение количества с учётом его знака."""
        return self.after - self.before

    class Meta:
        """Оставить право просмотра и показывать свежие корректировки первыми."""

        default_permissions = ('view',)
        ordering = ('-created_at', '-pk')
        verbose_name = 'Ручная корректировка'
        verbose_name_plural = 'Ручные корректировки'


class InventoryCount(models.Model):
    """Снимок учётного и фактического количества на момент пересчёта."""

    stock = models.ForeignKey(
        Stock, on_delete=models.SET_NULL, null=True, related_name='counts', verbose_name='Остаток',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name='Кто пересчитал',
    )
    stock_label = models.TextField(verbose_name='Позиция на момент пересчёта')
    actor_name = models.CharField(max_length=150, verbose_name='Имя пользователя на момент пересчёта')
    book_quantity = models.DecimalField(max_digits=15, decimal_places=2, verbose_name='По учёту')
    counted_quantity = models.DecimalField(
        max_digits=15, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))],
        verbose_name='Фактически',
    )
    note = models.CharField(max_length=500, blank=True, verbose_name='Примечание')
    counted_at = models.DateTimeField(auto_now_add=True, verbose_name='Время пересчёта')

    @property
    def difference(self):
        """Вычислить расхождение между фактическим и учётным количеством."""
        return self.counted_quantity - self.book_quantity

    class Meta:
        """Настроить права на пересчёт и порядок показа истории."""

        default_permissions = ('add', 'view')
        ordering = ('-counted_at', '-pk')
        verbose_name = 'Пересчёт остатков'
        verbose_name_plural = 'Пересчёты остатков'


class WriteOff(MachinesWorkersTrailersMixin, StockOperation):
    """Расход запчасти со склада с указанием работника, техники или прицепа."""

    date = models.DateField(verbose_name='Дата списания', validators=[validate_posting_date])
    stock_field = 'output_quantity'
    total_field = 'total_amount'
    quantity = models.DecimalField(
        verbose_name='Списываемое количество', default=0, max_digits=15, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    total_amount = models.DecimalField(verbose_name='Итоговая сумма', max_digits=15, decimal_places=2)

    class Meta:
        """Задать названия списаний и индекс для журнала проведённых строк."""

        verbose_name_plural = 'Списания'
        verbose_name = 'Списание'
        indexes = [models.Index(
            fields=('-date', '-id'), condition=models.Q(cancelled_at__isnull=True), name='writeoff_active_date_idx',
        )]

    def __str__(self):
        """Вернуть название запчасти для краткой подписи расхода."""
        return f'Списание запчасти: {self.spare}'


class Movement(SpareMixin):
    """Историческая запись о смене склада в документе прихода."""

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
        """Вернуть направление и время исторического перемещения."""
        return f"Из {self.from_warehouse} в {self.to_warehouse} | {self.timestamp}"

    class Meta:
        """Задать отображаемые названия исторических перемещений."""

        verbose_name_plural = 'Перемещения'
        verbose_name = 'Перемещение'


from .invoice_models import ReceiptInvoice
from .inventory_sheet_models import InventorySheet, InventorySheetLine
from .request_models import StockRequest
from .threshold_models import StockMinimum
from .transfer_models import StockTransfer
