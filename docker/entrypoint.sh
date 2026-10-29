#!/bin/sh
# Startskript des Containers: Datenbank aktualisieren, Admin anlegen, optional Beispieldaten laden.
set -e

python manage.py migrate --noinput
python manage.py ensure_admin

if [ "${DEMO_DATA:-0}" = "1" ]; then
    python manage.py seed_demo
fi

exec "$@"
