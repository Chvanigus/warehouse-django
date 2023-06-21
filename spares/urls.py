from django.urls import path
from spares.views import WarehouseMainView, MachineReportView

app_name = 'spares'

urlpatterns = [
    path('', WarehouseMainView.as_view(), name='warehouse_main'),
    path('machine_report/', MachineReportView.as_view(), name='machine_report')
]
