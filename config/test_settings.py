"""Ambiente de testes isolado; não usa o banco de produção nem senhas reais."""
import os

os.environ.setdefault("SECRET_KEY", "test-suite-only")

from .settings import *  # noqa: E402,F403

DEBUG = True
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.environ.get("TEST_DB_PATH", ":memory:")}}
if os.environ.get("TEST_DATABASE_URL"):
    DATABASES = {"default": dj_database_url.parse(os.environ["TEST_DATABASE_URL"])}  # noqa: F405
LOGGING = {"version": 1, "disable_existing_loggers": False,
           "loggers": {"django.request": {"handlers": [], "level": "CRITICAL", "propagate": False},
                       "axes": {"handlers": [], "level": "CRITICAL", "propagate": False}}}
AXES_ENABLED = False
