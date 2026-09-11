#!/usr/bin/env bash
set -euo pipefail
# Django creates and destroys a separate test_<POSTGRES_DB> database.
docker compose run --rm web python manage.py test production --noinput
