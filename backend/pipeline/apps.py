from django.apps import AppConfig


class PipelineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pipeline"

    def ready(self):
        # Importing the adapters package triggers @register on every shipped adapter,
        # so the registry is populated by the time a management command runs.
        from pipeline import adapters  # noqa: F401
