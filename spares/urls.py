from django.contrib.auth import views as auth_views
from django.urls import path

from spares.adjustment_views import StockAdjustmentListView
from spares.stock_card import StockCardView
from spares.views import (
    ContractorReportView,
    IncomeOutcomeReportView,
    MachineReportView,
    StockReportView,
    TrailerReportView,
    WarehouseMainView,
)


app_name = 'spares'

urlpatterns = [
    path('', WarehouseMainView.as_view(), name='warehouse_main'),
    path('login/', auth_views.LoginView.as_view(
        template_name='warehouse/login.html',
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='spares:login'), name='logout'),
    path('machine_report/', MachineReportView.as_view(), name='machine_report'),
    path('trailer_report/', TrailerReportView.as_view(), name='trailer_report'),
    path('stock_report/', StockReportView.as_view(), name='stock_report'),
    path('stock/adjustments/', StockAdjustmentListView.as_view(), name='stock_adjustments'),
    path('stock/<int:pk>/movements/', StockCardView.as_view(), name='stock_card'),
    path('contractor_report/', ContractorReportView.as_view(), name='contractor_report'),
    path('income_outcome_report/', IncomeOutcomeReportView.as_view(), name='income_outcome_report'),
]
