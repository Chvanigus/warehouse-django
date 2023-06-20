from django.contrib import admin
from django import forms
from .forms import WriteOffForm, SpareSelectWidget
from .models import *


@admin.register(Spares)
class SparesAdmin(admin.ModelAdmin):
    list_display = ['spare_name']


@admin.register(Warehouses)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ['warehouse_name']


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ['company_name']


@admin.register(Contractors)
class ContractorsAdmin(admin.ModelAdmin):
    list_display = ['contractor_name', 'contact', 'name']


@admin.register(Workers)
class WorkersAdmin(admin.ModelAdmin):
    list_display = ['worker_name']


@admin.register(Machines)
class MachinesAdmin(admin.ModelAdmin):
    list_display = ['machine_name']


@admin.register(MachineWorker)
class MachineWorkerAdmin(admin.ModelAdmin):
    list_display = ('worker', 'machine', 'trailer')


@admin.register(MeasureMeasurement)
class MeasureMeasurementAdmin(admin.ModelAdmin):
    list_display = ['measure_name']


@admin.register(Trailers)
class TrailersAdmin(admin.ModelAdmin):
    list_display = ['trailer_name']


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = (
        'spare',
        'measure',
        'company',
        'date',
        'warehouse',
        'quantity',
        'price',
        'amount',
        'invoice_number',
        'contractor'
    )
    list_filter = (
        'spare',
        'warehouse',
        'price',
        'company',
        'date'
    )
    readonly_fields = ['amount']
    formfield_overrides = {
        models.ForeignKey: {'widget': SpareSelectWidget},
    }


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_filter = ('spare', 'warehouse', 'price')
    list_display = (
        'spare',
        'measure',
        'company',
        'warehouse',
        'input_quantity',
        'output_quantity',
        'actual_balance',
        'price',
        'plan',
        'discrepancy',
        'inventory'
    )

    def has_change_permission(self, request, obj=None):
        return False


class WriteOffAdmin(admin.ModelAdmin):
    form = WriteOffForm
    list_display = (
        'spare',
        'measure',
        'company',
        'date',
        'worker',
        'machine',
        'trailer',
        'warehouse',
        'quantity',
        'price',
        'total_amount'
    )
    list_filter = (
        'spare',
        'warehouse',
        'price',
        'company',
        'date',
        'machine',
        'worker'
    )
    formfield_overrides = {
        forms.ModelChoiceField: {'widget': SpareSelectWidget}
    }


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

    def has_change_permission(self, request, obj=None):
        return False


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

    def has_change_permission(self, request, obj=None):
        return False


admin.site.register(IncomeReport, IncomeReportsAdmin)
admin.site.register(OutcomeReport, OutcomeReportsAdmin)
admin.site.register(WriteOff, WriteOffAdmin)
