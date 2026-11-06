"""Снимки инвентаризационных пересчётов."""

from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Создаёт историю пересчётов и поле учётного количества на момент проверки."""
    dependencies = [('spares', '0036_posting_and_cancellation')]

    operations = [
        migrations.AddField(
            model_name='stock', name='inventory_book_balance',
            field=models.DecimalField(
                blank=True, decimal_places=2, editable=False, max_digits=15, null=True,
                verbose_name='Учётный остаток на момент пересчёта',
            ),
        ),
        migrations.CreateModel(
            name='InventoryCount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stock_label', models.TextField(verbose_name='Позиция на момент пересчёта')),
                ('actor_name', models.CharField(max_length=150, verbose_name='Имя пользователя на момент пересчёта')),
                ('book_quantity', models.DecimalField(max_digits=15, decimal_places=2, verbose_name='По учёту')),
                ('counted_quantity', models.DecimalField(
                    max_digits=15, decimal_places=2, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))],
                    verbose_name='Фактически',
                )),
                ('note', models.CharField(max_length=500, blank=True, verbose_name='Примечание')),
                ('counted_at', models.DateTimeField(auto_now_add=True, verbose_name='Время пересчёта')),
                ('actor', models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL,
                    verbose_name='Кто пересчитал',
                )),
                ('stock', models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='counts',
                    to='spares.stock', verbose_name='Остаток',
                )),
            ],
            options={
                'default_permissions': ('add', 'view'),
                'ordering': ('-counted_at', '-pk'),
                'verbose_name': 'Пересчёт остатков',
                'verbose_name_plural': 'Пересчёты остатков',
            },
        ),
    ]
