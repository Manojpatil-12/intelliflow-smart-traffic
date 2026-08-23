from django.core.checks import Warning, register


@register()
def check_model_registry(app_configs, **kwargs):
    errors = []
    try:
        from prediction.registry import registry
        if not registry._loaded:
            registry.load()
        if not registry.is_healthy():
            errors.append(Warning(
                "Model registry is not fully healthy.",
                hint=f"Load errors: {registry.load_errors}",
                id="prediction.W001",
            ))
    except Exception as e:
        errors.append(Warning(
            f"Could not check model registry: {e}",
            id="prediction.W002",
        ))
    return errors
