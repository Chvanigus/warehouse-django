"""Проверки управления складскими учётными записями и границ полномочий."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from spares.warehouse_admin_views import WarehouseUserUpdateView
from spares.warehouse_roles import WAREHOUSE_ROLES


OLD_PASSWORD = 'warehouse-strong-165'
NEW_PASSWORD = 'strong-unrelated-726'


class WarehouseUserManagementTests(TestCase):
    """Проверяет создание, защиту и изменение складских пользователей."""

    @classmethod
    def setUpTestData(cls):
        """Создаёт штатные роли, администратора и проверяемого сотрудника."""
        call_command('configure_warehouse_roles', stdout=StringIO())
        cls.groups = {key: Group.objects.get(name=name) for key, name in WAREHOUSE_ROLES.items()}
        cls.manage_permission = Permission.objects.get(
            content_type__app_label='spares', codename='manage_warehouse_users',
        )
        cls.actor = get_user_model().objects.create_user(username='administrator', password=OLD_PASSWORD)
        cls.actor.groups.add(cls.groups['admin'])
        cls.account = get_user_model().objects.create_user(
            username='warehouse-operator', first_name='Алексей Петров', password=OLD_PASSWORD,
        )
        cls.account.groups.add(cls.groups['operator'])

    def test_management_requires_its_own_permission(self):
        """Проверяет, что обычный сотрудник не может смотреть и изменять пользователей."""
        self.client.force_login(self.account)
        for route, args in (
            ('users', ()), ('add', ()), ('edit', (self.actor.pk,)), ('password', (self.actor.pk,)),
        ):
            with self.subTest(route=route):
                url = reverse(f'warehouse_admin:{route}', args=args)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_creates_regular_employee_with_exactly_one_role(self):
        """Проверяет назначение роли, хеширование пароля и игнорирование полей повышения прав."""
        self.client.force_login(self.actor)
        url = reverse('warehouse_admin:add')
        response = self.client.post(url, {
            'username': 'new-employee', 'first_name': 'Новый сотрудник',
            'role': 'reviewer', 'is_active': 'on', 'password1': NEW_PASSWORD, 'password2': NEW_PASSWORD,
            'is_staff': 'on', 'is_superuser': 'on', 'user_permissions': self.manage_permission.pk,
        })
        self.assertRedirects(response, reverse('warehouse_admin:users'))
        created = get_user_model().objects.get(username='new-employee')
        self.assertEqual(created.first_name, 'Новый сотрудник')
        self.assertTrue(created.check_password(NEW_PASSWORD))
        self.assertTrue(created.is_active)
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)
        self.assertFalse(created.user_permissions.exists())
        self.assertEqual(list(created.groups.all()), [self.groups['reviewer']])

    def test_creation_and_password_change_use_django_validators(self):
        """Проверяет отказ при слабом пароле и сохранение нового пароля сотрудника."""
        self.client.force_login(self.actor)
        response = self.client.post(reverse('warehouse_admin:add'), {
            'username': 'new-employee', 'role': 'operator',
            'password1': '123', 'password2': '123',
        })
        self.assertIn('password2', response.context['form'].errors)
        self.assertFalse(get_user_model().objects.filter(username='new-employee').exists())
        password_url = reverse('warehouse_admin:password', args=[self.account.pk])
        response = self.client.post(password_url, {'new_password1': '123', 'new_password2': '123'})
        self.assertIn('new_password2', response.context['form'].errors)
        self.account.refresh_from_db()
        self.assertTrue(self.account.check_password(OLD_PASSWORD))
        response = self.client.post(password_url, {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        self.assertRedirects(response, reverse('warehouse_admin:users'))
        self.account.refresh_from_db()
        self.assertTrue(self.account.check_password(NEW_PASSWORD))

    def test_updates_employee_and_filters_list(self):
        """Проверяет смену роли и доступа, а также кириллический поиск в отфильтрованном списке."""
        self.client.force_login(self.actor)
        response = self.client.post(reverse('warehouse_admin:edit', args=[self.account.pk]), {
            'first_name': 'Алексей Сидоров', 'role': 'reviewer', 'username': 'ignored',
        })
        self.assertRedirects(response, reverse('warehouse_admin:users'))
        self.account.refresh_from_db()
        self.assertEqual(self.account.username, 'warehouse-operator')
        self.assertEqual(self.account.first_name, 'Алексей Сидоров')
        self.assertFalse(self.account.is_active)
        self.assertEqual(list(self.account.groups.all()), [self.groups['reviewer']])
        response = self.client.get(reverse('warehouse_admin:users'), {
            'q': 'алексей', 'role': 'reviewer', 'status': 'inactive',
        })
        self.assertContains(response, self.account.username)
        self.assertEqual([account for account, _ in response.context['rows']], [self.account])

    def test_cannot_deactivate_or_demote_self(self):
        """Проверяет, что отправка формы собственной учётной записи сохраняет роль и доступ."""
        self.client.force_login(self.actor)
        response = self.client.post(reverse('warehouse_admin:edit', args=[self.actor.pk]), {
            'first_name': 'Своё имя', 'role': 'operator', 'is_active': '',
        })
        self.assertRedirects(response, reverse('warehouse_admin:users'))
        self.actor.refresh_from_db()
        self.assertEqual(self.actor.first_name, 'Своё имя')
        self.assertTrue(self.actor.is_active)
        self.assertEqual(list(self.actor.groups.all()), [self.groups['admin']])
        password_url = reverse('warehouse_admin:password', args=[self.actor.pk])
        response = self.client.post(password_url, {
            'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD,
        })
        self.assertRedirects(response, reverse('spares:password_change'))
        self.actor.refresh_from_db()
        self.assertTrue(self.actor.check_password(OLD_PASSWORD))

    def test_role_revocation_blocks_request_with_cached_permissions(self):
        """Проверяет, что ранее авторизованный запрос прекращается после смены роли."""
        stale_actor = get_user_model().objects.get(pk=self.actor.pk)
        self.assertTrue(stale_actor.has_perm('spares.manage_warehouse_users'))
        self.actor.groups.set([self.groups['operator']])
        url = reverse('warehouse_admin:edit', args=[self.account.pk])
        request = RequestFactory().post(url, {'first_name': 'Замена', 'role': 'admin'})
        request.user = stale_actor
        with self.assertRaises(PermissionDenied):
            WarehouseUserUpdateView.as_view()(request, pk=self.account.pk)
        self.account.refresh_from_db()
        self.assertEqual(self.account.first_name, 'Алексей Петров')
        self.assertTrue(self.account.is_active)
        self.assertEqual(list(self.account.groups.all()), [self.groups['operator']])

    def test_privileged_and_external_users_cannot_be_managed(self):
        """Проверяет исключение служебных, смешанных и наделённых прямыми правами аккаунтов."""
        self.client.force_login(self.actor)
        users = get_user_model().objects
        staff = users.create_user(username='protected-staff', is_staff=True)
        superuser = users.create_user(username='protected-superuser', is_superuser=True)
        direct = users.create_user(username='protected-direct')
        direct.user_permissions.add(self.manage_permission)
        foreign = users.create_user(username='protected-foreign')
        foreign.groups.add(Group.objects.create(name='Внешняя роль'))
        multiple = users.create_user(username='protected-multiple')
        multiple.groups.add(self.groups['reviewer'])
        unmanaged = users.create_user(username='protected-unmanaged')
        for account in (staff, superuser, direct, foreign, multiple):
            account.groups.add(self.groups['operator'])

        listing = self.client.get(reverse('warehouse_admin:users'))
        for account in (staff, superuser, direct, foreign, multiple, unmanaged):
            with self.subTest(account=account.username):
                self.assertNotContains(listing, account.username)
                for route in ('edit', 'password'):
                    url = reverse(f'warehouse_admin:{route}', args=[account.pk])
                    self.assertEqual(self.client.get(url).status_code, 404)
                    self.assertEqual(self.client.post(url, {}).status_code, 404)

    def test_group_with_extra_permissions_cannot_be_assigned_or_changed(self):
        """Проверяет защиту от складской группы с дополнительным системным правом."""
        self.client.force_login(self.actor)
        extra = Permission.objects.get(content_type__app_label='auth', codename='change_user')
        self.groups['operator'].permissions.add(extra)
        response = self.client.post(reverse('warehouse_admin:add'), {
            'username': 'new-employee', 'role': 'operator', 'password1': NEW_PASSWORD, 'password2': NEW_PASSWORD,
        })
        self.assertIn('role', response.context['form'].errors)
        self.assertFalse(get_user_model().objects.filter(username='new-employee').exists())
        self.assertEqual(self.client.get(reverse('warehouse_admin:edit', args=[self.account.pk])).status_code, 404)

    def test_incomplete_role_cannot_be_assigned(self):
        """Показывает сбой настройки роли и блокирует выдачу неполного доступа."""
        self.client.force_login(self.actor)
        self.groups['operator'].permissions.clear()
        listing = self.client.get(reverse('warehouse_admin:users'))
        self.assertContains(listing, 'Проверьте настройку складских ролей: Оператор.')
        response = self.client.post(reverse('warehouse_admin:add'), {
            'username': 'new-employee', 'role': 'operator', 'password1': NEW_PASSWORD, 'password2': NEW_PASSWORD,
        })
        self.assertIn('role', response.context['form'].errors)
        self.assertFalse(get_user_model().objects.filter(username='new-employee').exists())

    def test_employee_changes_own_password_with_current_password(self):
        """Проверяет вход, CSRF, текущий пароль, сохранение нового пароля и сеанса."""
        url = reverse('spares:password_change')
        self.assertRedirects(self.client.get(url), f"{reverse('spares:login')}?next={url}")
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.account)
        form = client.get(url)
        self.assertContains(form, 'Сменить пароль')
        self.assertIn('no-store', form.headers['Cache-Control'])
        values = {'old_password': OLD_PASSWORD, 'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD}
        self.assertEqual(client.post(url, values).status_code, 403)
        values['csrfmiddlewaretoken'] = client.cookies['csrftoken'].value
        invalid = client.post(url, {**values, 'old_password': 'incorrect'})
        self.assertIn('old_password', invalid.context['form'].errors)
        self.account.refresh_from_db()
        self.assertTrue(self.account.check_password(OLD_PASSWORD))
        changed = client.post(url, values, follow=True)
        self.assertRedirects(changed, reverse('spares:warehouse_main'))
        self.assertContains(changed, 'Пароль изменён.')
        self.account.refresh_from_db()
        self.assertTrue(self.account.check_password(NEW_PASSWORD))
        self.assertEqual(int(client.session['_auth_user_id']), self.account.pk)

    def test_forbidden_page_explains_access(self):
        """Показывает понятный отказ в доступе после входа без административной роли."""
        self.client.force_login(self.account)
        response = self.client.get(reverse('warehouse_admin:users'))
        self.assertContains(response, 'Доступ ограничен', status_code=403)
