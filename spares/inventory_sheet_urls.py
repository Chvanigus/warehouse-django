from django.urls import path

from .inventory_sheet_views import (
    InventorySheetAddView,
    InventorySheetDetailView,
    InventorySheetListView,
    InventorySheetReviewView,
)


app_name = 'inventory_sheets'

urlpatterns = [
    path('', InventorySheetListView.as_view(), name='list'),
    path('add/', InventorySheetAddView.as_view(), name='add'),
    path('<int:pk>/', InventorySheetDetailView.as_view(), name='detail'),
    path('<int:pk>/approve/', InventorySheetReviewView.as_view(), name='approve'),
]
