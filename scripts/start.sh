#!/usr/bin/env bash
# Start command for a host (Render, etc.): bring the database to the latest schema, then serve.
set -e
flask --app wsgi:app db upgrade
# The landing page's demo button needs the sample organization: build it once (does nothing if it exists; a failure must not stop the deploy).
if [ "${ENABLE_DEMO:-1}" = "1" ]; then
  flask --app wsgi:app ensure-demo || echo "demo seed failed (the /demo page will retry on first visit)"
fi
exec gunicorn wsgi:app --bind "0.0.0.0:${PORT:-8000}" --workers "${WEB_CONCURRENCY:-2}" --timeout 120
