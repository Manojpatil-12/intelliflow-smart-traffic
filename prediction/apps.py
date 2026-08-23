from django.apps import AppConfig


class PredictionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "prediction"

    def ready(self):
        from prediction.registry import registry
        try:
            registry.load()
        except Exception as e:
            import logging
            logging.getLogger("prediction").error(
                "Registry failed to load at startup: %s", e
            )
