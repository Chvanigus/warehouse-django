"""Очередь заявок на проведение операций и права согласования."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Создаёт таблицу заявок с историей автора, решения и проведённого документа."""

    dependencies = [
        ('spares', '0041_inventory_sheets'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StockRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('receipt', 'Приход'), ('receipt_invoice', 'Накладная прихода'), ('writeoff', 'Списание'), ('transfer', 'Перемещение')], editable=False, max_length=20, verbose_name='Вид операции')),
                ('title', models.CharField(editable=False, max_length=255, verbose_name='Краткое описание')),
                ('payload', models.JSONField(editable=False, verbose_name='Исходные данные')),
                ('status', models.CharField(choices=[('pending', 'На согласовании'), ('applied', 'Проведена'), ('rejected', 'Отклонена')], db_index=True, default='pending', max_length=8, verbose_name='Статус')),
                ('created_by_name', models.CharField(editable=False, max_length=150, verbose_name='Имя автора при подаче')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Время подачи')),
                ('reviewed_by_name', models.CharField(blank=True, max_length=150, verbose_name='Имя сотрудника при рассмотрении')),
                ('reviewed_at', models.DateTimeField(blank=True, null=True, verbose_name='Время решения')),
                ('review_note', models.CharField(blank=True, max_length=500, verbose_name='Причина отклонения')),
                ('result', models.JSONField(blank=True, default=dict, verbose_name='Ссылка на проведённый документ')),
                ('applied_automatically', models.BooleanField(default=False, verbose_name='Проведена сразу при подаче')),
                ('created_by', models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Автор')),
                ('reviewed_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Согласовавший сотрудник')),
            ],
            options={
                'verbose_name': 'Складская заявка',
                'verbose_name_plural': 'Складские заявки',
                'ordering': ('-created_at', '-pk'),
                'permissions': [('approve_stockrequest', 'Может согласовывать складские заявки'), ('manage_warehouse_users', 'Может управлять пользователями склада')],
                'default_permissions': ('add', 'view'),
            },
        ),
    ]
