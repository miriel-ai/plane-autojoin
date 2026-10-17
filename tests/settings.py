SECRET_KEY = "tests-only"
USE_TZ = True
INSTALLED_APPS = ["plane.db", "plane_autojoin"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
