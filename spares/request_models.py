"""Заявки на проведение складских операций и история решений."""

from django.conf import settings
from django.db import models


class StockRequest(models.Model):
    """Хранит снимок исходного ввода, автора и результат рассмотрения."""

    class Kind(models.TextChoices):
        """Операции, которые можно передать на согласование."""

        RECEIPT = 'receipt', 'Приход'
        RECEIPT_INVOICE = 'receipt_invoice', 'Накладная прихода'
        WRITEOFF = 'writeoff', 'Списание'
        TRANSFER = 'transfer', 'Перемещение'

    class Status(models.TextChoices):
        """Состояния заявки до решения и после него."""

        PENDING = 'pending', 'На согласовании'
        APPLIED = 'applied', 'Проведена'
        REJECTED = 'rejected', 'Отклонена'

    kind = models.CharField(max_length=20, choices=Kind.choices, verbose_name='Вид операции', editable=False)
    title = models.CharField(max_length=255, verbose_name='Краткое описание', editable=False)
    payload = models.JSONField(verbose_name='Исходные данные', editable=False)
    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.PENDING, db_index=True, verbose_name='Статус',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name='Автор', editable=False,
    )
    created_by_name = models.CharField(max_length=150, verbose_name='Имя автора при подаче', editable=False)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Время подачи')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+',
        verbose_name='Согласовавший сотрудник',
    )
    reviewed_by_name = models.CharField(max_length=150, blank=True, verbose_name='Имя сотрудника при рассмотрении')
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='Время решения')
    review_note = models.CharField(max_length=500, blank=True, verbose_name='Причина отклонения')
    result = models.JSONField(default=dict, blank=True, verbose_name='Ссылка на проведённый документ')
    applied_automatically = models.BooleanField(default=False, verbose_name='Проведена сразу при подаче')

    class Meta:
        """Оставляет редактирование заявок только штатным операциям согласования."""

        default_permissions = ('add', 'view')
        permissions = [
            ('approve_stockrequest', 'Может согласовывать складские заявки'),
            ('manage_warehouse_users', 'Может управлять пользователями склада'),
        ]
        ordering = ('-created_at', '-pk')
        verbose_name = 'Складская заявка'
        verbose_name_plural = 'Складские заявки'

    def __str__(self):
        """Возвращает подпись заявки с номером и кратким описанием."""
        return f'Заявка № {self.pk} · {self.title}'
