# The settings module from README.md ("Install"), as a deployment would
# mount it.
from .production import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, "plane_autojoin"]  # noqa: F405

LOGGING["loggers"]["plane_autojoin"] = {  # noqa: F405
    "level": "INFO",
    "handlers": ["console"],
    "propagate": False,
}
