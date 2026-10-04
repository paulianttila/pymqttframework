#!/usr/bin/env python3

from collections.abc import Callable
import importlib.metadata
import logging
import signal
import threading
from threading import Lock
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from flask import Flask, Response

from pymqttframework.app import App, TriggerSource
from pymqttframework.callbacks import CallbacksImpl
from pymqttframework.config import Config
from pymqttframework.config_loader import load_config
from pymqttframework.metrics import FrameworkMetrics
from pymqttframework.mqtt import MqttManager
from pymqttframework.scheduler import FrameworkScheduler, create_cron_trigger
from pymqttframework.server import WebServer

# current MQTT-Framework version
try:
    __version__ = importlib.metadata.version("pymqttframework")
except importlib.metadata.PackageNotFoundError:
    __version__ = "unknown"


class Framework:
    """Coordinator and application runner for pymqttframework."""

    TOPIC_STATUS = MqttManager.TOPIC_STATUS
    TOPIC_UPDATE_NOW = MqttManager.TOPIC_UPDATE_NOW
    TOPIC_SET_LOG_LEVEL = MqttManager.TOPIC_SET_LOG_LEVEL

    def __init__(self) -> None:
        self._TRACE_LOG_LEVEL = 5
        self._lock = Lock()
        self._stop_event = threading.Event()
        self._started = False

        self.__add_trace_level_to_logger()
        self._server = WebServer(trace_log_func=self._trace_log)
        self._metrics = FrameworkMetrics()
        self._scheduler = FrameworkScheduler(logger=self._flask.logger)
        self._mqtt = MqttManager(
            logger=self._flask.logger,
            metrics=self._metrics,
            trace_log_func=self._trace_log,
        )

        self._server.register_routes(
            healthy_check_func=self._rest_do_healthy_check_delegate,
            update_now_func=self._update_now,
            get_jobs_func=self._scheduler.get_jobs_info,
        )
        self._server.init_metrics(self._metrics.registry)

        self._mqtt.setup_handlers(
            app_getter=lambda: getattr(self, "_app", None),
            get_prefix_func=lambda: self._flask.config.get("MQTT_TOPIC_PREFIX", ""),
            update_now_func=lambda: self._update_now(),
            set_log_level_func=lambda lvl: self._set_log_level(lvl),
        )

    @property
    def _flask(self) -> Flask:
        return self._server.flask

    @property
    def _metrics_registry(self) -> Any:
        return self._metrics.registry

    @property
    def _mqtt_callbacks(self) -> dict[str, Callable[[str, str], None]]:
        return self._mqtt._callbacks

    def __add_trace_level_to_logger(self) -> None:
        logging.addLevelName(self._TRACE_LOG_LEVEL, "TRACE")

    def _trace_log(self, message: str, *args: Any, **kwargs: Any) -> None:
        if self._flask.logger.isEnabledFor(self._TRACE_LOG_LEVEL):
            self._flask.logger.log(self._TRACE_LOG_LEVEL, message, *args, **kwargs)

    def _signal_handler(self, sig: int, frame: Any) -> None:
        self._trace_log(f"Signal {signal.strsignal(sig)} received")
        self.shutdown()

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _load_config(self, config: Config, config_file: str | None = None) -> None:
        load_config(self._flask, config=config, config_file=config_file)

    def _create_cron_trigger(self) -> CronTrigger:
        cron_schedule = self._flask.config.get("UPDATE_CRON_SCHEDULE", "")
        return create_cron_trigger(cron_schedule)

    def _do_wait(self) -> None:
        self._trace_log("Start blocking")
        try:
            while not self._stop_event.is_set():
                if self._stop_event.wait(timeout=0.5):
                    break
        except KeyboardInterrupt:
            self._trace_log("KeyboardInterrupt received")
            self.shutdown()
        self._trace_log("End blocking")

    def _call_do_update(self, trigger_source: TriggerSource) -> None:
        @self._metrics.do_update.time()
        @self._metrics.do_update_exceptions.count_exceptions()
        def do():
            self._app.do_update(trigger_source)

        do()

    def _update_now(self) -> None:
        self._scheduler.trigger_update_now(
            update_interval=self._flask.config.get("UPDATE_INTERVAL", 0),
            update_callback=self._call_do_update,
        )

    def _rest_do_healthy_check_delegate(self) -> bool:
        if hasattr(self, "_app") and self._app is not None:
            return bool(self._app.do_healthy_check())
        return False

    def _rest_do_healthy_check(self) -> tuple[str, int]:
        if self._rest_do_healthy_check_delegate():
            self._flask.logger.debug("Healthy check OK")
            return "OK", 200
        self._flask.logger.warning("Healthy check FAIL")
        return "FAIL", 500

    def _rest_get_jobs(self) -> tuple[Response, int]:
        from flask import jsonify

        return jsonify({"jobs": self._scheduler.get_jobs_info()}), 200

    def _rest_update_now(self) -> tuple[str, int]:
        self._update_now()
        return "OK", 200

    def _to_full_mqtt_topic_name(self, topic: str) -> str:
        prefix = self._flask.config.get("MQTT_TOPIC_PREFIX", "")
        return self._mqtt.to_full_topic(topic, prefix)

    def _subscribe_to_mqtt_topic(
        self, topic: str, callback: Callable[[str, str], None] | None = None
    ) -> None:
        prefix = self._flask.config.get("MQTT_TOPIC_PREFIX", "")
        self._mqtt.subscribe(topic, prefix=prefix, callback=callback)

    def _publish_value_to_mqtt_topic(
        self,
        topic: str,
        value: str | bytes | bytearray | int | float,
        retain: bool = False,
    ) -> None:
        prefix = self._flask.config.get("MQTT_TOPIC_PREFIX", "")
        self._mqtt.publish(topic, value=value, prefix=prefix, retain=retain)

    def _mqtt_handle_connect(
        self, client: Any, userdata: Any, flags: Any, rc: int
    ) -> None:
        self._mqtt._handle_connect(client, userdata, flags, rc)

    def _mqtt_message_received(self, client: Any, userdata: Any, message: Any) -> None:
        self._mqtt._handle_message(client, userdata, message)

    def _set_log_level(self, level: str) -> None:
        self._flask.logger.setLevel(level)
        if level == "TRACE":
            logging.getLogger("werkzeug").setLevel(logging.DEBUG)
        else:
            logging.getLogger("werkzeug").setLevel(logging.ERROR)

    def _start_flask(self) -> None:
        host = self._flask.config.get("WEB_HOST", "0.0.0.0")
        port = self._flask.config.get("WEB_PORT", 5000)
        self._server.start(host=host, port=port)

    def _stop_flask(self) -> None:
        self._server.stop()

    def _start(
        self,
        app: App,
        config: Config,
        blocked: bool = False,
        config_file: str | None = None,
    ) -> int:
        if self._started:
            self._flask.logger.debug("Application already started")
            return 1

        self._flask.logger.info(
            f"{app.__class__.__name__} version {app.get_version()} starting, "
            f"framework version {__version__} "
        )

        self._load_config(config=config, config_file=config_file)
        self._server.init_limiter()

        if blocked:
            self._install_signal_handlers()

        self._app = app
        self._stop_event.clear()

        self._app.init(CallbacksImpl(self))
        self._mqtt.init_app(self._flask)

        self._scheduler.setup_jobs(
            update_interval=self._flask.config.get("UPDATE_INTERVAL", 0),
            cron_schedule=self._flask.config.get("UPDATE_CRON_SCHEDULE"),
            update_callback=self._call_do_update,
            initial_delay=self._flask.config.get("DELAY_BEFORE_FIRST_TRY", 5),
        )

        self._start_flask()
        self._scheduler.start()
        self._started = True
        return 0

    def _shutdown(self) -> None:
        try:
            self._app.stop()
        except Exception as e:
            self._flask.logger.exception(f"Error occurred during app.stop(): {e}")

        try:
            self._scheduler.shutdown(wait=True)
        except Exception as e:
            self._flask.logger.exception(f"Error shutting down scheduler: {e}")

        try:
            self._stop_flask()
        except Exception as e:
            self._flask.logger.exception(f"Error stopping web server: {e}")

        try:
            self._publish_value_to_mqtt_topic(self.TOPIC_STATUS, "offline", True)
        except Exception as e:
            self._flask.logger.exception(f"Error publishing offline status: {e}")

        try:
            self._mqtt.unsubscribe_all()
        except Exception as e:
            self._flask.logger.exception(f"Error unsubscribing MQTT topics: {e}")

        try:
            self._mqtt.disconnect()
        except Exception as e:
            self._flask.logger.exception(f"Error disconnecting MQTT: {e}")

        self._started = False

    def run(self, app: App, config: Config, config_file: str | None = None) -> int:
        """Start the application and block until stopped."""
        return self.start(app=app, config=config, blocked=True, config_file=config_file)

    def start(
        self,
        app: App,
        config: Config,
        blocked: bool = False,
        config_file: str | None = None,
    ) -> int:
        """Start the application."""
        with self._lock:
            if retval := self._start(
                app=app, config=config, blocked=blocked, config_file=config_file
            ):
                return retval
        if blocked:
            self._do_wait()
        return 0

    def shutdown(self) -> None:
        """Stop the application and release resources."""
        with self._lock:
            if self._started:
                self._flask.config["EXIT"] = True
                self._stop_event.set()
                self._flask.logger.info("Closing...")
                try:
                    self._shutdown()
                except Exception as e:
                    self._flask.logger.exception(f"Error occurred: {e}")
                self._flask.logger.info("Application stopped")
            else:
                self._flask.logger.debug("Application already stopped")
