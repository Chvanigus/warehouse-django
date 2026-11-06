"""Индексы дат проведённых операций для главной страницы и отчётов."""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Ускоряет выборки по диапазону и выдачу последних действующих документов."""

    dependencies = [
        ('spares', '0042_stockrequest'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddIndex(
            model_name='receipt',
            index=models.Index(
                condition=models.Q(cancelled_at__isnull=True), fields=['-date', '-id'], name='receipt_active_date_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='writeoff',
            index=models.Index(
                condition=models.Q(cancelled_at__isnull=True), fields=['-date', '-id'], name='writeoff_active_date_idx',
            ),
        ),
    ]
