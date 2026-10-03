from collections.abc import Callable, Mapping
import logging
from typing import Any, Protocol, runtime_checkable

from prometheus_client import CollectorRegistry

from pymqttframework.read_only_dict import ReadOnlyDict


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


class CallbacksImpl(Callbacks):
    """Implementation of Callbacks protocol provided to client applications."""

    def __init__(self, framework: Any) -> None:
        self._framework = framework

    def get_config(self) -> Mapping[str, Any]:
        return ReadOnlyDict(self._framework._flask.config)

    def get_logger(self) -> logging.Logger:
        return self._framework._flask.logger

    def get_metrics_registry(self) -> CollectorRegistry:
        return self._framework._metrics_registry

    def add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: Callable | None = None,
        provide_automatic_options: bool | None = None,
        **options: Any,
    ) -> None:
        self._framework._flask.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=view_func,
            provide_automatic_options=provide_automatic_options,
            **options,
        )

    def publish_value_to_mqtt_topic(
        self,
        topic: str,
        value: str | bytes | bytearray | int | float,
        retain: bool = False,
    ) -> None:
        self._framework._publish_value_to_mqtt_topic(topic, value, retain=retain)

    def subscribe_to_mqtt_topic(
        self, topic: str, callback: Callable[[str, str], None] | None = None
    ) -> None:
        self._framework._subscribe_to_mqtt_topic(topic, callback)
