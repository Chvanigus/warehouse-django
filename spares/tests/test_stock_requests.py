"""Проверки жизненного цикла и прав доступа к складским заявкам."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from spares.request_models import StockRequest
from spares.request_services import approve_stock_request, reject_stock_request, submit_stock_request


class StockRequestTests(TestCase):
    """Проверяет подачу, принятие решения и разграничение доступа к очереди."""

    @classmethod
    def setUpTestData(cls):
        """Создаёт двух операторов и согласующего с раздельными правами."""
        users = get_user_model().objects
        cls.operator = users.create_user(username='operator')
        cls.other_operator = users.create_user(username='other-operator')
        cls.reviewer = users.create_user(username='reviewer')
        cls.permissions = {
            permission.codename: permission
            for permission in Permission.objects.filter(content_type__app_label='spares', content_type__model='stockrequest')
        }
        for actor in (cls.operator, cls.other_operator):
            actor.user_permissions.add(cls.permissions['add_stockrequest'], cls.permissions['view_stockrequest'])
        cls.reviewer.user_permissions.add(*cls.permissions.values())

    def _submit(self, *, actor=None, title='Подшипники на склад', payload=None):
        """Подаёт заявку на приход с указанным автором и реквизитами."""
        return submit_stock_request(
            StockRequest.Kind.RECEIPT, {'quantity': '2.00'} if payload is None else payload,
            actor=actor if actor is not None else self.operator, title=title,
        )

    @patch('spares.request_operations.apply_request')
    def test_operator_snapshot_waits_for_reviewer_and_is_applied_once(self, apply_request):
        """Подача сохраняет копию реквизитов, а повторное решение не проводит документ снова."""
        apply_request.return_value = {'route': 'operations:receipts', 'pk': 7, 'query': {'entry': 7}}
        payload = {'quantity': '2.00', 'internal': {'key': ['original']}}
        submitted = self._submit(payload=payload)
        payload['internal']['key'].append('changed')
        self.assertEqual(submitted.status, StockRequest.Status.PENDING)
        self.assertEqual(submitted.created_by_name, 'operator')
        apply_request.assert_not_called()

        reviewed = approve_stock_request(submitted.pk, actor=self.reviewer)
        apply_request.assert_called_once_with(StockRequest.Kind.RECEIPT, reviewed.payload, self.reviewer)
        self.assertEqual(reviewed.payload['internal']['key'], ['original'])
        self.assertEqual(reviewed.status, StockRequest.Status.APPLIED)
        self.assertFalse(reviewed.applied_automatically)
        self.assertEqual(reviewed.reviewed_by_name, 'reviewer')
        self.assertIsNotNone(reviewed.reviewed_at)
        self.assertEqual(reviewed.result['pk'], 7)
        with self.assertRaisesMessage(ValidationError, 'Решение по заявке уже принято.'):
            approve_stock_request(submitted.pk, actor=self.reviewer)
        self.assertEqual(apply_request.call_count, 1)

        self.client.force_login(self.operator)
        response = self.client.get(reverse('stock_requests:detail', args=[submitted.pk]))
        result_url = reverse('operations:receipts', query={'entry': 7})
        self.assertContains(response, f'href="{result_url}"')

    @patch('spares.request_operations.apply_request', return_value={'route': 'transfers:detail', 'pk': 7})
    def test_reviewer_submission_is_applied_automatically(self, apply_request):
        """Согласующий проводит свою новую заявку сразу при подаче."""
        submitted = self._submit(actor=self.reviewer)
        self.assertEqual(submitted.status, StockRequest.Status.APPLIED)
        self.assertEqual(submitted.reviewed_by, self.reviewer)
        self.assertTrue(submitted.applied_automatically)
        self.assertEqual(submitted.result['pk'], 7)
        apply_request.assert_called_once()

    @patch('spares.request_operations.apply_request')
    def test_rejection_requires_reason_and_preserves_names(self, apply_request):
        """Отклонение требует текст, сохраняет снимки имён и не запускает проведение."""
        submitted = self._submit()
        with self.assertRaisesMessage(ValidationError, 'Укажите причину отклонения.'):
            reject_stock_request(submitted.pk, actor=self.reviewer, reason='   ')
        rejected = reject_stock_request(submitted.pk, actor=self.reviewer, reason='  Неверное количество  ')
        self.reviewer.delete()
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, StockRequest.Status.REJECTED)
        self.assertEqual(rejected.review_note, 'Неверное количество')
        self.assertEqual(rejected.reviewed_by_name, 'reviewer')
        self.assertIsNone(rejected.reviewed_by)
        self.assertEqual(rejected.result, {})
        apply_request.assert_not_called()

    def test_author_with_new_permissions_cannot_review_old_own_request(self):
        """Появление права согласования не разрешает автору принять старую заявку."""
        submitted = self._submit()
        self.operator.user_permissions.add(self.permissions['approve_stockrequest'])
        promoted_operator = get_user_model().objects.get(pk=self.operator.pk)
        with self.assertRaises(PermissionDenied):
            approve_stock_request(submitted.pk, actor=promoted_operator)
        with self.assertRaises(PermissionDenied):
            reject_stock_request(submitted.pk, actor=promoted_operator, reason='Отказ')

    @patch('spares.request_operations.apply_request')
    def test_apply_failure_rolls_back_effects_and_preserves_pending_request(self, apply_request):
        """Ошибка проведения откатывает промежуточную запись и оставляет заявку ожидающей."""
        submitted = self._submit()

        def fail_after_write(kind, payload, actor):
            """Имитирует запись операции перед ошибкой бизнес-правила."""
            StockRequest.objects.filter(pk=submitted.pk).update(title='Изменение внутри операции')
            raise ValidationError('Остаток изменился.')

        apply_request.side_effect = fail_after_write
        with self.assertRaisesMessage(ValidationError, 'Остаток изменился.'):
            approve_stock_request(submitted.pk, actor=self.reviewer)
        submitted.refresh_from_db()
        self.assertEqual(submitted.title, 'Подшипники на склад')
        self.assertEqual(submitted.status, StockRequest.Status.PENDING)
        self.assertIsNone(submitted.reviewed_at)

    def test_queue_scopes_operator_and_keeps_review_post_only(self):
        """Автор видит свои заявки, согласующий видит очередь, решение доступно через POST."""
        mine = self._submit(title='Моя проверка прихода')
        other = self._submit(actor=self.other_operator, title='Чужая проверка прихода')
        self.client.force_login(self.operator)
        response = self.client.get(reverse('stock_requests:list'))
        self.assertContains(response, mine.title)
        self.assertNotContains(response, other.title)
        self.assertEqual(self.client.get(reverse('stock_requests:detail', args=[other.pk])).status_code, 404)
        approval_url = reverse('stock_requests:approve', args=[mine.pk])
        self.assertEqual(self.client.post(approval_url).status_code, 403)

        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(reverse('stock_requests:list')), other.title)
        self.assertEqual(self.client.get(approval_url).status_code, 405)
        self.assertRedirects(
            self.client.post(reverse('stock_requests:reject', args=[mine.pk]), {'reason': 'Неверный склад'}),
            reverse('stock_requests:detail', args=[mine.pk]),
        )
        self.assertNotContains(self.client.get(reverse('stock_requests:list')), mine.title)
        self.assertContains(self.client.get(reverse('stock_requests:list'), {'status': 'rejected'}), mine.title)
