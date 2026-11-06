FROM python:3.13.18-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/db.sqlite3

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 warehouse \
    && useradd --uid 10001 --gid warehouse --no-create-home warehouse \
    && install -d -o warehouse -g warehouse /data /app/staticfiles

COPY . .
USER warehouse
RUN DEBUG=1 python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["sh", "-ec", "python manage.py migrate --check && exec gunicorn --bind 0.0.0.0:8000 --workers 1 --threads 4 --access-logfile - warehouse.wsgi:application"]
