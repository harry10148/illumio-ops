"""Alert output plugin base and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

_OUTPUT_REGISTRY: dict[str, type["AlertOutputPlugin"]] = {}

class AlertOutputPlugin(ABC):
    name: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.name:
            _OUTPUT_REGISTRY[cls.name] = cls

    def __init__(self, config_manager):
        self.cm = config_manager

    @abstractmethod
    def send(self, reporter, subject: str) -> dict:
        """Send the current alert payload for the given subject."""

def get_output_registry() -> dict[str, type[AlertOutputPlugin]]:
    return dict(_OUTPUT_REGISTRY)

def build_output_plugin(name: str, config_manager) -> AlertOutputPlugin:
    plugin_cls = _OUTPUT_REGISTRY.get(name)
    if not plugin_cls:
        raise KeyError(name)
    return plugin_cls(config_manager)
