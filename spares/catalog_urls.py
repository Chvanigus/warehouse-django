from django.urls import path

from . import catalog_views as views

app_name = 'catalog'

urlpatterns = [
    path('', views.CatalogIndexView.as_view(), name='index'),
    path('stock/add/', views.StockCreateView.as_view(), name='stock-add'),
    path('stock/<int:pk>/edit/', views.StockUpdateView.as_view(), name='stock-edit'),
    path('minimums/', views.StockMinimumListView.as_view(), {'slug': 'minimums'}, name='minimums'),
    path('<slug:slug>/', views.CatalogListView.as_view(), name='list'),
    path('<slug:slug>/add/', views.CatalogCreateView.as_view(), name='add'),
    path('<slug:slug>/<int:pk>/edit/', views.CatalogUpdateView.as_view(), name='edit'),
    path('<slug:slug>/<int:pk>/delete/', views.CatalogDeleteView.as_view(), name='delete'),
]
