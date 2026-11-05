import importlib
import pkgutil

from .base import REGISTRY, Context, Strategy, build_strategy, register


def load_all() -> None:
    """Import every module in this package so @register runs."""
    for m in pkgutil.iter_modules(__path__):
        if m.name != "base":
            importlib.import_module(f"{__name__}.{m.name}")


load_all()

__all__ = ["REGISTRY", "Context", "Strategy", "build_strategy", "register", "load_all"]
