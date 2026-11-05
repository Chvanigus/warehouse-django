"""URL configuration for warehouse project."""
from django.contrib import admin
from django.urls import path, include
from spares import urls as spares_urls

urlpatterns = [
    path('admin/', admin.site.urls),
    path('catalog/', include('spares.catalog_urls')),
    path('operations/', include('spares.operation_urls')),
    path('inventory/', include('spares.inventory_urls')),
    path('transfers/', include('spares.transfer_urls')),
    path('invoices/', include('spares.invoice_urls')),
    path('', include(spares_urls)),
]

# Обработчики ошибок
handler404 = 'core.views.page_not_found'
handler500 = 'core.views.server_error'
