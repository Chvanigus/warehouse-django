"""Дата проведения и отметки отмены складских документов."""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import spares.validators


class Migration(migrations.Migration):
    """Добавляет сведения об отмене и валидаторы дат прихода и расхода."""
    dependencies = [
        ('spares', '0035_stock_adjustment'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name=model_name, name=name, field=field)
        for model_name in ('receipt', 'writeoff')
        for name, field in (
            ('cancelled_at', models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Дата отмены')),
            ('cancelled_by', models.ForeignKey(
                blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='cancelled_%(class)ss', to=settings.AUTH_USER_MODEL, verbose_name='Кто отменил',
            )),
            ('cancelled_by_name', models.CharField(
                blank=True, editable=False, max_length=150, verbose_name='Автор отмены',
            )),
            ('cancellation_reason', models.CharField(
                blank=True, editable=False, max_length=500, verbose_name='Причина отмены',
            )),
        )
    ] + [
        migrations.AlterField(
            model_name='receipt', name='date', field=models.DateField(
                default=django.utils.timezone.localdate, validators=[spares.validators.validate_posting_date],
                verbose_name='Дата',
            ),
        ),
        migrations.AlterField(
            model_name='writeoff', name='date', field=models.DateField(
                validators=[spares.validators.validate_posting_date], verbose_name='Дата списания',
            ),
        ),
    ]
