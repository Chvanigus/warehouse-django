"""Заголовок многострочной накладной поставщика."""

from unicodedata import normalize

from django.conf import settings
from django.db import models
from django.db.models import Q


class ReceiptInvoice(models.Model):
    """Проведённая накладная, каждая позиция которой записана как приход."""

    number = models.CharField(max_length=255, verbose_name='Номер накладной')
    number_key = models.CharField(max_length=255, editable=False)
    date = models.DateField(verbose_name='Дата накладной')
    company = models.ForeignKey('spares.Company', on_delete=models.PROTECT, verbose_name='Фирма')
    contractor = models.ForeignKey('spares.Contractors', on_delete=models.PROTECT, verbose_name='Поставщик')
    warehouse = models.ForeignKey('spares.Warehouses', on_delete=models.PROTECT, verbose_name='Склад')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Проведена')
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name='+', verbose_name='Провёл',
    )
    posted_by_name = models.CharField(max_length=150, verbose_name='Кто провёл')
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name='Отменена')
    cancelled_by_name = models.CharField(max_length=150, blank=True, verbose_name='Кто отменил')
    cancellation_reason = models.CharField(max_length=500, blank=True, verbose_name='Причина отмены')

    class Meta:
        """Задать порядок, права и уникальность номера действующей накладной в рамках фирмы и поставщика."""

        default_permissions = ()
        ordering = ('-date', '-pk')
        verbose_name = 'Многострочная накладная'
        verbose_name_plural = 'Многострочные накладные'
        constraints = [
            models.UniqueConstraint(
                fields=('company', 'contractor', 'number_key'), condition=Q(cancelled_at__isnull=True),
                name='unique_active_supplier_invoice',
            ),
        ]

    @staticmethod
    def normalize_number(number):
        """Нормализовать Юникод, пробелы и регистр номера для проверки дубликатов."""
        return ' '.join(normalize('NFKC', number).split()).casefold()

    def __str__(self):
        """Вернуть номер накладной для отображения в журналах."""
        return self.number
