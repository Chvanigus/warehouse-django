"""Датированные пересчёты и их связь с последующими операциями."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from spares.context_processors.income_outcome_report import get_income_report
from spares.models import Company, Contractors, InventoryCount, Receipt, Spares, Stock, Warehouses


class DatedInventoryTests(TestCase):
    """Проверяет достоверность исторического среза и суммы приходного отчёта."""

    @classmethod
    def setUpTestData(cls):
        """Создаёт складскую позицию и пользователя с доступом к пересчётам."""
        cls.company = Company.objects.create(name='Фирма')
        cls.warehouse = Warehouses.objects.create(name='Основной')
        cls.spare = Spares.objects.create(name='Фильтр')
        cls.contractor = Contractors.objects.create(name='Поставщик')
        cls.operator = get_user_model().objects.create_user('counter')
        cls.operator.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='spares',
            codename__in=['add_inventorycount', 'view_inventorycount'],
        ))

    def receipt(self, quantity, **kwargs):
        """Проводит поступление в тестовом складе с заданным количеством."""
        return Receipt.objects.create(
            company=self.company, warehouse=self.warehouse, spare=self.spare, contractor=self.contractor,
            quantity=quantity, price=2, **kwargs,
        )

    def test_dated_count_does_not_follow_subsequent_movements(self):
        """Проверяет сохранение данных пересчёта после нового прихода."""
        self.receipt(5)
        self.client.force_login(self.operator)
        stock = Stock.objects.get()
        url = reverse('inventory:add', args=[stock.pk])
        revision = self.client.get(url).context['form']['revision'].value()
        report = reverse('inventory:list', query={'stock': stock.pk})
        self.assertRedirects(self.client.post(
            url, {'counted_quantity': '5', 'note': 'Ведомость № 12', 'revision': revision},
        ), report)
        self.receipt(2)
        count = InventoryCount.objects.get()
        stock.refresh_from_db()
        self.assertEqual(count.actor, self.operator)
        self.assertEqual((count.book_quantity, count.counted_quantity), (5, 5))
        self.assertEqual(stock.actual_balance, 7)
        self.assertEqual(stock.inventory_book_balance, 5)
        self.assertFalse(stock.discrepancy)
        self.assertContains(self.client.get(report), 'Ведомость № 12')

    def test_stale_count_is_rejected_and_fractional_count_records_difference(self):
        """Проверяет отказ для устаревшего пересчёта и точность дробного расхождения."""
        self.receipt(5)
        self.client.force_login(self.operator)
        stock = Stock.objects.get()
        url = reverse('inventory:add', args=[stock.pk])
        revision = self.client.get(url).context['form']['revision'].value()
        self.receipt(2)
        response = self.client.post(url, {'counted_quantity': '4.75', 'revision': revision})
        self.assertContains(response, 'Остаток изменился после открытия формы')
        self.assertFalse(InventoryCount.objects.exists())
        revision = self.client.get(url).context['form']['revision'].value()
        self.assertEqual(self.client.post(url, {'counted_quantity': '6.75', 'revision': revision}).status_code, 302)
        self.assertEqual(InventoryCount.objects.get().difference, Decimal('-0.25'))
        stock.refresh_from_db()
        self.assertTrue(stock.discrepancy)
        self.assertEqual(stock.actual_balance, 7)

    def test_future_receipt_has_no_effect_and_cancellation_excludes_amount_from_report(self):
        """Проверяет отклонение будущего прихода и исключение отменённой суммы из отчёта."""
        with self.assertRaisesMessage(ValidationError, 'Дата проведения не может быть в будущем'):
            self.receipt(5, date=timezone.localdate() + timedelta(days=1))
        self.assertFalse(Stock.objects.exists())
        receipt = self.receipt(5)
        self.assertEqual(get_income_report()[0]['year_total'], Decimal('10.00'))
        receipt.cancel(actor=self.operator, reason='Дубль')
        self.assertFalse(get_income_report())
        self.assertEqual(Stock.objects.get().actual_balance, 0)
        with self.assertRaises(ValidationError):
            receipt.cancel(actor=self.operator, reason='Повтор')
