import django.core.validators
import django.db.models.deletion
from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('spares', '0037_dated_inventory')]

    operations = [
        migrations.AddField(
            model_name='spares',
            name='sku',
            field=models.CharField(blank=True, max_length=64, null=True, unique=True, verbose_name='Артикул'),
        ),
        migrations.CreateModel(
            name='StockMinimum',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('minimum', models.DecimalField(
                    max_digits=15, decimal_places=2, verbose_name='Минимальный остаток',
                    validators=[django.core.validators.MinValueValidator(Decimal('0.01'))],
                )),
                ('company', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, to='spares.company', verbose_name='Фирма',
                )),
                ('measure', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, to='spares.measuremeasurement',
                    blank=True, null=True, verbose_name='Единица измерения',
                    help_text='Если оставить пустым, в расчёт войдут только остатки без единицы измерения.',
                )),
                ('spare', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, to='spares.spares', verbose_name='Запчасть',
                )),
                ('warehouse', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, to='spares.warehouses', verbose_name='Склад',
                )),
            ],
            options={
                'verbose_name': 'Минимальный остаток',
                'verbose_name_plural': 'Минимальные остатки',
                'constraints': [
                    models.UniqueConstraint(
                        fields=('spare', 'company', 'warehouse', 'measure'),
                        condition=models.Q(measure__isnull=False), name='stock_minimum_with_measure',
                        violation_error_message='Минимум для этой позиции уже задан.',
                    ),
                    models.UniqueConstraint(
                        fields=('spare', 'company', 'warehouse'),
                        condition=models.Q(measure__isnull=True), name='stock_minimum_without_measure',
                        violation_error_message='Минимум для этой позиции уже задан.',
                    ),
                    models.CheckConstraint(condition=models.Q(minimum__gt=0), name='stock_minimum_positive'),
                ],
            },
        ),
    ]
