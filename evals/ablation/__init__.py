"""Optional, removable ablation experiment extension."""


def create_ablation_router(*args, **kwargs):
    from .web_api import create_ablation_router as factory

    return factory(*args, **kwargs)


__all__ = ["create_ablation_router"]
