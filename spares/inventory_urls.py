from django.urls import path

from .inventory_views import InventoryCountCreateView, InventoryCountListView

app_name = 'inventory'

urlpatterns = [
    path('', InventoryCountListView.as_view(), name='list'),
    path('<int:pk>/count/', InventoryCountCreateView.as_view(), name='add'),
]
