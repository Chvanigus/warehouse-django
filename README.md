# Склад запчастей

В веб-интерфейсе можно вести справочники, вводить начальные остатки, оформлять приход и списание, сверять остатки с инвентаризацией и просматривать отчёты. Для перемещения всей партии отредактируйте склад в её приходе. Успешное изменение появится в журнале перемещений. Если часть партии уже списана и остатка для переноса не хватает, приложение покажет ошибку.

## Локальный запуск

Нужен Python 3.13. Команды для PowerShell, из корня репозитория:

```powershell
python -m venv .venv
$env:DEBUG = '1'
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py createsuperuser
.venv/Scripts/python.exe manage.py runserver
```

Откройте [http://127.0.0.1:8000](http://127.0.0.1:8000) и войдите. В Linux и macOS используйте `.venv/bin/python` и `export DEBUG=1`.

В «Справочниках» заведите фирму, склад, запчасть и контрагента. Для списаний добавьте работника и запись в справочнике «Водители-транспорт-прицепы». Складская работа доступна с главной страницы. Для сотрудников создавайте отдельные учётные записи и назначайте им права Django на просмотр, добавление, изменение и удаление по нужным моделям. Управлять пользователями и группами можно в `/admin/`. Сотруднику достаточно выданных прав, чтобы работать в веб-интерфейсе без доступа к панели администратора.

## Локальные проверки

```powershell
$env:DEBUG = '1'
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe manage.py check
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
.venv/Scripts/python.exe manage.py test
```

## Развёртывание через Docker Compose

1. Скопируйте `.env.example` в `.env` и заполните `SECRET_KEY` уникальным значением. Сгенерировать его можно командой `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
2. Соберите образ и примените миграции. Для новой базы создайте первого пользователя.

   ```sh
   docker compose build
   docker compose run --rm web python manage.py migrate --noinput
   docker compose run --rm web python manage.py createsuperuser
   docker compose up -d
   ```

3. Откройте `http://127.0.0.1:8000` на сервере. Контейнер слушает на loopback хоста, порт можно сменить через `WAREHOUSE_PORT`.

Для доступа по сети настройте обратный прокси с TLS перед приложением. Укажите домен в `ALLOWED_HOSTS`, HTTPS-адрес с протоколом в `CSRF_TRUSTED_ORIGINS` и установите `WAREHOUSE_HTTPS=1`. Прокси должен передавать исходный `Host` и сам устанавливать `X-Forwarded-Proto`. Проверка с такой конфигурацией:

```sh
docker compose run --rm web python manage.py check --deploy --fail-level ERROR
```

Проверка может вывести рекомендации Django по HSTS для всех поддоменов и списку preload. Эти параметры зависят от настройки домена.

Статику собирает Docker при сборке. Gunicorn работает с одним процессом, SQLite хранится в именованном томе `warehouse-data`. Используйте один экземпляр приложения на этот том.

### Обновление существующего склада

Остановите старый экземпляр и сделайте резервную копию SQLite. Прогоните миграции на копии и проверьте остатки до обновления рабочей базы. Приложение сохраняет вручную введённые остатки. Если рабочая база уже в томе Compose, при остановленном сервисе копию можно получить командой `docker compose cp web:/data/db.sqlite3 ./warehouse-backup.sqlite3`.

Команда `python manage.py reconcile_stock` после миграции покажет возможные дубли остатков. После сверки с фактическими данными запустите `python manage.py reconcile_stock --merge ID_СОХРАНЯЕМОЙ_СТРОКИ ID_ДУБЛЯ …`, перечислив все строки одной группы. Команда суммирует приход, расход и фактический остаток. При конфликте планов или данных инвентаризации она потребует сначала сверить их. В Docker добавьте префикс `docker compose run --rm web` к командам управления.

Для установки существующей базы в новый том перед первым запуском приложения выполните на Linux из каталога проекта:

```sh
docker compose run --rm --user root \
  --volume "$(pwd)/warehouse-backup.sqlite3:/backup.sqlite3:ro" web \
  sh -c 'test ! -e /data/db.sqlite3 && install -o warehouse -g warehouse -m 600 /backup.sqlite3 /data/db.sqlite3'
```

Затем выполните `docker compose run --rm web python manage.py migrate --noinput` и `docker compose up -d`. При обновлении контейнера используйте прежний том. Команда `docker compose down -v` удаляет данные.
