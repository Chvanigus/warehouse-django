"""Настройка стандартных групп и назначение складских ролей."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from spares.warehouse_roles import WAREHOUSE_ROLES, WAREHOUSE_ROLE_PERMISSIONS

OPERATOR_GROUP = WAREHOUSE_ROLES['operator']
CONTROLLER_GROUP = WAREHOUSE_ROLES['reviewer']


class Command(BaseCommand):
    """Команда Django для назначения складских прав и добавления пользователей в группы."""

    help = 'Настроить права оператора, проверяющего и администратора склада.'

    def add_arguments(self, parser):
        """Добавить повторяемые параметры назначения ролей и сохранить прежний ключ контролёра."""
        parser.add_argument('--operator', action='append', default=[], metavar='USER')
        parser.add_argument('--controller', '--reviewer', action='append', default=[], metavar='USER')
        parser.add_argument('--admin', action='append', default=[], metavar='USER')

    @transaction.atomic
    def handle(self, *args, **options):
        """Проверить права после миграций и обновить группы и пользователей в одной транзакции."""
        assignments = {'operator': options['operator'], 'reviewer': options['controller'], 'admin': options['admin']}
        usernames = [username for names in assignments.values() for username in set(names)]
        if len(set(usernames)) != len(usernames):
            raise CommandError('Для одной учётной записи можно указать только одну складскую роль.')

        required = set().union(*WAREHOUSE_ROLE_PERMISSIONS.values())
        permissions = {
            permission.codename: permission
            for permission in Permission.objects.filter(
                content_type__app_label='spares',
                codename__in=required,
            )
        }
        missing = required - permissions.keys()
        if missing:
            raise CommandError(f"Выполните миграции. Отсутствуют права {', '.join(sorted(missing))}.")

        user_model = get_user_model()
        users = user_model._default_manager
        for role, group_name in WAREHOUSE_ROLES.items():
            group, _ = Group.objects.get_or_create(name=group_name)
            group.permissions.set(permissions[codename] for codename in WAREHOUSE_ROLE_PERMISSIONS[role])
            for username in assignments[role]:
                try:
                    user = users.get_by_natural_key(username)
                except user_model.DoesNotExist as error:
                    raise CommandError(f'Пользователь «{username}» не найден.') from error
                user.groups.remove(*user.groups.filter(name__in=WAREHOUSE_ROLES.values()).exclude(pk=group.pk))
                user.groups.add(group)
        self.stdout.write(self.style.SUCCESS('Стандартные роли склада настроены.'))
