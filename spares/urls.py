from django.urls import path
from spares.views import WarehouseMainView, MachineReportView, TrailerReportView, StockReportView

app_name = 'spares'

urlpatterns = [
    path('', WarehouseMainView.as_view(), name='warehouse_main'),
    path('machine_report/', MachineReportView.as_view(), name='machine_report'),
    path('trailer_report/', TrailerReportView.as_view(), name='trailer_report'),
    path('stock_report/', StockReportView.as_view(), name='stock_report'),
]
