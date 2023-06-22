from django.contrib import admin

from reports.models import IncomeReport, OutcomeReport


@admin.register(IncomeReport)
class IncomeReportsAdmin(admin.ModelAdmin):
    list_display = [
        'company',
        'total_company',
        'january',
        'february',
        'march',
        'april',
        'may',
        'june',
        'july',
        'august',
        'september',
        'october',
        'november',
        'december',
        'year'
    ]


@admin.register(OutcomeReport)
class OutcomeReportsAdmin(admin.ModelAdmin):
    list_display = [
        'company',
        'total_company',
        'january',
        'february',
        'march',
        'april',
        'may',
        'june',
        'july',
        'august',
        'september',
        'october',
        'november',
        'december',
        'year'
    ]
