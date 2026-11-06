"""Инвентаризационные ведомости и строки пересчётов."""

from django.conf import settings
from django.db import models


class InventorySheet(models.Model):
    """Ведомость одного склада с автором, результатом проверки и контролёром."""

    class Status(models.TextChoices):
        """Состояния ведомости от подачи до подтверждения или отклонения."""

        PENDING = 'pending', 'На проверке'
        APPROVED = 'approved', 'Подтверждена'
        REJECTED = 'rejected', 'Отклонена'

    warehouse = models.ForeignKey('spares.Warehouses', on_delete=models.PROTECT, verbose_name='Склад')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', verbose_name='Автор',
    )
    created_by_name = models.CharField(max_length=150, verbose_name='Автор при составлении')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Время составления')
    note = models.CharField(max_length=500, blank=True, verbose_name='Примечание')
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING, verbose_name='Статус')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', verbose_name='Контролёр',
    )
    reviewed_by_name = models.CharField(max_length=150, blank=True, verbose_name='Имя контролёра при проверке')
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='Время проверки')
    review_note = models.CharField(max_length=500, blank=True, verbose_name='Комментарий контролёра')

    class Meta:
        """Настроить права и порядок отображения ведомостей."""

        default_permissions = ('add', 'view')
        permissions = [('approve_inventorysheet', 'Может проверять инвентаризационные ведомости')]
        ordering = ('-created_at', '-pk')
        verbose_name = 'Инвентаризационная ведомость'
        verbose_name_plural = 'Инвентаризационные ведомости'

    def __str__(self):
        """Вернуть подпись ведомости с её номером."""
        return f'Ведомость № {self.pk}'


class InventorySheetLine(models.Model):
    """Связь ведомости с пересчётом, версией остатка и возможной корректировкой."""

    sheet = models.ForeignKey(InventorySheet, on_delete=models.CASCADE, related_name='lines')
    count = models.OneToOneField('spares.InventoryCount', on_delete=models.PROTECT, related_name='sheet_line')
    stock_revision = models.JSONField(editable=False)
    adjustment = models.OneToOneField(
        'spares.StockAdjustment', null=True, on_delete=models.PROTECT, related_name='sheet_line',
    )

    class Meta:
        """Упорядочить строки ведомости и оставить права на уровне документа."""

        default_permissions = ()
        ordering = ('pk',)
