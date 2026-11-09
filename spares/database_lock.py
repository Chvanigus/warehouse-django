"""Общая транзакционная блокировка складских записей в PostgreSQL."""

from django.db import connections
from django.db.transaction import TransactionManagementError


# Стабильный ключ «WHSTOCK1»; блокировки изолированы в пределах текущей базы.
WAREHOUSE_WRITE_LOCK = int.from_bytes(b'WHSTOCK1', 'big')


def lock_warehouse_writes(using='default'):
    """Сериализует записи до блокировок строк и освобождается с завершением транзакции.

    PostgreSQL не блокирует отсутствующий остаток через SELECT FOR UPDATE.
    Общая блокировка сохраняет прежнее поведение SQLite IMMEDIATE без изменения
    исторических дублей: одновременно выполняется одна складская запись,
    чтение остаётся параллельным. Все пути записи берут её до строк автора,
    документа и остатка, чтобы не менять порядок захвата блокировок.
    """
    database = connections[using]
    if database.vendor != 'postgresql':
        return
    if not database.in_atomic_block:
        raise TransactionManagementError('Складскую блокировку нужно брать внутри transaction.atomic().')
    with database.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [WAREHOUSE_WRITE_LOCK])
