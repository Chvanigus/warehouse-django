from decimal import Decimal

import django.core.validators
import django.db.models.deletion
import django.utils.timezone
import spares.validators
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('spares', '0038_part_codes_and_minimums'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StockTransfer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('price', models.DecimalField(
                    decimal_places=2, default=0, max_digits=15,
                    validators=[django.core.validators.MinValueValidator(0)], verbose_name='Цена',
                )),
                ('quantity', models.DecimalField(
                    decimal_places=2, max_digits=15, verbose_name='Количество',
                    validators=[django.core.validators.MinValueValidator(Decimal('0.01'))],
                )),
                ('date', models.DateField(
                    default=django.utils.timezone.localdate, validators=[spares.validators.validate_posting_date],
                    verbose_name='Дата документа',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Время проведения')),
                ('actor_name', models.CharField(max_length=150, verbose_name='Имя пользователя при проведении')),
                ('note', models.CharField(blank=True, max_length=500, verbose_name='Примечание')),
                ('cancelled_at', models.DateTimeField(editable=False, null=True, verbose_name='Время отмены')),
                ('cancelled_by_name', models.CharField(
                    blank=True, editable=False, max_length=150, verbose_name='Автор отмены',
                )),
                ('cancellation_reason', models.CharField(
                    blank=True, editable=False, max_length=500, verbose_name='Причина отмены',
                )),
                ('actor', models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='stock_transfers',
                    to=settings.AUTH_USER_MODEL, verbose_name='Автор',
                )),
                ('cancelled_by', models.ForeignKey(
                    editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='cancelled_stock_transfers', to=settings.AUTH_USER_MODEL, verbose_name='Кто отменил',
                )),
                ('company', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, to='spares.company', verbose_name='Фирма',
                )),
                ('from_warehouse', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name='transfers_out',
                    to='spares.warehouses', verbose_name='Со склада',
                )),
                ('measure', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                    to='spares.measuremeasurement', verbose_name='Мера',
                )),
                ('spare', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, to='spares.spares', verbose_name='Наименование',
                )),
                ('to_warehouse', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name='transfers_in',
                    to='spares.warehouses', verbose_name='На склад',
                )),
            ],
            options={
                'verbose_name': 'Перемещение запчастей',
                'verbose_name_plural': 'Перемещения запчастей',
                'ordering': ('-date', '-pk'),
                'default_permissions': ('add', 'delete', 'view'),
                'constraints': [
                    models.CheckConstraint(condition=models.Q(quantity__gt=0), name='transfer_quantity_positive'),
                    models.CheckConstraint(
                        condition=~models.Q(from_warehouse=models.F('to_warehouse')),
                        name='transfer_warehouses_differ',
                    ),
                ],
            },
        ),
    ]
