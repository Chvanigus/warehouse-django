"""Проверки разметки аналитики с данными и разными правами просмотра."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from spares.models import Company, Contractors, Receipt, Spares, Warehouses


class AnalyticsPageTests(TestCase):
    """Проверяет график, быстрые периоды и доступность разделов через реальный URL."""

    @classmethod
    def setUpTestData(cls):
        """Создаёт приход и пользователя, которому тесты назначают отдельные права."""
        cls.warehouse = Warehouses.objects.create(name='Основной')
        Receipt.objects.create(
            company=Company.objects.create(name='Фирма'),
            warehouse=cls.warehouse,
            spare=Spares.objects.create(name='Фильтр'),
            contractor=Contractors.objects.create(name='Поставщик'),
            quantity=2,
            price=3,
        )
        cls.reader = get_user_model().objects.create_user('analytics-reader')

    def grant(self, *codenames):
        """Выдаёт нужные права и входит под тестовым пользователем."""
        self.reader.user_permissions.set(Permission.objects.filter(
            content_type__app_label='spares', codename__in=codenames,
        ))
        self.client.force_login(self.reader)

    def test_receipt_permission_shows_one_series_and_period_presets(self):
        """Показывает интерактивные месяцы и таблицу прихода без расходных показателей."""
        self.grant('view_receipt')
        response = self.client.get(reverse('spares:analytics'), {'warehouse': self.warehouse.pk})
        self.assertContains(response, 'data-chart-value', count=6)
        self.assertContains(response, 'Сумма прихода')
        self.assertContains(response, 'Быстрый выбор периода')
        self.assertContains(response, f'warehouse={self.warehouse.pk}&amp;start=')
        self.assertNotContains(response, 'Сумма расхода')
        self.assertNotContains(response, 'Состояние запасов')

    def test_stock_permission_shows_snapshot_without_period_controls(self):
        """Отображает текущий остаток независимо от неподходящего параметра месяца."""
        self.grant('view_stock')
        response = self.client.get(reverse('spares:analytics'), {'start': 'ошибка'})
        self.assertContains(response, 'Состояние запасов')
        self.assertNotContains(response, 'name="start"')
        self.assertNotContains(response, 'Сумма прихода')
