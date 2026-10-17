from django.apps import AppConfig


class PlaneAutojoinConfig(AppConfig):
    # No models, so no migrations: Plane's migrator has nothing to do for us.
    name = "plane_autojoin"
    verbose_name = "Plane auto-join"

    def ready(self):
        # Imported here, not at module level: Plane's models are importable
        # only once the app registry is ready.
        from . import receivers

        receivers.connect()
