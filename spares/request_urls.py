"""Маршруты просмотра и согласования складских заявок."""

from django.urls import path

from .request_views import StockRequestDetailView, StockRequestListView, StockRequestReviewView


app_name = 'stock_requests'
urlpatterns = [
    path('', StockRequestListView.as_view(), name='list'),
    path('<int:pk>/', StockRequestDetailView.as_view(), name='detail'),
    path('<int:pk>/approve/', StockRequestReviewView.as_view(approve=True), name='approve'),
    path('<int:pk>/reject/', StockRequestReviewView.as_view(), name='reject'),
]
