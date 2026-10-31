#!/usr/bin/env bash
# Start command for a host (Render, etc.): bring the database to the latest schema, then serve.
set -e
flask --app wsgi:app db upgrade
exec gunicorn wsgi:app --bind "0.0.0.0:${PORT:-8000}" --workers "${WEB_CONCURRENCY:-2}" --timeout 120
