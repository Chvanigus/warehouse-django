from django.contrib import admin
from .forms import WriteOffForm, ReceiptForm
from .models import Spares, Warehouses, Company, Contractors, Workers, Machines, MachineWorker, MeasureMeasurement, \
    Trailers, Receipt, Stock, WriteOff, Movement


@admin.register(Spares)
class SparesAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Warehouses)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Contractors)
class ContractorsAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact', 'contact_name')
    search_fields = ('name', 'contact_name')


@admin.register(Workers)
class WorkersAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Machines)
class MachinesAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(MachineWorker)
class MachineWorkerAdmin(admin.ModelAdmin):
    list_display = ('worker', 'machine', 'trailer')
    autocomplete_fields = ('worker', 'machine', 'trailer')
    search_fields = ('worker', 'machine', 'trailer')


@admin.register(MeasureMeasurement)
class MeasureMeasurementAdmin(admin.ModelAdmin):
    list_display = ('name',)


@admin.register(Trailers)
class TrailersAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    form = ReceiptForm
    list_display = (
        'spare',
        'measure',
        'quantity',
        'price',
        'amount',
        'company',
        'date',
        'warehouse',
        'invoice_number',
        'contractor'
    )
    list_filter = (
        'date',
        'warehouse',
        'company',
        'contractor'
    )
    search_fields = ('spare__name',)
    autocomplete_fields = ('spare', 'company', 'contractor', 'warehouse')


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_filter = ('warehouse', 'company')
    list_display = (
        'spare',
        'actual_balance',
        'input_quantity',
        'output_quantity',
        'measure',
        'company',
        'warehouse',
        'price',
        'plan',
        'discrepancy',
        'inventory'
    )
    search_fields = ('spare__name',)
    readonly_fields = (
        'input_quantity',
        'output_quantity',
        'company',
        'discrepancy',
    )


@admin.register(WriteOff)
class WriteOffAdmin(admin.ModelAdmin):
    form = WriteOffForm
    list_display = (
        'spare',
        'measure',
        'quantity',
        'price',
        'total_amount',
        'company',
        'date',
        'worker',
        'machine',
        'trailer',
        'warehouse',
    )
    list_filter = (
        'warehouse',
        'company',
        'date',
    )

    search_fields = ('spare__name',)


@admin.register(Movement)
class MovementAdmin(admin.ModelAdmin):
    list_display = ('spare', 'from_warehouse', 'to_warehouse', 'timestamp')
    search_fields = ('spare__name',)
    list_filter = ('timestamp',)
