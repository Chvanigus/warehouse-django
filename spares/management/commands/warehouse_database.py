"""Резервное копирование и безопасное восстановление SQLite склада."""

import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def read_database(path):
    """Открывает существующий файл SQLite только для чтения."""
    return sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True, timeout=20)


def verify_database(database):
    """Проверяет таблицы склада, целостность SQLite и ссылочные связи."""
    tables = {row[0] for row in database.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('django_migrations', 'spares_stock')",
    )}
    if tables != {'django_migrations', 'spares_stock'}:
        raise CommandError('Файл не содержит таблицы базы склада.')
    if database.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise CommandError('Проверка целостности SQLite завершилась ошибкой.')
    if database.execute('PRAGMA foreign_key_check').fetchone() is not None:
        raise CommandError('В SQLite найдены нарушенные ссылочные связи.')


def copy_database(source, target):
    """Сохраняет проверенный снимок рядом с целью и публикует его без перезаписи."""
    if os.path.lexists(target):
        raise CommandError(f'Файл уже существует: {target}')
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.warehouse-', suffix='.tmp', delete=False) as handle:
        staged = Path(handle.name)
    try:
        with closing(read_database(source)) as original, closing(sqlite3.connect(staged)) as snapshot:
            original.backup(snapshot)
            verify_database(snapshot)
        if os.name == 'nt':
            staged.rename(target)
        else:
            os.link(staged, target)
    finally:
        staged.unlink(missing_ok=True)


class Command(BaseCommand):
    """Управляет снимками базы отдельно от миграций и запуска веб-сервера."""

    help = 'Создать, проверить или восстановить резервную копию базы SQLite склада.'
    requires_system_checks = []

    def add_arguments(self, parser):
        """Принимает действие и путь к файлу резервной копии."""
        parser.add_argument('action', choices=('backup', 'verify', 'restore'))
        parser.add_argument('path', type=Path, help='Путь к копии или «-» для восстановления из stdin.')

    def handle(self, *args, **options):
        """Выполняет операцию над копией, не заменяя существующую базу."""
        action = options['action']
        path = options['path']
        database = settings.DATABASES['default']
        try:
            if action == 'verify':
                with closing(read_database(path)) as snapshot:
                    verify_database(snapshot)
                self.stdout.write(self.style.SUCCESS('Копия прошла проверку целостности.'))
                return

            if database['ENGINE'] != 'django.db.backends.sqlite3':
                raise CommandError(
                    'Команда поддерживает только файловую базу SQLite. '
                    'Для PostgreSQL используйте pg_dump и pg_restore.',
                )
            if str(database['NAME']) == ':memory:':
                raise CommandError('Команда поддерживает только файловую базу SQLite.')
            database_path = Path(database['NAME'])
            if action == 'backup':
                copy_database(database_path, path)
                self.stdout.write(self.style.SUCCESS(f'Копия создана и проверена: {path}'))
                return

            if any(os.path.lexists(f'{database_path}{suffix}') for suffix in ('-journal', '-wal', '-shm')):
                raise CommandError('В каталоге есть журналы SQLite. Восстанавливайте копию в пустой том.')
            if path == Path('-'):
                with tempfile.TemporaryDirectory(dir=database_path.parent) as folder:
                    incoming = Path(folder) / 'source.sqlite3'
                    with incoming.open('wb') as stream:
                        shutil.copyfileobj(sys.stdin.buffer, stream)
                    copy_database(incoming, database_path)
            else:
                copy_database(path, database_path)
            self.stdout.write(self.style.SUCCESS(f'База восстановлена: {database_path}'))
        except (OSError, sqlite3.Error) as error:
            raise CommandError(f'Операция с SQLite не выполнена: {error}') from error
