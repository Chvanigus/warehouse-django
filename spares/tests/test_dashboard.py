"""Показатели склада и доступность действий на главной странице."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from spares.models import Company, Contractors, Receipt, Spares, Stock, Warehouses


class DashboardTests(TestCase):
    """Проверяет сводку поступлений и остатков с учётом разрешений."""

    def test_dashboard_shows_only_permitted_monthly_metrics(self):
        """Проверяет подсчёт текущего месяца и сокрытие операций без права доступа."""
        user = get_user_model().objects.create_user('reader')
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='spares', codename__in=['view_receipt', 'view_stock'],
        ))
        company = Company.objects.create(name='Фирма')
        warehouse = Warehouses.objects.create(name='Основной')
        spare = Spares.objects.create(name='Колодки')
        contractor = Contractors.objects.create(name='Поставщик')
        for operation_date in (date(2026, 10, 28), date(2026, 11, 2), date(2026, 11, 3)):
            receipt = Receipt.objects.create(
                company=company, warehouse=warehouse, spare=spare, contractor=contractor,
                date=operation_date, quantity=1,
            )
        # The former version allowed a future date on an already posted entry.
        Receipt.objects.filter(pk=receipt.pk).update(date=date(2026, 11, 30))
        stock = Stock.objects.get()
        stock.inventory = 2
        stock.save(update_fields=['inventory'])
        self.client.force_login(user)
        with patch('spares.views.timezone.localdate', return_value=date(2026, 11, 5)):
            response = self.client.get(reverse('spares:warehouse_main'))
        self.assertEqual(response.context['receipt_count'], 1)
        self.assertEqual(len(response.context['recent_receipts']), 2)
        self.assertEqual(response.context['stock_summary'], {'positions': 1, 'discrepancies': 1})
        self.assertContains(response, reverse('spares:stock_report') + '?discrepancy=1')
        self.assertNotContains(response, reverse('invoices:add'))
        self.assertNotContains(response, reverse('operations:writeoffs'))
