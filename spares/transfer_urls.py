"""Маршруты журнала, проведения, просмотра и отмены перемещения."""

from django.urls import path

from .transfer_views import TransferCancelView, TransferCreateView, TransferDetailView, TransferListView

app_name = 'transfers'

urlpatterns = [
    path('', TransferListView.as_view(), name='list'),
    path('add/', TransferCreateView.as_view(), name='add'),
    path('<int:pk>/', TransferDetailView.as_view(), name='detail'),
    path('<int:pk>/cancel/', TransferCancelView.as_view(), name='cancel'),
]
