"""Утилиты приложения reports."""


def calculate_total_company(income_report):
    months = [
        income_report.january, income_report.february, income_report.march, income_report.april,
        income_report.may, income_report.june, income_report.july, income_report.august,
        income_report.september, income_report.october, income_report.november, income_report.december
    ]

    total_company = sum(month for month in months if month is not None)
    return total_company
