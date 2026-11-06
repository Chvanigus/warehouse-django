"""Транзакционная подача, проведение и отклонение складских заявок."""

import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from .request_models import StockRequest
from .validators import load_operation_actor


def _require_permission(actor, permission):
    """Возвращает активного автора с актуальным разрешением на действие."""
    actor = load_operation_actor(actor, 'Для работы с заявкой нужен автор.')
    if not actor.has_perm(permission):
        raise PermissionDenied
    return actor


def _snapshot(payload):
    """Отделяет сохранённые данные от входного словаря и проверяет сериализацию."""
    if not isinstance(payload, dict):
        raise ValidationError('Исходные данные заявки должны быть объектом.')
    try:
        return json.loads(json.dumps(payload, cls=DjangoJSONEncoder, allow_nan=False))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValidationError('Не удалось сохранить исходные данные заявки.') from error


def _pending_for_review(request_pk, actor):
    """Блокирует заявку и проверяет, что её ещё может рассмотреть другой сотрудник."""
    try:
        stock_request = StockRequest.objects.select_for_update().get(pk=request_pk)
    except StockRequest.DoesNotExist as error:
        raise ValidationError('Заявка отсутствует.') from error
    if stock_request.created_by_id == actor.pk:
        raise PermissionDenied('Автор не может рассмотреть собственную ожидающую заявку.')
    if stock_request.status != StockRequest.Status.PENDING:
        raise ValidationError('Решение по заявке уже принято.')
    return stock_request


def _finish(stock_request, *, actor, status, note='', result=None, automatic=False):
    """Сохраняет решение, не меняя исходные данные или автора заявки."""
    stock_request.status = status
    stock_request.reviewed_by = actor
    stock_request.reviewed_by_name = actor.get_username()
    stock_request.reviewed_at = timezone.now()
    stock_request.review_note = note
    stock_request.result = result if result is not None else {}
    stock_request.applied_automatically = automatic
    stock_request.save(update_fields=(
        'status', 'reviewed_by', 'reviewed_by_name', 'reviewed_at', 'review_note', 'result', 'applied_automatically',
    ))
    return stock_request


def _apply(stock_request, actor, *, automatic=False):
    """Проводит операцию из снимка и связывает заявку с полученным документом."""
    from .request_operations import apply_request

    result = apply_request(stock_request.kind, _snapshot(stock_request.payload), actor)
    if (
        not isinstance(result, dict) or not isinstance(result.get('route'), str) or not result['route']
        or type(result.get('pk')) is not int or result['pk'] <= 0
    ):
        raise ValidationError('Не удалось связать заявку с проведённым документом.')
    return _finish(
        stock_request, actor=actor, status=StockRequest.Status.APPLIED, result=_snapshot(result), automatic=automatic,
    )


@transaction.atomic
def submit_stock_request(kind, payload, *, actor, title):
    """Сохраняет заявку, а при праве согласования проводит её в той же транзакции."""
    actor = _require_permission(actor, 'spares.add_stockrequest')
    if kind not in StockRequest.Kind.values:
        raise ValidationError('Неизвестный вид складской заявки.')
    title = (title or '').strip()[:StockRequest._meta.get_field('title').max_length]
    if not title:
        raise ValidationError('Укажите описание заявки.')
    stock_request = StockRequest.objects.create(
        kind=kind, title=title, payload=_snapshot(payload), created_by=actor, created_by_name=actor.get_username(),
    )
    if actor.has_perm('spares.approve_stockrequest'):
        return _apply(stock_request, actor, automatic=True)
    return stock_request


@transaction.atomic
def approve_stock_request(request_pk, *, actor):
    """Проводит ожидающую заявку другого автора и записывает решение согласовавшего."""
    actor = _require_permission(actor, 'spares.approve_stockrequest')
    return _apply(_pending_for_review(request_pk, actor), actor)


@transaction.atomic
def reject_stock_request(request_pk, *, actor, reason):
    """Отклоняет ожидающую заявку другого автора и сохраняет обязательную причину."""
    actor = _require_permission(actor, 'spares.approve_stockrequest')
    stock_request = _pending_for_review(request_pk, actor)
    reason = StockRequest._meta.get_field('review_note').clean((reason or '').strip(), stock_request)
    if not reason:
        raise ValidationError('Укажите причину отклонения.')
    return _finish(stock_request, actor=actor, status=StockRequest.Status.REJECTED, note=reason)
