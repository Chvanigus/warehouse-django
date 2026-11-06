"""Годовые отчёты по суммам прихода и расхода в разрезе фирм."""

from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import ExtractMonth, ExtractYear

from spares.models import Receipt, WriteOff


ZERO = Decimal('0.00')


def _annual_report(model, amount_field):
    """Суммировать проведённые операции по месяцам и годам, заполнив пустые месяцы нулями."""
    rows = (
        model.objects.filter(cancelled_at__isnull=True)
        .annotate(year=ExtractYear('date'), month=ExtractMonth('date'))
        .values('company_id', 'company__name', 'year', 'month')
        .annotate(amount=Sum(amount_field))
        .order_by('company__name', 'company_id', '-year', 'month')
    )
    company_years = {}
    for row in rows:
        company_year = (row['company_id'], row['year'])
        summary = company_years.setdefault(company_year, {
            'company': row['company__name'],
            'year': row['year'],
            'month_totals': [ZERO] * 12,
            'year_total': ZERO,
        })
        amount = row['amount'].quantize(ZERO)
        summary['month_totals'][row['month'] - 1] = amount
        summary['year_total'] += amount
    return list(company_years.values())


def get_income_report():
    """Вернуть годовые отчёты по суммам приходов."""
    return _annual_report(Receipt, 'amount')


def get_outcome_report():
    """Вернуть годовые отчёты по суммам расходов."""
    return _annual_report(WriteOff, 'total_amount')
