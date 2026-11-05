import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('spares', '0040_receipt_invoices'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='InventorySheet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_by_name', models.CharField(max_length=150, verbose_name='Автор при составлении')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Время составления')),
                ('note', models.CharField(blank=True, max_length=500, verbose_name='Примечание')),
                ('status', models.CharField(choices=[('pending', 'На проверке'), ('approved', 'Подтверждена'), ('rejected', 'Отклонена')], default='pending', max_length=8, verbose_name='Статус')),
                ('reviewed_by_name', models.CharField(blank=True, max_length=150, verbose_name='Имя контролёра при проверке')),
                ('reviewed_at', models.DateTimeField(blank=True, null=True, verbose_name='Время проверки')),
                ('review_note', models.CharField(blank=True, max_length=500, verbose_name='Комментарий контролёра')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Автор')),
                ('reviewed_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Контролёр')),
                ('warehouse', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='spares.warehouses', verbose_name='Склад')),
            ],
            options={
                'default_permissions': ('add', 'view'),
                'permissions': [('approve_inventorysheet', 'Может проверять инвентаризационные ведомости')],
                'ordering': ('-created_at', '-pk'),
                'verbose_name': 'Инвентаризационная ведомость',
                'verbose_name_plural': 'Инвентаризационные ведомости',
            },
        ),
        migrations.CreateModel(
            name='InventorySheetLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stock_revision', models.JSONField(editable=False)),
                ('adjustment', models.OneToOneField(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='sheet_line', to='spares.stockadjustment')),
                ('count', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='sheet_line', to='spares.inventorycount')),
                ('sheet', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='spares.inventorysheet')),
            ],
            options={
                'default_permissions': (),
                'ordering': ('pk',),
            },
        ),
    ]
