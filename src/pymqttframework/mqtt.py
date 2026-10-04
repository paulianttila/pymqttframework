from collections.abc import Callable
import logging
from typing import Any

from flask import Flask
from flask_mqtt import Mqtt

from pymqttframework.app import App
from pymqttframework.metrics import FrameworkMetrics


class MqttManager:
    """Manages the MQTT client, subscriptions, message routing, and publishing."""

    TOPIC_STATUS = "status"
    TOPIC_UPDATE_NOW = "updateNow"
    TOPIC_SET_LOG_LEVEL = "setLogLevel"

    def __init__(
        self,
        logger: logging.Logger,
        metrics: FrameworkMetrics,
        trace_log_func: Callable[..., None] | None = None,
    ) -> None:
        self._mqtt = Mqtt()
        self._logger = logger
        self._metrics = metrics
        self._trace_log = trace_log_func or (lambda msg, *a, **kw: None)
        self._callbacks: dict[str, Callable[[str, str], None]] = {}
        self._app_getter: Callable[[], App | None] = lambda: None
        self._get_prefix_func: Callable[[], str] = lambda: ""
        self._update_now_func: Callable[[], None] = lambda: None
        self._set_log_level_func: Callable[[str], None] = lambda lvl: None

        @self._mqtt.on_log()
        def handle_logging(client, userdata, level, buf) -> None:
            self._trace_log(f"MQTT: {buf}")

        self._mqtt.on_connect()(self._handle_connect)
        self._mqtt.on_message()(self._handle_message)

    def init_app(self, flask_app: Flask) -> None:
        """Initialize Flask-MQTT extension."""
        self._mqtt.init_app(flask_app)

    def setup_handlers(
        self,
        app_getter: Callable[[], App | None],
        get_prefix_func: Callable[[], str],
        update_now_func: Callable[[], None],
        set_log_level_func: Callable[[str], None],
    ) -> None:
        """Register handler dependencies."""
        self._app_getter = app_getter
        self._get_prefix_func = get_prefix_func
        self._update_now_func = update_now_func
        self._set_log_level_func = set_log_level_func

    def _handle_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        prefix = self._get_prefix_func()
        self.publish(self.TOPIC_STATUS, "online", prefix=prefix, retain=True)
        self.subscribe(self.TOPIC_UPDATE_NOW, prefix=prefix)
        self.subscribe(self.TOPIC_SET_LOG_LEVEL, prefix=prefix)
        app = self._app_getter()
        if app is not None:
            try:
                app.subscribe_to_mqtt_topics()
            except Exception as e:
                self._logger.exception(f"Error occurred during topic subscription: {e}")

    def _handle_message(self, client: Any, userdata: Any, message: Any) -> None:
        self._metrics.mqtt_messages_received.inc()
        try:
            data = str(message.payload.decode("utf-8"))
        except UnicodeDecodeError:
            self._logger.warning(
                f"MQTT message on topic {message.topic} could not be decoded as UTF-8: {message.payload!r}"
            )
            return

        self._logger.debug(
            f"MQTT message received: topic={message.topic}, "
            f"qos={message.qos}, data: {data}"
        )
        prefix = self._get_prefix_func()
        topic = message.topic.removeprefix(prefix)

        try:
            if topic == self.TOPIC_UPDATE_NOW and data.lower() in {
                "yes",
                "true",
                "1",
            }:
                self._update_now_func()
            elif topic == self.TOPIC_SET_LOG_LEVEL and data.upper() in {
                "TRACE",
                "DEBUG",
                "INFO",
                "WARNING",
                "ERROR",
                "CRITICAL",
            }:
                self._set_log_level_func(data.upper())
            else:
                if callback := self._callbacks.get(topic):
                    callback(topic, data)
                else:
                    app = self._app_getter()
                    if app is not None:
                        app.mqtt_message_received(topic, data)
        except Exception as e:
            self._logger.exception(
                f"Error occurred while processing MQTT message, "
                f"topic={topic}, data: {data}: {e}"
            )

    def to_full_topic(self, topic: str, prefix: str) -> str:
        """Return fully qualified MQTT topic with prefix."""
        return prefix + topic

    def subscribe(
        self,
        topic: str,
        prefix: str,
        callback: Callable[[str, str], None] | None = None,
    ) -> None:
        """Subscribe to an MQTT topic with optional dedicated callback."""
        fulltopic = self.to_full_topic(topic, prefix)
        self._logger.debug(f"Subscribe to MQTT topic: {fulltopic}")
        self._mqtt.subscribe(fulltopic)
        if callback:
            self._callbacks[topic] = callback

    def publish(
        self,
        topic: str,
        value: str | bytes | bytearray | int | float,
        prefix: str,
        retain: bool = False,
    ) -> None:
        """Publish payload to an MQTT topic."""
        fulltopic = self.to_full_topic(topic, prefix)
        self._logger.debug(f"Publish to topic '{fulltopic}' retain {retain}: {value!r}")
        try:
            res = self._mqtt.publish(fulltopic, value, retain=retain)
            result = getattr(res, "rc", res[0] if isinstance(res, tuple) else 0)
            if result != 0:
                self._logger.error(
                    f"Failed to publish to MQTT topic '{fulltopic}': MQTT error code {result}"
                )
                return
            self._metrics.mqtt_messages_sent.inc()
        except Exception as e:
            self._logger.error(f"Failed to publish to MQTT topic '{fulltopic}': {e}")

    def unsubscribe_all(self) -> None:
        """Unsubscribe all topics."""
        self._mqtt.unsubscribe_all()

    def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        self._mqtt._disconnect()
