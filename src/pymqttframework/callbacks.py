from collections.abc import Callable, Mapping
import logging
from typing import Any, Protocol, runtime_checkable

from prometheus_client import CollectorRegistry


@runtime_checkable
class Callbacks(Protocol):
    def get_config(self) -> Mapping[str, Any]:
        """Provide application config"""
        ...

    def get_logger(self) -> logging.Logger:
        """Provide preconfigured logger"""
        ...

    def get_metrics_registry(self) -> CollectorRegistry:
        """Provide Prometheus metrics registry for custom metrics"""
        ...

    def add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: Callable | None = None,
        provide_automatic_options: bool | None = None,
        **options: Any,
    ) -> None:
        """Add custom url rules"""
        ...

    def publish_value_to_mqtt_topic(
        self,
        topic: str,
        value: str | bytes | bytearray | int | float,
        retain: bool = False,
    ) -> None:
        """Publish data to MQTT topic"""
        ...

    def subscribe_to_mqtt_topic(
        self, topic: str, callback: Callable[[str, str], None] | None = None
    ) -> None:
        """Subscribe to MQTT topic"""
        ...
