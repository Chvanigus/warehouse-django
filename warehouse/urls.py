"""Главный маршрутизатор для складских разделов и панели администратора."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('management/', include('spares.warehouse_admin_urls')),
    path('requests/', include('spares.request_urls')),
    path('catalog/', include('spares.catalog_urls')),
    path('operations/', include('spares.operation_urls')),
    path('inventory/sheets/', include('spares.inventory_sheet_urls')),
    path('inventory/', include('spares.inventory_urls')),
    path('transfers/', include('spares.transfer_urls')),
    path('invoices/', include('spares.invoice_urls')),
    path('purchases/', include('spares.purchase_urls')),
    path('', include('spares.urls')),
]

# Обработчики ошибок
handler404 = 'core.views.page_not_found'
handler500 = 'core.views.server_error'
