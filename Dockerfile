FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Populates STATIC_ROOT inside the image so WhiteNoise has something to serve
# once the container runs with DEBUG=0 (Gunicorn), where Django no longer
# serves static files itself the way it does under `runserver` + DEBUG=1.
# Safe at build time: settings.py has defaults for DJANGO_SECRET_KEY and the
# DB settings, and collectstatic never opens a database connection.
RUN python manage.py collectstatic --noinput

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
