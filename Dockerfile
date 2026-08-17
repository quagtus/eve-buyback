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

# Set by BuildKit to the architecture being built for. Declared so it reaches the
# RUN below; dpkg is the fallback for the classic builder, which leaves it empty.
ARG TARGETARCH

# The asset name must match the build architecture. Hardcoding linux-x64 downloads
# and chmods successfully on an arm64 host, then dies at the --help below with
# "Exec format error" and exit code 126 — which reads like a corrupt download but
# is not one.
#
# The base image is Debian (glibc), so the plain builds are correct here, not
# the -musl ones.
#
# --fail makes an HTTP error a non-zero exit instead of writing the error body to
# the binary path; --retry rides out transient GitHub/CDN failures. The final
# --help proves the binary actually runs and pins any failure to this line.
RUN set -eu; \
    arch="${TARGETARCH:-$(dpkg --print-architecture)}"; \
    case "$arch" in \
      amd64) tw_arch=x64 ;; \
      arm64) tw_arch=arm64 ;; \
      *) echo "No Tailwind standalone build for architecture: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL --retry 3 --retry-delay 2 --retry-all-errors \
      -o /usr/local/bin/tailwindcss \
      "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-${tw_arch}"; \
    chmod +x /usr/local/bin/tailwindcss; \
    tailwindcss --help >/dev/null

COPY . .

RUN tailwindcss -i assets/css/input.css -o static/css/app.css --minify

# Populates STATIC_ROOT inside the image so WhiteNoise has something to serve
# once the container runs with DEBUG=0 (Gunicorn), where Django no longer
# serves static files itself the way it does under `runserver` + DEBUG=1.
# Safe at build time: settings.py has defaults for DJANGO_SECRET_KEY and the
# DB settings, and collectstatic never opens a database connection.
RUN python manage.py collectstatic --noinput

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
