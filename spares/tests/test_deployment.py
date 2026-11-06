"""Регрессии для проверки готовности и восстановления резервной копии."""

import sqlite3
from contextlib import closing
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.db import OperationalError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.core.management import call_command
from django.core.management.base import CommandError

from spares.management.commands.warehouse_database import copy_database, read_database


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
