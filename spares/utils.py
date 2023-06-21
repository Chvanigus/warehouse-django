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
