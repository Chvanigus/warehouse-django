from django.views.generic import TemplateView


class WarehouseMain(TemplateView):
    """Основной контроллер страницы со складами."""
    template_name = 'warehouse/warehouse_main.html'
