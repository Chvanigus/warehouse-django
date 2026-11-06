"""Расчёт потребности в закупке и выгрузка списка по складам."""

from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from spares.models import Company, MeasureMeasurement, Spares, Stock, StockMinimum, Warehouses


class PurchaseListTests(TestCase):
    """Проверяет количество к заказу, фильтры и книгу XLSX."""

    @classmethod
    def setUpTestData(cls):
        """Создаёт нормативы двух складов и пользователя с правами просмотра."""
        cls.viewer = get_user_model().objects.create_user(username='purchaser')
        cls.viewer.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='spares', codename__in=['view_stock', 'view_stockminimum'],
        ))
        cls.warehouse = Warehouses.objects.create(name='Основной')
        cls.other_warehouse = Warehouses.objects.create(name='Запасной')
        cls.company = Company.objects.create(name='Фирма')
        cls.unit = MeasureMeasurement.objects.create(name='шт.')
        cls.spare = Spares.objects.create(name='Подшипник', sku='ПДШ-7')
        cls.rule = StockMinimum.objects.create(
            spare=cls.spare, warehouse=cls.warehouse, company=cls.company, measure=cls.unit, minimum=Decimal('6.25'),
        )
        cls.empty_rule = StockMinimum.objects.create(
            spare=cls.spare, warehouse=cls.other_warehouse, company=cls.company, measure=cls.unit, minimum=2,
        )

    def setUp(self):
        """Сохраняет адреса списка и выгрузки и входит под пользователем закупок."""
        self.list_url = reverse('purchases:list')
        self.export_url = reverse('purchases:export')
        self.client.force_login(self.viewer)

    def make_stock(self, balance, price, **overrides):
        """Создаёт ценовую партию с указанным остатком и реквизитами."""
        key = dict(spare=self.spare, warehouse=self.warehouse, company=self.company, measure=self.unit)
        return Stock.objects.create(**(key | overrides), actual_balance=Decimal(balance), price=price)

    def workbook(self, response):
        """Открывает успешную выгрузку XLSX и регистрирует закрытие книги."""
        self.assertEqual(response.status_code, 200)
        book = load_workbook(BytesIO(b''.join(response.streaming_content)))
        self.addCleanup(book.close)
        return book

    def test_shortages_group_lots_and_include_zero_stock(self):
        """Проверяет суммирование ценовых партий и расчёт для отсутствующего остатка."""
        self.make_stock('0.75', 10)
        self.make_stock('3.40', 11)
        self.make_stock('20.00', 11, measure=None)
        response = self.client.get(self.list_url)
        shortages = {rule.pk: rule for rule in response.context['shortages']}
        self.assertEqual(shortages[self.rule.pk].available, Decimal('4.15'))
        self.assertEqual(shortages[self.rule.pk].shortage, Decimal('2.10'))
        self.assertEqual(shortages[self.empty_rule.pk].available, 0)
        self.assertEqual(shortages[self.empty_rule.pk].shortage, 2)
        self.assertContains(response, 'warehouse-' + str(self.warehouse.pk))
        self.assertContains(response, 'warehouse-' + str(self.other_warehouse.pk))
        self.assertContains(response, 'К заказу')

    def test_exact_minimum_and_company_filter(self):
        """Проверяет исключение позиции ровно на минимуме и фильтрацию по фирме."""
        self.make_stock('6.25', 10)
        other_company = Company.objects.create(name='Вторая фирма')
        other_rule = StockMinimum.objects.create(
            spare=self.spare, warehouse=self.warehouse, company=other_company, measure=self.unit, minimum=3,
        )
        response = self.client.get(self.list_url, {'warehouse': self.warehouse.pk})
        self.assertEqual(list(response.context['shortages']), [other_rule])
        filtered = self.client.get(self.list_url, {'warehouse': self.warehouse.pk, 'company': self.company.pk})
        self.assertFalse(filtered.context['shortages'])

    def test_filtered_workbook_uses_same_values_and_text_cells(self):
        """Проверяет фильтры выгрузки и запись названий обычным текстом."""
        self.make_stock('4.15', 10)
        bad_name = Warehouses.objects.create(name='=Склад [/?]')
        bad_company = Company.objects.create(name='=1+1')
        formula_like = Spares.objects.create(name='=HYPERLINK("example","example")', sku='=1+2')
        StockMinimum.objects.create(spare=formula_like, warehouse=bad_name, company=bad_company, minimum=5)

        filtered_response = self.client.get(
            self.list_url, {'warehouse': self.warehouse.pk, 'q': 'пдш-7', 'page': 1},
        )
        self.assertContains(filtered_response, f'{self.export_url}?warehouse={self.warehouse.pk}&amp;q=')
        filtered_book = self.workbook(self.client.get(
            self.export_url, {'warehouse': self.warehouse.pk, 'q': 'пдш-7'},
        ))
        self.assertEqual(len(filtered_book.sheetnames), 1)
        self.assertEqual(list(filtered_book.active.values)[1], (
            'Основной', 'ПДШ-7', 'Подшипник', 'Фирма', 'шт.', 4.15, 6.25, 2.1,
        ))
        full_book = self.workbook(self.client.get(self.export_url))
        self.assertEqual(len(full_book.sheetnames), 3)
        formula_sheet = next(sheet for sheet in full_book if sheet['A2'].value == bad_name.name)
        self.assertEqual([cell.data_type for cell in formula_sheet[2][:4]], ['s'] * 4)
        self.assertEqual(formula_sheet['B2'].value, formula_like.sku)
        self.assertEqual(formula_sheet['C2'].value, formula_like.name)
        self.assertEqual(formula_sheet['D2'].value, bad_company.name)
        self.assertEqual(formula_sheet['H2'].data_type, 'n')
        self.assertEqual(formula_sheet['H2'].value, 5)

    def test_export_includes_all_matching_pages(self):
        """Проверяет включение всех отфильтрованных позиций вне зависимости от страницы."""
        for index in range(32):
            part = Spares.objects.create(name=f'Вкладыш {index:02d}')
            StockMinimum.objects.create(spare=part, warehouse=self.warehouse, company=self.company, minimum=1)
        params = {'warehouse': self.warehouse.pk, 'q': 'вкладыш'}
        response = self.client.get(self.list_url, params)
        self.assertTrue(response.context['is_paginated'])
        self.assertEqual(len(response.context['shortages']), 30)
        workbook = self.workbook(self.client.get(self.export_url, params | {'page': 2}))
        self.assertEqual(workbook.active.max_row, 33)

    def test_list_and_export_require_both_permissions(self):
        """Проверяет оба права доступа и обработку неверного фильтра."""
        self.assertContains(self.client.get(self.list_url, {'warehouse': 0}), 'Исправьте отмеченные поля')
        self.assertEqual(self.client.get(self.export_url, {'warehouse': 0}).status_code, 400)
        for code in ('view_stock', 'view_stockminimum'):
            user = get_user_model().objects.create_user(username=code)
            user.user_permissions.add(Permission.objects.get(content_type__app_label='spares', codename=code))
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.list_url).status_code, 403)
            self.assertEqual(self.client.get(self.export_url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.export_url).status_code, 302)
