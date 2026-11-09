"""Регрессии для проверки готовности и восстановления резервной копии."""

import os
import sqlite3
from contextlib import closing
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.core.management import call_command
from django.core.management.base import CommandError

from spares.management.commands.warehouse_database import copy_database, read_database
from warehouse.settings import BASE_DIR, database_config


class ReadinessTests(TestCase):
    """Проверяет анонимный статус базы и закрытие подробностей при отказе."""

    def test_readiness_answers_anonymous_get_and_rejects_post(self):
        """Возвращает состояние готовой базы и принимает только безопасные методы."""
        url = reverse('readiness')
        response = self.client.get(url)
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(self.client.post(url).status_code, 405)

    def test_readiness_returns_service_unavailable_when_database_fails(self):
        """Скрывает текст ошибки драйвера и возвращает HTTP 503."""
        with patch('warehouse.health.connection.cursor', side_effect=OperationalError('Внутренний путь к базе')):
            response = self.client.get(reverse('readiness'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'unavailable'})


class DatabaseCopyTests(SimpleTestCase):
    """Проверяет перенос снимка и сохранность существующего файла назначения."""

    def test_backup_verify_and_restore_do_not_overwrite(self):
        """Копирует исходное состояние и блокирует повторное восстановление поверх него."""
        with TemporaryDirectory() as folder:
            source, snapshot, restored = (Path(folder) / name for name in ('live.sqlite3', 'copy.sqlite3', 'restore.sqlite3'))
            with closing(sqlite3.connect(source)) as database:
                database.executescript(
                    'CREATE TABLE django_migrations (id INTEGER PRIMARY KEY);'
                    'CREATE TABLE spares_stock (id INTEGER PRIMARY KEY);'
                    'INSERT INTO spares_stock VALUES (7);',
                )
                copy_database(source, snapshot)
                with database:
                    database.execute('INSERT INTO spares_stock VALUES (8)')
            call_command('warehouse_database', 'verify', snapshot, stdout=StringIO())
            copy_database(snapshot, restored)
            with self.assertRaises(CommandError):
                copy_database(source, restored)
            with closing(read_database(restored)) as database:
                self.assertEqual(database.execute('SELECT id FROM spares_stock').fetchall(), [(7,)])

    def test_failed_copy_is_never_published(self):
        """Оставляет каталог назначения без снимка при ошибке проверки SQLite."""
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'invalid.sqlite3'
            target = Path(folder) / 'copy.sqlite3'
            with closing(sqlite3.connect(source)) as database:
                database.execute('CREATE TABLE other (id INTEGER)')
            with self.assertRaises(CommandError):
                copy_database(source, target)
            self.assertEqual(list(Path(folder).iterdir()), [source])


class DatabaseConfigurationTests(SimpleTestCase):
    """Проверяет выбор сервера БД и явный отказ при неполных настройках PostgreSQL."""

    def test_sqlite_remains_default_and_uses_immediate_transactions(self):
        """Сохраняет локальный файл и сериализацию записей при отсутствии выбора PostgreSQL."""
        with patch.dict(os.environ, {}, clear=True):
            database = database_config()
        self.assertEqual(database['ENGINE'], 'django.db.backends.sqlite3')
        self.assertEqual(database['NAME'], BASE_DIR / 'db.sqlite3')
        self.assertEqual(database['OPTIONS']['transaction_mode'], 'IMMEDIATE')

    def test_postgresql_uses_server_credentials_without_sqlite_options(self):
        """Передаёт параметры контейнерного PostgreSQL выбранному драйверу без SQLite-опций."""
        environment = {
            'DATABASE_ENGINE': 'postgresql', 'POSTGRES_DB': 'warehouse',
            'POSTGRES_USER': 'warehouse_user', 'POSTGRES_PASSWORD': 'test-only-password',
            'POSTGRES_HOST': 'db', 'POSTGRES_PORT': '5439', 'DATABASE_PATH': 'ignored.sqlite3',
        }
        with patch.dict(os.environ, environment, clear=True):
            database = database_config()
        self.assertEqual(database['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(database['NAME'], 'warehouse')
        self.assertEqual(database['USER'], 'warehouse_user')
        self.assertEqual(database['PASSWORD'], 'test-only-password')
        self.assertEqual(database['HOST'], 'db')
        self.assertEqual(database['PORT'], '5439')
        self.assertNotIn('transaction_mode', database['OPTIONS'])

    def test_postgresql_defaults_to_localhost_for_native_python(self):
        """Подключает Python вне Compose к стандартному адресу локального PostgreSQL."""
        environment = {
            'DATABASE_ENGINE': 'postgresql', 'POSTGRES_DB': 'warehouse',
            'POSTGRES_USER': 'warehouse', 'POSTGRES_PASSWORD': 'test-only-password',
        }
        with patch.dict(os.environ, environment, clear=True):
            database = database_config()
        self.assertEqual((database['HOST'], database['PORT']), ('localhost', '5432'))

    def test_incomplete_postgresql_settings_fail_before_connection(self):
        """Требует каждый параметр PostgreSQL и не переключается на пустую базу SQLite."""
        environment = {
            'DATABASE_ENGINE': 'postgresql', 'POSTGRES_DB': 'warehouse',
            'POSTGRES_USER': 'warehouse', 'POSTGRES_PASSWORD': 'test-only-password',
        }
        for required in ('POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD'):
            with self.subTest(variable=required):
                incomplete = {name: value for name, value in environment.items() if name != required}
                with patch.dict(os.environ, incomplete, clear=True):
                    with self.assertRaisesMessage(ImproperlyConfigured, required):
                        database_config()

    def test_unknown_database_engine_is_rejected(self):
        """Останавливает запуск при опечатке вместо неявного открытия SQLite."""
        with patch.dict(os.environ, {'DATABASE_ENGINE': 'postgress'}, clear=True):
            with self.assertRaisesMessage(ImproperlyConfigured, 'DATABASE_ENGINE'):
                database_config()


class PostgreSQLBackupGuardTests(SimpleTestCase):
    """Запрещает применять файловые операции SQLite к рабочей базе PostgreSQL."""

    def test_backup_and_restore_require_postgresql_tools(self):
        """Отказывает до доступа к файлам и указывает pg_dump и pg_restore."""
        database_settings = SimpleNamespace(DATABASES={'default': {
            'ENGINE': 'django.db.backends.postgresql', 'NAME': 'warehouse',
        }})
        with TemporaryDirectory() as folder:
            snapshot = Path(folder) / 'copy.sqlite3'
            for action in ('backup', 'restore'):
                with self.subTest(action=action):
                    with patch('spares.management.commands.warehouse_database.settings', database_settings):
                        with self.assertRaisesMessage(CommandError, 'pg_dump и pg_restore'):
                            call_command('warehouse_database', action, snapshot, stdout=StringIO())
            self.assertEqual(list(Path(folder).iterdir()), [])
