"""Настройка стандартных групп оператора и контролёра склада."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


OPERATOR_GROUP = 'Склад · оператор'
CONTROLLER_GROUP = 'Склад · контролёр'

CATALOG_MODELS = {
    'company', 'contractors', 'machineworker', 'machines', 'measuremeasurement',
    'spares', 'trailers', 'warehouses', 'workers',
}
READ_PERMISSIONS = {
    f'view_{model}' for model in CATALOG_MODELS | {
        'receipt', 'writeoff', 'stocktransfer', 'movement', 'stock',
        'inventorycount', 'inventorysheet', 'stockminimum', 'stockadjustment',
    }
}
OPERATOR_PERMISSIONS = READ_PERMISSIONS | {
    'add_receipt', 'add_writeoff', 'add_stocktransfer', 'add_inventorycount', 'add_inventorysheet',
}
CONTROLLER_PERMISSIONS = READ_PERMISSIONS | {
    'delete_receipt', 'delete_writeoff', 'delete_stocktransfer',
    'add_stock', 'change_stock', 'approve_inventorysheet',
    'add_stockminimum', 'change_stockminimum', 'delete_stockminimum',
} | {
    f'{action}_{model}' for action in ('add', 'change') for model in CATALOG_MODELS
}


class Command(BaseCommand):
    """Команда Django для назначения складских прав и добавления пользователей в группы."""

    help = 'Настроить стандартные права оператора и контролёра склада.'

    def add_arguments(self, parser):
        """Добавить повторяемые параметры для назначения оператора и контролёра."""
        parser.add_argument('--operator', action='append', default=[], metavar='USER')
        parser.add_argument('--controller', action='append', default=[], metavar='USER')

    @transaction.atomic
    def handle(self, *args, **options):
        """Проверить права после миграций и обновить группы и пользователей в одной транзакции."""
        permissions = {
            permission.codename: permission
            for permission in Permission.objects.filter(
                content_type__app_label='spares',
                codename__in=OPERATOR_PERMISSIONS | CONTROLLER_PERMISSIONS,
            )
        }
        missing = (OPERATOR_PERMISSIONS | CONTROLLER_PERMISSIONS) - permissions.keys()
        if missing:
            raise CommandError(f"Выполните миграции. Отсутствуют права {', '.join(sorted(missing))}.")

        user_model = get_user_model()
        users = user_model._default_manager
        for group_name, allowed, usernames in (
            (OPERATOR_GROUP, OPERATOR_PERMISSIONS, options['operator']),
            (CONTROLLER_GROUP, CONTROLLER_PERMISSIONS, options['controller']),
        ):
            group, _ = Group.objects.get_or_create(name=group_name)
            group.permissions.set(permissions[codename] for codename in allowed)
            for username in usernames:
                try:
                    user = users.get_by_natural_key(username)
                except user_model.DoesNotExist as error:
                    raise CommandError(f'Пользователь «{username}» не найден.') from error
                user.groups.add(group)
        self.stdout.write(self.style.SUCCESS('Стандартные роли склада настроены.'))
