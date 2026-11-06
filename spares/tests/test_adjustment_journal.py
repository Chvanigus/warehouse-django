"""Доступ к журналу корректировок, фильтры и разбиение на страницы."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from spares.models import Company, Spares, Stock, StockAdjustment, Warehouses


class AdjustmentJournalTests(TestCase):
    """Проверяет просмотр корректировок остатков в интерфейсе."""

    @classmethod
    def setUpTestData(cls):
        """Создаёт корректировки на границе московских суток и пользователей с разным доступом."""
        user_model = get_user_model()
        cls.reader = user_model.objects.create_user(username='stock-reader')
        cls.reviewer = user_model.objects.create_user(username='stock-reviewer')
        cls.author = user_model.objects.create_user(username='operator-original')
        permissions = Permission.objects.filter(content_type__app_label='spares')
        cls.reader.user_permissions.add(permissions.get(codename='view_stock'))
        cls.reviewer.user_permissions.add(*permissions.filter(
            codename__in=['view_stock', 'view_stockadjustment'],
        ))
        company = Company.objects.create(name='Фирма')
        warehouse = Warehouses.objects.create(name='Основной')
        cls.stock = Stock.objects.create(
            company=company, warehouse=warehouse, spare=Spares.objects.create(name='Фильтр'),
        )
        cls.other_stock = Stock.objects.create(
            company=company, warehouse=warehouse, spare=Spares.objects.create(name='Лампа'),
        )
        cls.old = cls.make_entry(cls.stock, 'Фильтр', 'Сверка за прошлый день')
        cls.latest = cls.make_entry(cls.stock, 'Фильтр', 'Сверка [A] по пересчёту')
        cls.other = cls.make_entry(cls.other_stock, 'Лампа', 'Сверка [A] по пересчёту', after=Decimal('16.25'))
        StockAdjustment.objects.filter(pk=cls.old.pk).update(
            created_at=datetime(2026, 11, 4, 12, tzinfo=timezone.utc),
        )
        StockAdjustment.objects.filter(pk__in=[cls.latest.pk, cls.other.pk]).update(
            created_at=datetime(2026, 11, 4, 22, tzinfo=timezone.utc),
        )

    @classmethod
    def make_entry(cls, stock, stock_label, reason, *, after=Decimal('12.25')):
        """Создаёт запись корректировки с заданным итоговым количеством."""
        return StockAdjustment.objects.create(
            stock=stock, stock_label=stock_label, actor=cls.author, actor_name=cls.author.username,
            before=Decimal('15.00'), after=after, reason=reason,
        )

    def setUp(self):
        """Сохраняет адреса журнала и списка остатков."""
        self.url = reverse('spares:stock_adjustments')
        self.stock_url = reverse('spares:stock_report')

    def test_separate_view_permission_and_read_only_page(self):
        """Проверяет отдельное право просмотра и запрет записи через журнал."""
        self.assertRedirects(self.client.get(self.url), f"{reverse('spares:login')}?next={self.url}")
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertNotContains(self.client.get(self.stock_url), self.url)

        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(self.stock_url), f'{self.url}?stock={self.stock.pk}')
        self.assertEqual(self.client.post(self.url, {'reason': 'Новая причина'}).status_code, 405)
        self.assertEqual(StockAdjustment.objects.count(), 3)

    def test_filters_use_local_date_and_match_literal_cyrillic(self):
        """Проверяет московскую дату и буквальный поиск кириллицы со скобками."""
        self.client.force_login(self.reviewer)
        response = self.client.get(self.url, {
            'q': 'сверка [a]',
            'date_from': '2026-11-05',
            'date_to': '2026-11-05',
            'stock': self.stock.pk,
        })
        self.assertQuerySetEqual(response.context['entries'], [self.latest])
        self.assertContains(response, '05.11.2026 01:00:00')
        self.assertContains(response, '12,25')
        self.assertContains(response, '-2,75')
        self.assertContains(response, 'operator-original')
        self.assertNotContains(response, 'Лампа')
        self.assertContains(self.client.get(self.url, {'stock': '-1'}), 'Проверьте фильтры')

    def test_pagination_keeps_filters_and_stable_order(self):
        """Проверяет порядок записей с одинаковым временем и сохранение фильтра позиции."""
        self.client.force_login(self.reviewer)
        with patch('spares.adjustment_views.StockAdjustmentListView.paginate_by', 1):
            response = self.client.get(self.url, {'stock': self.stock.pk})
            self.assertQuerySetEqual(response.context['entries'], [self.latest])
            self.assertContains(response, f'?stock={self.stock.pk}&amp;page=2')
            response = self.client.get(self.url, {'stock': self.stock.pk, 'page': 2})
            self.assertQuerySetEqual(response.context['entries'], [self.old])
            response = self.client.get(self.url)
            self.assertQuerySetEqual(response.context['entries'], [self.other])
            self.assertContains(response, '+1,25')
