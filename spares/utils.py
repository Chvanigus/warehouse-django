"""Утилиты приложения spares."""
import datetime


def get_month_name(date_obj: datetime) -> str:
    month = {
        1: "january",
        2: "february",
        3: "march",
        4: "april",
        5: "may",
        6: "june",
        7: "july",
        8: "august",
        9: "september",
        10: "october",
        11: "november",
        12: "december"
    }
    return month.get(date_obj.month)


def calculate_total_company(income_report):
    months = [
        income_report.january, income_report.february, income_report.march, income_report.april,
        income_report.may, income_report.june, income_report.july, income_report.august,
        income_report.september, income_report.october, income_report.november, income_report.december
    ]

    total_company = sum(month for month in months if month is not None)
    return total_company
