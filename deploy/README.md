# Развёртывание склада

Конфигурация рассчитана на один Linux-сервер с Docker Compose и Nginx на хосте. PostgreSQL 17 работает в сервисе `db` и хранит данные в именованном томе `warehouse-postgres-data`; порт БД на хост не публикуется. Одноразовый сервис `init` ждёт готовности БД, применяет миграции и создаёт складские роли. Затем `web` запускает Gunicorn; по умолчанию используются два процесса по четыре потока, настройки меняются через `GUNICORN_WORKERS` и `GUNICORN_THREADS`. Статические файлы собраны в образ и отдаются через WhiteNoise.

Используйте постоянное имя Compose-проекта: оно определяет, какой том БД будет подключён. Смена `POSTGRES_DB`, `POSTGRES_USER` или `POSTGRES_PASSWORD` в `.env` не меняет уже созданную базу или пароль внутри непустого тома. Такие изменения выполняются отдельно в PostgreSQL и согласованно в конфигурации приложения.

Прежний SQLite-файл и том `warehouse-data` новая конфигурация не использует и автоматически не переносит. Сохраните их до отдельного переноса с проверкой документов, остатков, пользователей и прав. Не выполняйте `down -v` для рабочего проекта: эта команда удаляет PostgreSQL вместе с данными.

## Первый запуск

1. Скопируйте `.env.production.example` в `.env`, установите права `chmod 600 .env`. Заполните `WAREHOUSE_PUBLIC_HOST` доменом без схемы и порта, а `SECRET_KEY` и `POSTGRES_PASSWORD` — разными случайными значениями. Например, дважды выполните `docker run --rm python:3.13.18-slim-bookworm python -c 'import secrets; print(secrets.token_urlsafe(64))'`. Если порт 8000 занят, смените `WAREHOUSE_PORT` и порт upstream в Nginx. Не используйте `compose.dev.yaml` на сервере.
2. Настройте DNS и действующий TLS-сертификат. Подключите [пример Nginx](nginx.conf.example) в блок `http`, подставьте домен и пути к сертификату. Выполните `nginx -t` перед перезагрузкой. Прокси заменяет `X-Forwarded-Proto`, ограничивает размер запроса и частоту попыток входа. Gunicorn доступен на `127.0.0.1` хоста.
3. Выполните команды из корня проекта в одной сессии Bash. Пароль первого администратора задаётся в интерактивном приглашении.

```bash
dc() { docker compose -p warehouse -f compose.yaml -f compose.production.yaml "$@"; }
dc config --quiet
dc build --pull
dc up -d --wait db
dc run --rm --no-deps init python manage.py check --deploy --fail-level ERROR
dc up -d --wait
dc exec web python manage.py createsuperuser
dc ps -a
```

`init` должен завершиться с кодом 0, `db` и `web` — перейти в состояние healthy. При ошибке посмотрите `dc logs --tail=100 init web db`. `check --deploy` может показать рекомендации по распространению HSTS на поддомены и preload; эти параметры задаются отдельно для доменной зоны.

Проверьте готовность, вход и загрузку статики через публичный HTTPS: `dc exec -T web python deploy/smoke.py --base-url https://ВАШ_ДОМЕН`, подставив свой домен. Эта команда проверяет реальное TLS-соединение через прокси без подмены заголовков. Создайте обычного администратора склада через «Управление» и проверьте доступ под каждой ролью. Production-конфигурация требует `DEBUG=0`, HTTPS и корректный публичный домен для обоих сервисов приложения.

## Резервная копия PostgreSQL

