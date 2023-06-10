from django.urls import path
from spares.views import WarehouseMain

urlpatterns = [
    path('', WarehouseMain.as_view(), name='warehouse_main')
]
