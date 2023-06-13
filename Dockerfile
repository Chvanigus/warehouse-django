# Используйте базовый образ Python
FROM python:3.9

# Установка переменных окружения
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Установка зависимостей проекта
COPY requirements.txt .
RUN pip install -r requirements.txt

# Копирование кода проекта в Docker-контейнер
COPY . .

# Делаем миграции
RUN python manage.py makemigrations
RUN python manage.py migrate

# Запуск команды для запуска Django-приложения
CMD python manage.py runserver 0.0.0.0:8000