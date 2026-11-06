"""Подготовка, согласование и атомарность инвентаризационных ведомостей."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from spares.inventory_sheet_models import InventorySheet
from spares.inventory_sheet_services import review_inventory_sheet, submit_inventory_sheet
from spares.models import Company, InventoryCount, Spares, Stock, StockAdjustment, Warehouses
from spares.stock_adjustments import record_manual_stock


class InventorySheetTests(TestCase):
    """Проверяет форму ведомости, полномочия и связанные корректировки."""

    @classmethod
    def setUpTestData(cls):
        """Создаёт два склада, контрольные остатки и участников с разными разрешениями."""
        cls.warehouse = Warehouses.objects.create(name='Основной')
        cls.other_warehouse = Warehouses.objects.create(name='Другой')
        cls.company = Company.objects.create(name='Фирма')
        cls.first = cls.make_stock('Первый фильтр', 10, cls.warehouse)
        cls.second = cls.make_stock('Второй фильтр', 20, cls.warehouse)
        cls.other = cls.make_stock('Сторонняя деталь', 7, cls.other_warehouse)
        cls.operator = get_user_model().objects.create_user('inventory-operator')
        cls.controller = get_user_model().objects.create_user('inventory-controller')
        cls.grant(cls.operator, 'view_inventorysheet', 'add_inventorysheet')
        cls.grant(cls.controller, 'view_inventorysheet', 'approve_inventorysheet', 'view_stockadjustment')

    @classmethod
    def make_stock(cls, name, quantity, warehouse):
        """Создаёт позицию с согласованными учётным и фактическим остатками."""
        return Stock.objects.create(
            spare=Spares.objects.create(name=name), warehouse=warehouse, company=cls.company,
            price='100.00', actual_balance=quantity, inventory=quantity, inventory_book_balance=quantity,
        )

    @classmethod
    def grant(cls, user, *permissions):
        """Добавляет складские разрешения выбранному участнику."""
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='spares', codename__in=permissions,
        ))

    def make_sheet(self, second_quantity='20'):
        """Подаёт ведомость из двух позиций с заданным количеством второй строки."""
        return submit_inventory_sheet(
            warehouse=self.warehouse, actor=self.operator,
            entries=[(self.first, Decimal('9.75')), (self.second, Decimal(second_quantity))],
        )

    def open_form(self, actor=None):
        """Открывает ведомость нужного склада и возвращает параметры её отправки."""
        self.client.force_login(actor or self.operator)
        url = reverse('inventory_sheets:add')
        response = self.client.get(url, {'warehouse': self.warehouse.pk})
        self.assertContains(response, 'Первый фильтр')
        self.assertNotContains(response, 'Сторонняя деталь')
        return url, {
            'warehouse': self.warehouse.pk,
            'snapshot': response.context['form']['snapshot'].value(),
            'form-TOTAL_FORMS': '2',
            'form-INITIAL_FORMS': '0',
            'form-0-stock': self.first.pk,
            'form-0-counted_quantity': '9.75',
            'form-1-stock': self.second.pk,
            'form-1-counted_quantity': '20',
        }

    def test_operator_submits_and_controller_approves_linked_corrections(self):
        """Проверяет раздельное согласование и связь подтверждённой разницы с корректировкой."""
        url, data = self.open_form()
        result = self.client.post(url, data)
        sheet = InventorySheet.objects.get()
        detail = reverse('inventory_sheets:detail', args=[sheet.pk])
        review = reverse('inventory_sheets:approve', args=[sheet.pk])
        self.assertRedirects(result, detail)
        self.assertContains(self.client.get(detail), 'На проверке')
        self.first.refresh_from_db()
        self.assertEqual((self.first.actual_balance, self.first.inventory), (10, 10))
        self.assertFalse(StockAdjustment.objects.exists())
        self.assertEqual(self.client.post(review, {'decision': 'approve'}).status_code, 403)
        self.client.force_login(self.controller)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertRedirects(self.client.post(review, {'decision': 'approve', 'note': 'Сверено'}), detail)
        self.assertContains(self.client.get(detail), 'Подтверждена')
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual((self.first.actual_balance, self.first.inventory), (Decimal('9.75'), Decimal('9.75')))
        self.assertEqual(self.first.inventory_book_balance, 10)
        self.assertEqual((self.second.actual_balance, self.second.inventory), (20, 20))
        correction = StockAdjustment.objects.get()
        self.assertEqual((correction.actor, correction.before, correction.after), (self.controller, 10, Decimal('9.75')))
        self.assertEqual(sheet.lines.get(count__stock=self.first).adjustment, correction)
        self.assertIsNone(sheet.lines.get(count__stock=self.second).adjustment)
        self.assertContains(self.client.post(review, {'decision': 'approve'}), 'Ведомость уже проверена')
        self.assertEqual(StockAdjustment.objects.count(), 1)

    def test_stale_form_and_wrong_warehouse_are_rejected(self):
        """Проверяет отказ при устаревшем снимке, дублировании и выборе другого склада."""
        url, data = self.open_form()
        result = self.client.post(url, {**data, 'form-1-stock': self.other.pk})
        self.assertEqual(result.status_code, 200)
        self.assertIn('stock', result.context['lines'].forms[1].errors)
        duplicate = self.client.post(url, {**data, 'form-1-stock': self.first.pk})
        self.assertContains(duplicate, 'Каждый остаток можно указать только один раз')
        self.first.actual_balance = 8
        self.first.save(update_fields=['actual_balance'])
        self.assertContains(self.client.post(url, data), 'Остатки изменились после открытия формы')
        self.assertFalse(InventorySheet.objects.exists())
        self.assertFalse(InventoryCount.objects.exists())

    def test_stale_sheet_blocks_entire_approval_and_rejection_preserves_summary(self):
        """Проверяет откат согласования и сохранение прежнего пересчёта после отклонения."""
        sheet = self.make_sheet(second_quantity='18')
        self.second.actual_balance = 21
        self.second.save(update_fields=['actual_balance'])
        with self.assertRaisesMessage(ValidationError, 'изменились после пересчёта'):
            review_inventory_sheet(sheet, actor=self.controller, approve=True)
        self.assertFalse(StockAdjustment.objects.exists())
        self.first.refresh_from_db()
        self.assertEqual((self.first.actual_balance, self.first.inventory), (10, 10))
        with self.assertRaisesMessage(ValidationError, 'Укажите причину отклонения'):
            review_inventory_sheet(sheet, actor=self.controller, approve=False)
        self.assertEqual(
            review_inventory_sheet(sheet, actor=self.controller, approve=False, note='Остаток изменился').status,
            InventorySheet.Status.REJECTED,
        )
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual((self.first.inventory, self.second.inventory), (10, 20))
        self.assertEqual((self.first.actual_balance, self.second.actual_balance), (10, 21))
        self.assertEqual(InventoryCount.objects.count(), 2)

    def test_second_adjustment_failure_rolls_back_first(self):
        """Проверяет откат всей ведомости при ошибке записи второй корректировки."""
        sheet = self.make_sheet(second_quantity='18')

        def fail_second(stock, **kwargs):
            """Вызывает штатную запись для первой строки и имитирует ошибку второй."""
            if stock.pk == self.second.pk:
                raise ValidationError('Ошибка второй строки.')
            return record_manual_stock(stock, **kwargs)

        with patch('spares.inventory_sheet_services.record_manual_stock', side_effect=fail_second):
            with self.assertRaisesMessage(ValidationError, 'Ошибка второй строки'):
                review_inventory_sheet(sheet, actor=self.controller, approve=True)
        sheet.refresh_from_db()
        self.first.refresh_from_db()
        self.assertEqual(sheet.status, InventorySheet.Status.PENDING)
        self.assertEqual((self.first.actual_balance, self.first.inventory), (10, 10))
        self.assertFalse(StockAdjustment.objects.exists())

    def test_author_cannot_confirm_own_sheet_even_with_controller_permission(self):
        """Проверяет запрет самосогласования при наличии права контролёра."""
        sheet = self.make_sheet()
        self.grant(self.operator, 'approve_inventorysheet')
        self.client.force_login(self.operator)
        result = self.client.post(reverse('inventory_sheets:approve', args=[sheet.pk]), {'decision': 'approve'})
        self.assertContains(result, 'Автор ведомости не может проверить её самостоятельно')
        self.assertFalse(StockAdjustment.objects.exists())

    def test_reviewer_submits_and_applies_sheet_immediately(self):
        """Проверяет проведение новой ведомости проверяющего и аудит расхождения."""
        self.grant(self.controller, 'add_inventorysheet')
        url, data = self.open_form(actor=self.controller)
        result = self.client.post(url, data)
        sheet = InventorySheet.objects.get()
        self.assertRedirects(result, reverse('inventory_sheets:detail', args=[sheet.pk]))
        self.assertEqual(sheet.status, InventorySheet.Status.APPROVED)
        self.assertEqual((sheet.created_by_id, sheet.reviewed_by_id), (self.controller.pk, self.controller.pk))
        self.assertEqual(StockAdjustment.objects.get().after, Decimal('9.75'))

    def test_operator_cannot_read_other_pending_sheet(self):
        """Скрывает чужие ожидающие ведомости от оператора до проведения."""
        another = get_user_model().objects.create_user('other-operator')
        sheet = submit_inventory_sheet(warehouse=self.warehouse, actor=another, entries=[(self.first, 8)])
        self.client.force_login(self.operator)
        url = reverse('inventory_sheets:detail', args=[sheet.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.controller)
        self.assertEqual(self.client.get(url).status_code, 200)
