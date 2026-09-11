FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
RUN useradd --create-home --uid 10001 tileapp && \
    mkdir -p /app/staticfiles /app/media/imports && \
    chown -R tileapp:tileapp /app
COPY --chown=tileapp:tileapp . .
USER tileapp
RUN DJANGO_SECRET_KEY=collect-static-build-only-dummy-key-for-image-building-at-least-50-chars BUILDING_STATIC=1 python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