Команды ниже предназначены для Bash и используют функцию `dc` из первого запуска. [`pg_dump`](https://www.postgresql.org/docs/17/app-pgdump.html) получает согласованный снимок при работающем приложении. Перед обновлением остановите `web`, чтобы исключить новые складские операции между снимком и миграцией. Каталог `backups/` исключён из Git и контекста сборки, но копии нужно дополнительно сохранять в закрытом хранилище вне сервера.

```bash
mkdir -p backups
snapshot="warehouse-$(date -u +%Y%m%dT%H%M%SZ).dump"
dc exec -T db sh -ec 'umask 077; pg_dump --format=custom --no-owner --no-acl --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --file="/tmp/$1"; pg_restore --list "/tmp/$1" >/dev/null' sh "$snapshot"
dc cp "db:/tmp/$snapshot" "backups/$snapshot"
chmod 600 "backups/$snapshot"
```

Продолжайте только после успешного завершения `pg_dump` и копирования. Проверка списка архива подтверждает его формат; полную пригодность подтверждает контрольное восстановление ниже. После сохранения и проверки внешней копии удалите промежуточный файл: `dc exec -T db rm -- "/tmp/$snapshot"`. Сохраните отдельно защищённую копию настроек и сведения о версии приложения. В PowerShell также используйте `pg_dump --file` внутри контейнера и `docker compose cp`, чтобы не пропускать бинарный архив через текстовое перенаправление.

## Обновление

Сначала зафиксируйте текущий коммит и сохраните рабочий образ под отдельным тегом:

```bash
previous_commit="$(git rev-parse HEAD)"
previous_image="warehouse-django:before-$(date -u +%Y%m%dT%H%M%SZ)"
docker image tag "$(docker inspect --format '{{.Image}}' "$(dc ps -q web)")" "$previous_image"
printf 'Commit: %s\nImage: %s\n' "$previous_commit" "$previous_image"
```

Перейдите на выбранную версию кода, задайте отдельный `WAREHOUSE_IMAGE` для новой сборки и соберите её, пока старое приложение продолжает работать. Перед применением миграций проверьте их на восстановленной копии по следующему разделу.

```bash
export WAREHOUSE_IMAGE="warehouse-django:$(git rev-parse --short HEAD)"
dc build --pull
dc stop web
```

Создайте резервную копию командами выше. Затем выполните:

```bash
dc run --rm --no-deps init python manage.py check --deploy --fail-level ERROR
dc run --rm --no-deps init
dc up -d --wait
```

Явный запуск `init` применяет миграции и обновляет роли для новой версии. Убедитесь, что публичный healthcheck и основные складские операции работают. Сохраните выбранный `WAREHOUSE_IMAGE` в `.env`, чтобы следующие команды и новая SSH-сессия использовали тот же образ. При ошибке миграции оставьте `web` остановленным до исправления или восстановления копии в новый том с прежним образом. Простое переключение образа не отменяет миграции БД.

## Контрольное восстановление и откат

Для восстановления используется [`pg_restore`](https://www.postgresql.org/docs/17/app-pgrestore.html). Для каждой проверки выбирайте новое имя проекта: восстановление выполняется в пустую БД, созданную Docker в отдельном томе. Пример использует текущий образ; для проверки отката задайте `WAREHOUSE_IMAGE` сохранённым тегом прежнего образа и используйте соответствующую ему версию Compose-конфигурации. Не запускайте сборку поверх сохранённого тега.

```bash
restore_project="warehouse-restore-$(date -u +%Y%m%dT%H%M%SZ)"
restore() { WAREHOUSE_PORT=18084 docker compose -p "$restore_project" -f compose.yaml -f compose.production.yaml "$@"; }
restore up -d --wait db
restore cp "backups/$snapshot" "db:/tmp/$snapshot"
restore exec -T db sh -ec 'pg_restore --exit-on-error --single-transaction --no-owner --no-acl --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" "/tmp/$1"' sh "$snapshot"
restore run --rm --no-deps web python manage.py migrate --check
restore up -d --wait --no-deps web
```

`--no-deps` здесь позволяет проверить исходную схему копии без автоматического запуска миграций через `init`. Если проверяется обновление и есть ожидаемые новые миграции, выполните `restore run --rm --no-deps init`, затем снова `migrate --check` и запуск `web`. Сравните пользователей, документы, остатки и заявки. Для проверки готовности, входа и статики на восстановленном экземпляре выполните `restore exec -T web python deploy/smoke.py --host ВАШ_ДОМЕН --forwarded-https`, подставив домен из `.env`. Эта проверка идёт на loopback внутри контейнера с заголовком доверенного прокси; внешний HTTPS она не подтверждает. Для проверки через браузер настройте отдельный HTTPS upstream на порт 18084.

При откате подключите Nginx к проверенному экземпляру со старым образом и восстановленной БД. Сохраните исходный рабочий том для расследования; не восстанавливайте архив поверх него. После завершения репетиции `restore down` остановит стенд и сохранит его том. Удалять том можно только после явной проверки, что выбран именно тестовый проект.

При переходе с ранних версий `python manage.py reconcile_stock` показывает возможные дубли остатков. После сверки с фактическими данными можно явно объединить одну группу командой `python manage.py reconcile_stock --merge ID_СОХРАНЯЕМОЙ_СТРОКИ ID_ДУБЛЯ …`. Документы с будущей датой, проведённые до появления проверки даты, сохраняются с отметкой в журнале.
