from django.urls import path

from .invoice_views import (
    InvoiceAddView,
    InvoiceCancelView,
    InvoiceDetailView,
    InvoiceListView,
    InvoiceTemplateView,
    InvoiceUploadView,
)


app_name = 'invoices'

urlpatterns = [
    path('', InvoiceListView.as_view(), name='list'),
    path('add/', InvoiceAddView.as_view(), name='add'),
    path('upload/', InvoiceUploadView.as_view(), name='upload'),
    path('template.xlsx', InvoiceTemplateView.as_view(), name='template'),
    path('<int:pk>/', InvoiceDetailView.as_view(), name='detail'),
    path('<int:pk>/cancel/', InvoiceCancelView.as_view(), name='cancel'),
]
