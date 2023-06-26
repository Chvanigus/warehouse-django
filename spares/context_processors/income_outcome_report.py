from collections import defaultdict

from spares.models import Receipt, WriteOff


def get_income_report():
    result = []

    companies = Receipt.objects.values('company__company_name').distinct()

    company_data = defaultdict(lambda: {'year_totals': defaultdict(lambda: defaultdict(float))})

    for row in Receipt.objects.all():
        company_id = row.company.company_name
        year = row.date.year
        month = row.date.month
        amount = float(row.amount)

        company_data[company_id]['year_totals'][year][month] += round(amount, 2)

    for company in companies:
        company_id = company['company__company_name']
        company_years = company_data[company_id]['year_totals']

        for year, month_totals in company_years.items():
            month_totals = defaultdict(float, month_totals)
            company_years[year] = month_totals

        for year, month_totals in company_years.items():
            company_data_entry = {
                'company': company_id,
                'year': year,
                'year_total': sum(month_totals.values()),
                'month_totals': dict(month_totals)
            }

            result.append(company_data_entry)

    print(result)

    return result


def get_outcome_report():
    result = []
    companies = Receipt.objects.values('company__company_name').distinct()
    company_data = defaultdict(lambda: {'year_totals': defaultdict(lambda: defaultdict(float))})

    for row in WriteOff.objects.all():
        company_id = row.company.company_name
        year = row.date.year
        month = row.date.month
        amount = float(row.total_amount)

        company_data[company_id]['year_totals'][year][month] += round(amount, 2)

    for company in companies:
        company_id = company['company__company_name']
        company_years = company_data[company_id]['year_totals']

        for year, month_totals in company_years.items():
            month_totals = defaultdict(float, month_totals)
            company_years[year] = month_totals

        for year, month_totals in company_years.items():
            company_data_entry = {
                'company': company_id,
                'year': year,
                'year_total': sum(month_totals.values()),
                'month_totals': dict(month_totals)
            }

            result.append(company_data_entry)

    print(result)

    return result
