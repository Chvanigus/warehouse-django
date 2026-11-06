"""Маршруты управления сотрудниками склада."""

from django.urls import path

from .warehouse_admin_views import (
    WarehouseUserCreateView,
    WarehouseUserListView,
    WarehouseUserPasswordView,
    WarehouseUserUpdateView,
)


app_name = 'warehouse_admin'

urlpatterns = [
    path('', WarehouseUserListView.as_view(), name='users'),
    path('users/add/', WarehouseUserCreateView.as_view(), name='add'),
    path('users/<int:pk>/edit/', WarehouseUserUpdateView.as_view(), name='edit'),
    path('users/<int:pk>/password/', WarehouseUserPasswordView.as_view(), name='password'),
]
