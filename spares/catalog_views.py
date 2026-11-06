"""Представления справочников и формы ручного изменения остатков."""

import re

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError, Q
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse
from django.utils.functional import cached_property
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from . import models
from .catalog_forms import ManualStockForm, StockCorrectionForm
from .permission_views import CurrentPermissionPostMixin
from .report_forms import StockMinimumFilterForm
from .stock_adjustments import save_manual_stock


CATALOGS = {
    'companies': (models.Company, ('name',)),
    'warehouses': (models.Warehouses, ('name',)),
    'spares': (models.Spares, ('name', 'sku')),
    'measures': (models.MeasureMeasurement, ('name',)),
    'contractors': (models.Contractors, ('name', 'contact', 'contact_name')),
    'workers': (models.Workers, ('name',)),
    'machines': (models.Machines, ('name',)),
    'trailers': (models.Trailers, ('name',)),
    'assignments': (models.MachineWorker, ('worker', 'machine', 'trailer')),
    'minimums': (models.StockMinimum, ('spare', 'company', 'warehouse', 'measure', 'minimum')),
}


def model_permission(model, action):
    """Возвращает код права Django для операции над моделью склада."""
    return f'spares.{action}_{model._meta.model_name}'


class CatalogIndexView(LoginRequiredMixin, TemplateView):
    """Выводит справочники, которые пользователю разрешено просматривать."""
    template_name = 'spares/catalog/index.html'

    def get_context_data(self, **kwargs):
        """Передаёт список доступных пользователю справочников."""
        context = super().get_context_data(**kwargs)
        context['catalogs'] = [
            (slug, model._meta.verbose_name_plural)
            for slug, (model, _) in CATALOGS.items()
            if self.request.user.has_perm(model_permission(model, 'view'))
        ]
        return context


class CatalogViewMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Связывает маршрут справочника с его моделью, полями и правами."""
    action = 'view'

    def dispatch(self, request, *args, **kwargs):
        """Подставляет модель по коду справочника перед проверкой доступа."""
        self.slug = kwargs['slug']
        try:
            self.model, self.fields = CATALOGS[self.slug]
        except KeyError as exc:
            raise Http404('Справочник не найден.') from exc
        return super().dispatch(request, *args, **kwargs)

    def get_permission_required(self):
        """Возвращает право, требуемое для текущей операции."""
        return (model_permission(self.model, self.action),)

    def get_success_url(self):
        """Выбирает доступную пользователю страницу возврата после операции."""
        if self.request.user.has_perm(model_permission(self.model, 'view')):
            return reverse('catalog:list', args=[self.slug])
        return reverse('catalog:index')

    def get_context_data(self, **kwargs):
        """Добавляет название справочника и адрес возврата."""
        context = super().get_context_data(**kwargs)
        context.update(
            slug=self.slug,
            catalog_name=self.model._meta.verbose_name_plural,
            back_url=self.get_success_url(),
        )
        return context


class CatalogListingMixin(CatalogViewMixin):
    """Добавляет пагинацию и разрешённые действия к спискам справочников."""

    paginate_by = 30

    def get_context_data(self, **kwargs):
        """Передаёт права добавления, изменения и удаления строк справочника."""
        context = super().get_context_data(**kwargs)
        context.update(
            can_add=self.request.user.has_perm(model_permission(self.model, 'add')),
            can_change=self.request.user.has_perm(model_permission(self.model, 'change')),
            can_delete=self.request.user.has_perm(model_permission(self.model, 'delete')),
        )
        return context


class CatalogListView(CatalogListingMixin, ListView):
    """Показывает постраничный список строк справочника с поиском."""

    template_name = 'spares/catalog/list.html'

    def get_queryset(self):
        """Ищет по названию, артикулу или связанным полям назначения техники."""
        query = re.escape(self.request.GET.get('q', '').strip())
        queryset = super().get_queryset()
        if self.model is models.MachineWorker:
            queryset = queryset.select_related('worker', 'machine', 'trailer').order_by('worker__name', 'pk')
            if query:
                queryset = queryset.filter(
                    Q(worker__name__iregex=query)
                    | Q(machine__name__iregex=query)
                    | Q(trailer__name__iregex=query)
                )
            return queryset
        queryset = queryset.order_by('name', 'pk')
        if query and self.model is models.Spares:
            return queryset.filter(Q(name__iregex=query) | Q(sku__iregex=query))
        return queryset.filter(name__iregex=query) if query else queryset

    def get_context_data(self, **kwargs):
        """Подготавливает колонки и действия для видимых строк справочника."""
        context = super().get_context_data(**kwargs)
        context.update(
            query=self.request.GET.get('q', ''),
            columns=[self.model._meta.get_field(field).verbose_name for field in self.fields],
            rows=[
                (item.pk, [getattr(item, field) for field in self.fields])
                for item in context['object_list']
            ],
        )
        return context


class StockMinimumListView(CatalogListingMixin, ListView):
    """Отображает правила минимума с количеством на складе и признаком дефицита."""
    template_name = 'spares/catalog/minimums.html'
    context_object_name = 'rules'

    @cached_property
    def filters(self):
        """Создаёт форму фильтров минимальных остатков из параметров GET."""
        return StockMinimumFilterForm(self.request.GET or None)

    def get_queryset(self):
        """Считает доступное количество и ограничивает список правилами пополнения."""
        rules = super().get_queryset().with_available().select_related(
            'spare', 'company', 'warehouse', 'measure',
        ).order_by('spare__name', 'warehouse__name', 'company__name', 'pk')
        rules = self.filters.filter_groups(rules)
        if self.filters.is_valid() and self.filters.cleaned_data['low']:
            return rules.below_minimum()
        return rules

    def get_context_data(self, **kwargs):
        """Передаёт фильтры в шаблон списка правил."""
        return super().get_context_data(filters=self.filters, **kwargs)


class CatalogFormMixin(CurrentPermissionPostMixin, CatalogViewMixin):
    """Обеспечивает общий шаблон и атомарное сохранение записей справочника."""
    template_name = 'spares/catalog/form.html'

    def get_context_data(self, **kwargs):
        """Передаёт заголовок формы в общий шаблон справочников."""
        return super().get_context_data(title=self.title, **kwargs)

    def form_valid(self, form):
        """Сохраняет запись и показывает уведомление об успехе."""
        response = super().form_valid(form)
        messages.success(self.request, 'Запись сохранена.')
        return response


class CatalogCreateView(CatalogFormMixin, CreateView):
    """Добавляет новую запись выбранного справочника при наличии права."""
    action = 'add'
    title = 'Добавление записи'


class CatalogUpdateView(CatalogFormMixin, UpdateView):
    """Изменяет существующую запись выбранного справочника."""
    action = 'change'
    title = 'Редактирование записи'


class CatalogDeleteView(CurrentPermissionPostMixin, CatalogViewMixin, DeleteView):
    """Подтверждает удаление записи и обрабатывает защищённые связи."""
    action = 'delete'
    template_name = 'spares/catalog/confirm_delete.html'
    http_method_names = ['get', 'head', 'post', 'options']

    def form_valid(self, form):
        """Удаляет запись либо объясняет, какие связи препятствуют удалению."""
        try:
            response = super().form_valid(form)
        except ProtectedError:
            form.add_error(None, 'Запись используется в других данных склада.')
            return self.form_invalid(form)
        messages.success(self.request, 'Запись удалена.')
        return response


class StockFormViewMixin(CurrentPermissionPostMixin, LoginRequiredMixin, PermissionRequiredMixin):
    """Сохраняет ручные изменения остатка с записью автора и причины."""
    model = models.Stock
    form_class = ManualStockForm
    template_name = 'spares/catalog/form.html'

    def get_success_url(self):
        """Возвращает пользователя к остаткам или списку справочников по его правам."""
        if self.request.user.has_perm('spares.view_stock'):
            return reverse('spares:stock_report')
        return reverse('catalog:index')

    def get_context_data(self, **kwargs):
        """Помечает форму справочника как форму остатка и задаёт заголовок."""
        return super().get_context_data(
            title=self.title, catalog_name='Остатки', back_url=self.get_success_url(),
            stock_form=True, **kwargs,
        )

    def form_valid(self, form):
        """Передаёт подготовленный остаток в сервис аудируемых изменений."""
        stock = form.save(commit=False)
        try:
            save_manual_stock(stock, actor=self.request.user, reason=form.cleaned_data['reason'])
        except ValidationError as exc:
            form.add_error(None, exc.messages)
            return self.form_invalid(form)
        self.object = stock
        messages.success(self.request, 'Остаток сохранён.')
        return HttpResponseRedirect(self.get_success_url())


class StockCreateView(StockFormViewMixin, CreateView):
    """Создаёт позицию с начальным остатком и при необходимости причиной ввода."""
    permission_required = 'spares.add_stock'
    title = 'Начальный остаток'


class StockUpdateView(StockFormViewMixin, UpdateView):
    """Редактирует количество и план остатка с проверкой его версии."""
    form_class = StockCorrectionForm
    permission_required = 'spares.change_stock'
    title = 'Корректировка остатка'

    def get_context_data(self, **kwargs):
        """Передаёт адрес перезагрузки формы после изменения остатка."""
        return super().get_context_data(reload_url=self.request.path, **kwargs)
