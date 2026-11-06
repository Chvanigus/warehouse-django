"""Маршруты просмотра списка закупок и выгрузки в XLSX."""

from django.urls import path

from .purchase_views import PurchaseExportView, PurchaseListView


app_name = 'purchases'

urlpatterns = [
    path('', PurchaseListView.as_view(), name='list'),
    path('export/', PurchaseExportView.as_view(), name='export'),
]
