"""Утилиты приложения spares."""
import calendar
import datetime


def get_date_range(start_date_str: str, end_date_str: str) -> datetime:
    """Возвращает диапазон дат из datetime объектов."""
    month_names = {
        "Январь": 1,
        "Февраль": 2,
        "Март": 3,
        "Апрель": 4,
        "Май": 5,
        "Июнь": 6,
        "Июль": 7,
        "Август": 8,
        "Сентябрь": 9,
        "Октябрь": 10,
        "Ноябрь": 11,
        "Декабрь": 12
    }

    start_month_name, start_year_str = start_date_str.split()
    start_year = int(start_year_str)
    start_month = month_names[start_month_name]
    selected_start_month_year = datetime.datetime(start_year, start_month, 1)

    end_month_name, end_year_str = end_date_str.split()
    end_year = int(end_year_str)
    end_month = month_names[end_month_name]
    _, end_day = calendar.monthrange(int(end_year_str), end_month)
    selected_end_month_year = datetime.datetime(end_year, end_month, end_day)

    return selected_start_month_year, selected_end_month_year


def get_date_range_from_form(request) -> tuple or None:
    """Возвращает диапазон дат для фильтрации queryset по диапазону."""
    start_date_str = request.GET.get('start-date')
    end_date_str = request.GET.get('end-date')

    if start_date_str and end_date_str:
        start_date, end_date = get_date_range(start_date_str, end_date_str)
        return start_date, end_date
    else:
        return
