"""Многострочные приходные накладные."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Создаёт заголовок накладной и связывает его со строками прихода."""
    dependencies = [
        ('spares', '0039_stock_transfers'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ReceiptInvoice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.CharField(max_length=255, verbose_name='Номер накладной')),
                ('number_key', models.CharField(editable=False, max_length=255)),
                ('date', models.DateField(verbose_name='Дата накладной')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Проведена')),
                ('posted_by_name', models.CharField(max_length=150, verbose_name='Кто провёл')),
                ('cancelled_at', models.DateTimeField(blank=True, null=True, verbose_name='Отменена')),
                ('cancelled_by_name', models.CharField(blank=True, max_length=150, verbose_name='Кто отменил')),
                ('cancellation_reason', models.CharField(blank=True, max_length=500, verbose_name='Причина отмены')),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='spares.company', verbose_name='Фирма')),
                ('contractor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='spares.contractors', verbose_name='Поставщик')),
                ('posted_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Провёл')),
                ('warehouse', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='spares.warehouses', verbose_name='Склад')),
            ],
            options={
                'default_permissions': (),
                'ordering': ('-date', '-pk'),
                'verbose_name': 'Многострочная накладная',
                'verbose_name_plural': 'Многострочные накладные',
                'constraints': [models.UniqueConstraint(condition=models.Q(('cancelled_at__isnull', True)), fields=('company', 'contractor', 'number_key'), name='unique_active_supplier_invoice')],
            },
        ),
        migrations.AddField(
            model_name='receipt',
            name='invoice',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='lines', to='spares.receiptinvoice', verbose_name='Многострочная накладная',
            ),
        ),
    ]
