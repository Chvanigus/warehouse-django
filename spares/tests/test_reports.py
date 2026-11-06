"""Отчёты склада, проверка параметров и переходы при входе."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from spares.models import Company, Contractors, Machines, Receipt, Spares, Stock, Trailers, Warehouses, Workers, WriteOff


class WarehouseReportTests(TestCase):
    """Проверяет права просмотра и корректность агрегации документов."""

    @classmethod
    def setUpTestData(cls):
        """Создаёт справочники, пользователей и документы для отчётных сценариев."""
        cls.reader = get_user_model().objects.create_user(username='reporter', password='warehouse-test-password')
        cls.reader.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='spares',
            codename__in=('view_receipt', 'view_writeoff', 'view_stock'),
        ))
        cls.contractor = Contractors.objects.create(name='Поставщик', contact='123', contact_name='Контакт')
        cls.machine = Machines.objects.create(name='Трактор')
        cls.trailer = Trailers.objects.create(name='Прицеп')
        cls.worker = Workers.objects.create(name='Механик')
        cls.stock_key = {
            'company': Company.objects.create(name='Компания'),
            'warehouse': Warehouses.objects.create(name='Склад'),
            'spare': Spares.objects.create(name='Фильтр'),
            'price': Decimal('0.10'),
        }

    def test_login_preserves_requested_report_and_logout_requires_post(self):
        """Проверяет возврат к выбранному отчёту после входа и выход только по POST."""
        report_url = reverse('spares:stock_report')
        login_url = reverse('spares:login')
        logout_url = reverse('spares:logout')
        self.assertRedirects(self.client.get(report_url), f'{login_url}?next={report_url}')
        self.assertContains(self.client.get(login_url, {'next': report_url}), 'Вход в складской учёт')
        response = self.client.post(login_url, {
            'username': 'reporter', 'password': 'warehouse-test-password', 'next': report_url,
        })
        self.assertRedirects(response, report_url)
        self.assertEqual(self.client.get(logout_url).status_code, 405)
        self.assertRedirects(self.client.post(logout_url), login_url)

    def test_report_permissions_and_landing_page(self):
        """Проверяет доступ к отчётам и отображение разрешённых разделов."""
        user = get_user_model().objects.create_user(username='unprivileged')
        self.client.force_login(user)
        dashboard = self.client.get(reverse('spares:warehouse_main'))
        self.assertContains(dashboard, 'Складской учёт')
        for route in ('stock_report', 'contractor_report', 'machine_report', 'trailer_report', 'income_outcome_report'):
            with self.subTest(route=route):
                url = reverse(f'spares:{route}')
                self.assertNotContains(dashboard, f'href="{url}"')
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_reports_render_without_filters_and_validate_bad_query_values(self):
        """Проверяет пустые формы отчётов и ошибки неверных параметров."""
        self.client.force_login(self.reader)
        for route, field in (
            ('contractor_report', 'contractors'),
            ('machine_report', 'machine'),
            ('trailer_report', 'trailers'),
        ):
            with self.subTest(route=route):
                url = reverse(f'spares:{route}')
                blank = self.client.get(url)
                self.assertFalse(blank.context['form'].is_bound)
                self.assertContains(blank, 'Сформировать отчёт')
                bad = self.client.get(url, {field: 'invalid', 'start-date': 'unexpected', 'end-date': '2024-15'})
                self.assertEqual(bad.status_code, 200)
                self.assertEqual(set(bad.context['form'].errors), {field, 'start_date', 'end_date'})
                self.assertFalse(bad.context['report_data'])

    def test_contractor_report_handles_month_boundaries_and_legacy_urls(self):
        """Проверяет границы отчётного месяца и разбор прежних параметров ссылки."""
        self.client.force_login(self.reader)
        for day in (date(2024, 2, 29), date(2024, 3, 1)):
            Receipt.objects.create(
                date=day, quantity=3, contractor=self.contractor, invoice_number='101', **self.stock_key,
            )
        url = reverse('spares:contractor_report')
        response = self.client.get(url, {
            'contractors': self.contractor.pk, 'start-date': 'Февраль 2024', 'end-date': '2024-02',
        })
        self.assertContains(response, 'value="2024-02"')
        self.assertContains(response, '29.02.2024')
        self.assertNotContains(response, '01.03.2024')
        self.assertEqual(response.context['total_amount'], Decimal('0.30'))
        reversed_range = self.client.get(url, {
            'contractors': self.contractor.pk, 'start-date': '2024-03', 'end-date': '2024-02',
        })
        self.assertIn('end_date', reversed_range.context['form'].errors)

    def test_outcome_includes_company_with_only_writeoffs(self):
        """Проверяет включение фирмы со списаниями при отсутствии приходов."""
        self.client.force_login(self.reader)
        Stock.objects.create(actual_balance=5, **self.stock_key)
        for month in (1, 2):
            WriteOff.objects.create(
                date=date(2024, month, 1), quantity=2, worker=self.worker,
                machine=self.machine, trailer=self.trailer, **self.stock_key,
            )
        response = self.client.get(reverse('spares:income_outcome_report'))
        self.assertContains(response, self.stock_key['company'].name)
        self.assertEqual(response.context['income_report'], [])
        summary, = response.context['outcome_report']
        self.assertEqual(summary['month_totals'][:3], [Decimal('0.20'), Decimal('0.20'), Decimal('0.00')])
        self.assertEqual(summary['year_total'], Decimal('0.40'))
        for route, field, selected in (
            ('machine_report', 'machine', self.machine),
            ('trailer_report', 'trailers', self.trailer),
        ):
            with self.subTest(route=route):
                filtered = self.client.get(reverse(f'spares:{route}'), {
                    field: selected.pk, 'start-date': '2024-02', 'end-date': '2024-02',
                })
                self.assertContains(filtered, selected.name)
                self.assertEqual(len(filtered.context['report_data']), 1)
                self.assertEqual(filtered.context['total_amount'], Decimal('0.20'))

    def test_detailed_report_displays_scope_and_document_links(self):
        """Проверяет карточки итогов, точную ссылку на приход и понятный пустой результат."""
        self.client.force_login(self.reader)
        receipt = Receipt.objects.create(
            date=date(2024, 2, 29), quantity=3, contractor=self.contractor, invoice_number='101', **self.stock_key,
        )
        url = reverse('spares:contractor_report')
        response = self.client.get(url, {
            'contractors': self.contractor.pk, 'start-date': '2024-02', 'end-date': '2024-02',
        })
        self.assertEqual(response.context['entry_count'], 1)
        self.assertEqual(response.context['report_subject'], self.contractor)
        self.assertEqual(response.context['report_period'], (date(2024, 2, 1), date(2024, 2, 29)))
        self.assertContains(response, f'{reverse("operations:receipts")}?entry={receipt.pk}')
        self.assertContains(response, 'class="no-export"')
        empty = self.client.get(url, {
            'contractors': self.contractor.pk, 'start-date': '2024-04', 'end-date': '2024-04',
        })
        self.assertContains(empty, 'За выбранный период записей нет.')
        self.assertNotContains(empty, '<table')

    def test_annual_report_filters_year_company_and_warehouse(self):
        """Проверяет общую сумму по всем трём фильтрам и ошибку некорректного года."""
        self.client.force_login(self.reader)
        other_company = Company.objects.create(name='Другая фирма')
        other_warehouse = Warehouses.objects.create(name='Другой склад')
        for day, overrides in (
            (date(2024, 2, 1), {}),
            (date(2023, 2, 1), {}),
            (date(2024, 2, 1), {'company': other_company}),
            (date(2024, 2, 1), {'warehouse': other_warehouse}),
        ):
            Receipt.objects.create(
                date=day, quantity=3, contractor=self.contractor, invoice_number='101',
                **{**self.stock_key, **overrides},
            )
        url = reverse('spares:income_outcome_report')
        response = self.client.get(url, {
            'year': 2024, 'company': self.stock_key['company'].pk, 'warehouse': self.stock_key['warehouse'].pk,
        })
        self.assertEqual(response.context['income_total'], Decimal('0.30'))
        self.assertEqual(response.context['outcome_total'], Decimal('0.00'))
        row, = response.context['income_report']
        self.assertEqual(row['year'], 2024)
        self.assertEqual(row['month_totals'][1], Decimal('0.30'))
        invalid = self.client.get(url, {'year': 10000})
        self.assertFalse(invalid.context['ready'])
        self.assertContains(invalid, 'Исправьте отмеченные параметры')

    def test_reports_ignore_future_and_cancelled_operations(self):
        """Проверяет, что исключённые операции не попадают ни в детали, ни в годовые суммы."""
        self.client.force_login(self.reader)
        today = timezone.localdate()
        for changes in ({}, {'date': today + timedelta(days=1)}, {'cancelled_at': timezone.now()}):
            receipt = Receipt.objects.create(
                date=today, quantity=2, contractor=self.contractor, invoice_number='101', **self.stock_key,
            )
            if changes:
                Receipt.objects.filter(pk=receipt.pk).update(**changes)
        response = self.client.get(reverse('spares:contractor_report'), {
            'contractors': self.contractor.pk, 'start-date': today.isoformat()[:7],
            'end-date': (today + timedelta(days=1)).isoformat()[:7],
        })
        self.assertEqual(response.context['entry_count'], 1)
        self.assertEqual(response.context['total_amount'], Decimal('0.20'))
        annual = self.client.get(reverse('spares:income_outcome_report'))
        self.assertEqual(annual.context['income_total'], Decimal('0.20'))
