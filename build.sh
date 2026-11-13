#!/usr/bin/env bash
# Executado pelo Render a cada deploy
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py ativar_rls
python manage.py criar_admin
