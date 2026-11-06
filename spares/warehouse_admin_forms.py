"""Формы управления учётными записями сотрудников склада."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm
from django.contrib.auth.models import Group

from .warehouse_roles import WAREHOUSE_ROLE_LABELS, WAREHOUSE_ROLE_PERMISSIONS, WAREHOUSE_ROLES


ROLE_CHOICES = tuple((key, WAREHOUSE_ROLE_LABELS[key]) for key in WAREHOUSE_ROLES)
ROLE_BY_GROUP = {name: key for key, name in WAREHOUSE_ROLES.items()}


def safe_warehouse_groups():
    """Возвращает складские группы, в которых нет дополнительных полномочий."""
    groups = Group.objects.filter(name__in=ROLE_BY_GROUP).prefetch_related('permissions__content_type')
    result = {}
    for group in groups:
        role = ROLE_BY_GROUP[group.name]
        if all(
            permission.content_type.app_label == 'spares'
            and permission.codename in WAREHOUSE_ROLE_PERMISSIONS[role]
            for permission in group.permissions.all()
        ):
            result[role] = group
    return result


class WarehouseRoleField(forms.ChoiceField):
    """Принимает только настроенную складскую роль и возвращает её группу."""

    def __init__(self):
        """Подготавливает список штатных ролей."""
        super().__init__(label='Роль', choices=ROLE_CHOICES)

    def clean(self, value):
        """Проверяет ключ роли и безопасную конфигурацию группы в базе."""
        role = super().clean(value)
        group = safe_warehouse_groups().get(role)
        if group is None:
            raise forms.ValidationError('Роль недоступна. Проверьте её настройку у администратора системы.')
        return group


class WarehouseUserFilterForm(forms.Form):
    """Фильтрует сотрудников по имени, складской роли и состоянию доступа."""

    q = forms.CharField(
        label='Поиск', required=False, max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Логин или имя'}),
    )
    role = forms.ChoiceField(
        label='Роль', required=False, choices=(('', 'Все роли'), *ROLE_CHOICES),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    status = forms.ChoiceField(
        label='Статус', required=False, choices=(
            ('', 'Все статусы'), ('active', 'Активные'), ('inactive', 'Отключённые'),
        ),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )


class WarehouseUserCreateForm(UserCreationForm):
    """Создаёт обычного сотрудника и проверяет пароль средствами Django."""

    role = WarehouseRoleField()
    field_order = ('username', 'first_name', 'role', 'is_active', 'password1', 'password2')

    class Meta(UserCreationForm.Meta):
        """Ограничивает поля создания логином, именем и активностью."""

        model = get_user_model()
        fields = ('username', 'first_name', 'is_active')
        labels = {'username': 'Логин', 'first_name': 'Отображаемое имя', 'is_active': 'Учётная запись активна'}


class WarehouseUserUpdateForm(forms.ModelForm):
    """Меняет отображаемое имя, роль и доступ управляемого сотрудника."""

    role = WarehouseRoleField()
    field_order = ('first_name', 'role', 'is_active')

    class Meta:
        """Исключает логин, привилегии и прочие поля системной учётной записи."""

        model = get_user_model()
        fields = ('first_name', 'is_active')
        labels = {'first_name': 'Отображаемое имя', 'is_active': 'Учётная запись активна'}

    def __init__(self, *args, actor, role_key, **kwargs):
        """Подставляет текущую роль и защищает доступ самого администратора."""
        super().__init__(*args, **kwargs)
        self.initial['role'] = role_key
        if self.instance.pk == actor.pk:
            self.fields['role'].disabled = True
            self.fields['is_active'].disabled = True


class WarehouseUserPasswordForm(SetPasswordForm):
    """Задаёт новый пароль с проверкой совпадения и требований Django."""
