FROM python:3.13.18-slim-bookworm

LABEL org.opencontainers.image.title="Warehouse Django" \
    org.opencontainers.image.version="1.0.0" \
    org.opencontainers.image.source="https://github.com/Chvanigus/warehouse-django"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 warehouse \
    && useradd --uid 10001 --gid warehouse --no-create-home warehouse \
    && install -d -o warehouse -g warehouse /app/staticfiles

COPY . .
USER warehouse
RUN DEBUG=1 python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["sh", "-ec", "python manage.py migrate --check && exec gunicorn --bind 0.0.0.0:8000 --workers \"${GUNICORN_WORKERS:-2}\" --threads \"${GUNICORN_THREADS:-4}\" --access-logfile - --error-logfile - warehouse.wsgi:application"]
