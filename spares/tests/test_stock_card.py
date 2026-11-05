from datetime import datetime, timedelta, timezone as utc_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from spares.invoice_services import post_receipt_invoice
from spares.models import Company, Contractors, MeasureMeasurement, Receipt, Spares, Stock, StockAdjustment, Warehouses, Workers, WriteOff
from spares.stock_adjustments import save_manual_stock
from spares.transfer_models import cancel_transfer, post_transfer


class StockCardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.reader = users.create_user('stock-card-reader')
        cls.staff = users.create_user('stock-card-operator')
        cls.no_stock = users.create_user('stock-card-no-stock')
        permissions = Permission.objects.filter(content_type__app_label='spares')
        cls.reader.user_permissions.add(permissions.get(codename='view_stock'))
        cls.no_stock.user_permissions.add(permissions.get(codename='view_receipt'))
        cls.staff.user_permissions.add(*permissions.filter(codename__in=(
            'view_stock', 'view_receipt', 'view_writeoff', 'view_stocktransfer', 'view_stockadjustment',
        )))
        today = timezone.localdate()
        day = today - timedelta(days=2)
        company = Company.objects.create(name='Фирма')
        warehouse = Warehouses.objects.create(name='Основной склад')
        destination = Warehouses.objects.create(name='Резервный склад')
        contractor = Contractors.objects.create(name='Поставщик')
        worker = Workers.objects.create(name='Получатель')
        spare = Spares.objects.create(name='Фильтр', sku='CARD-001')
        measure = MeasureMeasurement.objects.create(name='шт.')
        header = dict(company=company, warehouse=warehouse, contractor=contractor, date=day)
        part = dict(spare=spare, measure=measure, price=Decimal('40.50'))
        cls.invoice = post_receipt_invoice(
            actor=cls.staff, header={**header, 'number': 'КАРТ-01'}, lines=[{**part, 'quantity': Decimal('10')}],
        )
        cls.receipt = Receipt.objects.create(**header, **part, quantity=4, invoice_number='КАРТ-02')
        cls.receipt.cancel(actor=cls.staff, reason='Снять приход')
        cls.writeoff = WriteOff.objects.create(
            **part, company=company, warehouse=warehouse, date=day, worker=worker, quantity=Decimal('2.25'),
        )
        cls.writeoff.cancel(actor=cls.staff, reason='Вернуть расход')
        cls.stock = Stock.objects.get(**part, company=company, warehouse=warehouse)
        cls.transfer = post_transfer(
            source=cls.stock, destination=destination, quantity=Decimal('3.50'), date=day, actor=cls.staff,
        )
        cancel_transfer(cls.transfer, actor=cls.staff, reason='Вернуть на основной склад')
        cls.destination_stock = Stock.objects.get(**part, company=company, warehouse=destination)
        cls.stock.refresh_from_db()
        cls.stock.actual_balance = Decimal('8.75')
        save_manual_stock(cls.stock, actor=cls.staff, reason='Корректировка по ведомости')
        cls.adjustment = StockAdjustment.objects.get(stock=cls.stock)
        StockAdjustment.objects.filter(pk=cls.adjustment.pk).update(
            created_at=datetime(2026, 11, 4, 22, tzinfo=utc_timezone.utc),
        )
        for number, price, unit, firm, location in (
            ('ДРУГАЯ-ЦЕНА', 41, measure, company, warehouse),
            ('ДРУГАЯ-ЕДИНИЦА', part['price'], None, company, warehouse),
            ('ДРУГАЯ-ФИРМА', part['price'], measure, Company.objects.create(name='Фирма Б'), warehouse),
            ('ДРУГОЙ-СКЛАД', part['price'], measure, company, destination),
        ):
            Receipt.objects.create(
                spare=spare, quantity=1, price=price, measure=unit, company=firm, warehouse=location,
                date=day, contractor=contractor, invoice_number=number,
            )

    def setUp(self):
        self.url = reverse('spares:stock_card', args=[self.stock.pk])

    def test_history_keeps_exact_stock_key_and_signed_reversals(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertContains(response, 'Текущий остаток')
        self.assertContains(response, '8,75')
        entries = response.context['entries']
        self.assertEqual(len(entries), 8)
        totals = {}
        for row in entries:
            totals.setdefault(row['event_kind'], []).append(row['delta'])
        self.assertEqual(totals, {
            'receipt': [Decimal('4'), Decimal('10')],
            'receipt_cancel': [Decimal('-4')],
            'writeoff': [Decimal('-2.25')],
            'writeoff_cancel': [Decimal('2.25')],
            'transfer_out': [Decimal('-3.50')],
            'transfer_out_cancel': [Decimal('3.50')],
            'adjustment': [Decimal('-1.25')],
        })
        self.assertContains(response, reverse('invoices:detail', args=[self.invoice.pk]))
        self.assertContains(response, reverse('transfers:detail', args=[self.transfer.pk]))
        self.assertContains(response, reverse('operations:receipts', query={'entry': self.receipt.pk}))
        self.assertContains(response, reverse('operations:writeoffs', query={'entry': self.writeoff.pk}))
        source = reverse('spares:stock_adjustments', query={'stock': self.stock.pk, 'entry': self.adjustment.pk})
        self.assertIn(source, [entry['url'] for entry in entries])
        self.assertQuerySetEqual(self.client.get(source).context['entries'], [self.adjustment])

        destination_url = reverse('spares:stock_card', args=[self.destination_stock.pk])
        response = self.client.get(destination_url, {'kind': 'transfer'})
        self.assertEqual([row['delta'] for row in response.context['entries']], [Decimal('3.50')])
        response = self.client.get(destination_url, {'kind': 'cancel'})
        self.assertEqual([row['delta'] for row in response.context['entries']], [Decimal('-3.50')])

    def test_permissions_hide_unavailable_sources(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.no_stock)
        self.assertEqual(self.client.get(self.url).status_code, 403)

        self.client.force_login(self.reader)
        response = self.client.get(self.url)
        self.assertEqual(response.context['entries'], [])
        self.assertNotContains(response, 'Корректировка по ведомости')
        self.assertContains(self.client.get(reverse('spares:stock_report')), self.url)
        self.reader.user_permissions.add(Permission.objects.get(
            content_type__app_label='spares', codename='view_receipt',
        ))
        response = self.client.get(self.url)
        self.assertEqual({row['event_kind'] for row in response.context['entries']}, {'receipt', 'receipt_cancel'})
        self.assertNotContains(response, 'Получатель')

    def test_dates_and_pagination(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url, {'kind': 'adjustment', 'date_from': '2026-11-05', 'date_to': '2026-11-05'})
        self.assertEqual([entry['event_pk'] for entry in response.context['entries']], [self.adjustment.pk])
        self.assertContains(response, '05.11.2026 01:00')
        with patch('spares.stock_card.StockCardView.paginate_by', 1):
            response = self.client.get(self.url, {'kind': 'receipt'})
            self.assertEqual(response.context['page_obj'].paginator.count, 2)
            self.assertEqual([entry['event_pk'] for entry in response.context['entries']], [self.receipt.pk])
            self.assertContains(response, '?kind=receipt&amp;page=2')
            response = self.client.get(self.url, {'kind': 'receipt', 'page': 2})
            self.assertEqual([entry['invoice_pk'] for entry in response.context['entries']], [self.invoice.pk])
