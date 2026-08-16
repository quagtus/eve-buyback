FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gettext \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Tailwind standalone CLI — no Node required. Pinned; do not track "latest".
ARG TAILWIND_VERSION=v4.3.3
RUN curl -sL -o /usr/local/bin/tailwindcss \
      "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64" \
    && chmod +x /usr/local/bin/tailwindcss

COPY . .

RUN tailwindcss -i assets/css/input.css -o static/css/app.css --minify

# Populates STATIC_ROOT inside the image so WhiteNoise has something to serve
# once the container runs with DEBUG=0 (Gunicorn), where Django no longer
# serves static files itself the way it does under `runserver` + DEBUG=1.
# Safe at build time: settings.py has defaults for DJANGO_SECRET_KEY and the
# DB settings, and collectstatic never opens a database connection.
RUN python manage.py collectstatic --noinput

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
