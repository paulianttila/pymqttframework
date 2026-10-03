#!/usr/bin/env python3

from collections.abc import Callable, Mapping
import importlib.metadata
import json
import logging
import os
import signal
import threading
import tomllib
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from cheroot.wsgi import Server as WSGIServer
from flask import Flask, Response, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mqtt import Mqtt
from prometheus_client import CollectorRegistry, Counter, Summary
from prometheus_flask_exporter import PrometheusMetrics
import tzlocal

from pymqttframework.app import App, TriggerSource
from pymqttframework.callbacks import Callbacks
from pymqttframework.config import Config
from pymqttframework.read_only_dict import ReadOnlyDict

# current MQTT-Framework version
try:
    __version__ = importlib.metadata.version("pymqttframework")
except importlib.metadata.PackageNotFoundError:
    __version__ = "unknown"


class CallbacksImpl(Callbacks):
    """Implementation of Callbacks protocol provided to client applications."""

    def __init__(self, framework: "Framework") -> None:
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


class Framework:
    TOPIC_STATUS = "status"
    TOPIC_UPDATE_NOW = "updateNow"
    TOPIC_SET_LOG_LEVEL = "setLogLevel"

    ###########################################################
    # Init and shutdown methods
    ###########################################################

    def __init__(self) -> None:
        self._TRACE_LOG_LEVEL = 5
        self._limiter = Limiter(
            get_remote_address,
            default_limits=["1 per second"],
            storage_uri="memory://",
            strategy="fixed-window",
        )
        self._scheduler = BackgroundScheduler(timezone=str(tzlocal.get_localzone()))
        self._lock = Lock()
        self._update_lock = Lock()
        self._stop_event = threading.Event()
        self.__add_trace_level_to_logger()
        self.__init_flask()
        self.__init_flask_routes()
        self.__init_metrics()
        self.__init_mqtt()
        self._started = False
        self._mqtt_callbacks: dict[str, Callable[[str, str], None]] = {}

    def __add_trace_level_to_logger(self) -> None:
        logging.addLevelName(self._TRACE_LOG_LEVEL, "TRACE")

    def _trace_log(self, message: str, *args: Any, **kwargs: Any) -> None:
        if self._flask.logger.isEnabledFor(self._TRACE_LOG_LEVEL):
            self._flask.logger.log(self._TRACE_LOG_LEVEL, message, *args, **kwargs)

    def __init_flask(self) -> None:
        # config not yet available, so read values directly from env vars
        static_folder = os.environ.get("CFG_WEB_STATIC_DIR", Config.WEB_STATIC_DIR)
        template_folder = os.environ.get(
            "CFG_WEB_TEMPLATE_DIR", Config.WEB_TEMPLATE_DIR
        )

        self._flask = Flask(
            __name__, static_folder=static_folder, template_folder=template_folder
        )

    def __init_flask_routes(self) -> None:
        @self._flask.route("/healthy")
        @self._limiter.limit("10 per minute")
        def do_healthy_check() -> tuple[str, int]:
            return self._rest_do_healthy_check()

        @self._flask.route("/update")
        @self._limiter.limit("2 per minute")
        def update() -> tuple[str, int]:
            return self._rest_update_now()

        @self._flask.route("/jobs")
        @self._limiter.limit("1 per second")
        def printjobs() -> tuple[Response, int]:
            return self._rest_get_jobs()

    def __init_mqtt(self) -> None:
        self._mqtt = Mqtt()

        @self._mqtt.on_connect()
        def handle_connect(client, userdata, flags, rc) -> None:
            self._mqtt_handle_connect(client, userdata, flags, rc)

        @self._mqtt.on_message()
        def mqtt_message_received(client, userdata, message) -> None:
            self._mqtt_message_received(client, userdata, message)

        @self._mqtt.on_log()
        def handle_logging(client, userdata, level, buf) -> None:
            self._trace_log(f"MQTT: {buf}")

    def __init_metrics(self) -> None:
        self._metrics_registry = CollectorRegistry()
        self._metrics = PrometheusMetrics(app=None, registry=self._metrics_registry)
        self._mqtt_messages_received_metric = Counter(
            "mqtt_messages_received", "", registry=self._metrics_registry
        )
        self._mqtt_messages_sent_metric = Counter(
            "mqtt_messages_sent", "", registry=self._metrics_registry
        )
        self._do_update_metric = Summary(
            "do_update", "Time spent in do_update", registry=self._metrics_registry
        )
        self._do_update_exception_metric = Counter(
            "do_update_exceptions",
            "How many exceptions caused by do_update",
            registry=self._metrics_registry,
        )

    def _start_wsgi_server_blocking(self) -> None:
        self._trace_log("Start WSGIServer")
        host = self._flask.config.get("WEB_HOST", "0.0.0.0")
        port = self._flask.config["WEB_PORT"]
        self._WSGIServer = WSGIServer((host, port), self._flask)
        self._WSGIServer.start()  # blocking
        self._trace_log("WSGIServer stopped")

    def _start_flask(self) -> None:
        self._server_thread = threading.Thread(target=self._start_wsgi_server_blocking)
        self._server_thread.start()

    def _stop_flask(self) -> None:
        self._trace_log("Stop WSGIServer")
        if hasattr(self, "_WSGIServer"):
            self._WSGIServer.stop()
        if hasattr(self, "_server_thread"):
            self._server_thread.join()

    def _signal_handler(self, sig: int, frame: Any) -> None:
        self._trace_log(f"Signal {signal.strsignal(sig)} received")
        self.shutdown()

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _load_config(self, config: Config, config_file: str | None = None) -> None:
        self._flask.config.from_object(config)
        if config_file is None:
            config_file = os.getenv("CFG_CONFIG_FILE", None)

        if config_file is not None:
            if config_file.endswith(".toml"):
                self._flask.config.from_file(config_file, load=tomllib.load, text=False)
            elif config_file.endswith(".json"):
                self._flask.config.from_file(config_file, load=json.load)
            else:
                self._flask.config.from_pyfile(config_file)
        self._flask.config.from_prefixed_env("CFG")

        # Normalize boolean configuration variables loaded from env strings
        for bool_key in (
            "MQTT_TLS_ENABLED",
            "MQTT_TLS_INSECURE",
            "MQTT_LAST_WILL_RETAIN",
        ):
            val = self._flask.config.get(bool_key)
            if isinstance(val, str):
                self._flask.config[bool_key] = val.lower() in ("true", "1", "yes")

        # Update static and template directories if configured
        if self._flask.config.get("WEB_STATIC_DIR"):
            self._flask.static_folder = self._flask.config["WEB_STATIC_DIR"]
        if self._flask.config.get("WEB_TEMPLATE_DIR"):
            self._flask.template_folder = self._flask.config["WEB_TEMPLATE_DIR"]

        log_level = self._flask.config.get("LOG_LEVEL", "INFO")
        if log_level == "TRACE":
            logging.getLogger("werkzeug").setLevel(logging.DEBUG)
        else:
            logging.getLogger("werkzeug").setLevel(logging.ERROR)
        self._flask.logger.setLevel(log_level)

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

    def _add_scheduler_jobs(self, next_run_time: datetime) -> None:
        update_interval = self._flask.config.get("UPDATE_INTERVAL", 0)
        if update_interval > 0:
            self._trace_log(
                f"Schedule interval job to happen in every {update_interval} sec"
            )
            self._scheduler.add_job(
                self._call_do_update,
                name="INTERVAL",
                trigger="interval",
                args=[TriggerSource.INTERVAL],
                id="do_update_interval",
                max_instances=1,
                seconds=update_interval,
                next_run_time=next_run_time,
                replace_existing=True,
            )
        if cron_schedule := self._flask.config.get("UPDATE_CRON_SCHEDULE"):
            self._trace_log(f"Schedule cron job: {cron_schedule}")
            self._scheduler.add_job(
                self._call_do_update,
                name="CRON_SCHEDULE",
                trigger=self._create_cron_trigger(),
                args=[TriggerSource.CRON],
                id="do_update_cron",
                max_instances=1,
                replace_existing=True,
            )

    def _create_cron_trigger(self) -> CronTrigger:
        cron_schedule = self._flask.config["UPDATE_CRON_SCHEDULE"]
        values = cron_schedule.split()
        if len(values) == 6:
            return CronTrigger(
                second=values[0],
                minute=values[1],
                hour=values[2],
                day=values[3],
                month=values[4],
                day_of_week=values[5],
            )
        else:
            return CronTrigger.from_crontab(cron_schedule)

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

        if blocked:
            self._install_signal_handlers()

        self._app = app
        self._stop_event.clear()

        self._limiter.init_app(self._flask)
        self._metrics.init_app(self._flask)
        self._app.init(CallbacksImpl(self))
        self._mqtt.init_app(self._flask)
        self._add_scheduler_jobs(
            next_run_time=datetime.now()
            + timedelta(seconds=self._flask.config.get("DELAY_BEFORE_FIRST_TRY", 5))
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
            self._mqtt._disconnect()
        except Exception as e:
            self._flask.logger.exception(f"Error disconnecting MQTT: {e}")

        self._started = False

    ###########################################################
    # Generic methods
    ###########################################################

    def _call_do_update(self, trigger_source: TriggerSource) -> None:
        @self._do_update_metric.time()
        @self._do_update_exception_metric.count_exceptions()
        def do():
            self._app.do_update(trigger_source)

        do()

    def _update_now(self) -> None:
        with self._update_lock:
            self._scheduler.add_job(
                self._call_do_update,
                trigger="date",
                args=[TriggerSource.MANUAL],
                id="do_update_manual",
                max_instances=1,
                next_run_time=datetime.now(),
                replace_existing=True,
            )
            update_interval = self._flask.config.get("UPDATE_INTERVAL", 0)
            if update_interval > 0:
                next_run = datetime.now() + timedelta(seconds=update_interval)
                if job := self._scheduler.get_job("do_update_interval"):
                    job.modify(next_run_time=next_run)
                else:
                    self._scheduler.add_job(
                        self._call_do_update,
                        name="INTERVAL",
                        trigger="interval",
                        args=[TriggerSource.INTERVAL],
                        id="do_update_interval",
                        max_instances=1,
                        seconds=update_interval,
                        next_run_time=next_run,
                        replace_existing=True,
                    )

    ###########################################################
    # REST interface methods
    ###########################################################

    def _rest_do_healthy_check(self) -> tuple[str, int]:
        if self._app.do_healthy_check():
            self._flask.logger.debug("Healthy check OK")
            return "OK", 200
        else:
            self._flask.logger.warning("Healthy check FAIL")
            return "FAIL", 500

    def _rest_get_jobs(self) -> tuple[Response, int]:
        jobs = [
            {
                "id": str(job.id),
                "name": str(job.name),
                "trigger": str(job.trigger),
                "next_run": str(job.next_run_time),
            }
            for job in self._scheduler.get_jobs()
        ]
        return jsonify({"jobs": jobs}), 200

    def _rest_update_now(self) -> tuple[str, int]:
        self._update_now()
        return "OK", 200

    ###########################################################
    # MQTT methods
    ###########################################################

    def _to_full_mqtt_topic_name(self, topic: str) -> str:
        return self._flask.config.get("MQTT_TOPIC_PREFIX", "") + topic

    def _subscribe_to_mqtt_topic(
        self, topic: str, callback: Callable[[str, str], None] | None = None
    ) -> None:
        fulltopic = self._to_full_mqtt_topic_name(topic)
        self._flask.logger.debug(f"Subscribe to MQTT topic: {fulltopic}")
        self._mqtt.subscribe(fulltopic)
        if callback:
            self._mqtt_callbacks[topic] = callback

    def _publish_value_to_mqtt_topic(
        self,
        topic: str,
        value: str | bytes | bytearray | int | float,
        retain: bool = False,
    ) -> None:
        fulltopic = self._to_full_mqtt_topic_name(topic)
        self._flask.logger.debug(
            f"Publish to topic '{fulltopic}' retain {retain}: {value!r}"
        )
        try:
            self._mqtt.publish(fulltopic, value, retain=retain)
            self._mqtt_messages_sent_metric.inc()
        except Exception as e:
            self._flask.logger.error(
                f"Failed to publish to MQTT topic '{fulltopic}': {e}"
            )

    def _mqtt_handle_connect(self, client, userdata, flags, rc) -> None:
        self._publish_value_to_mqtt_topic(self.TOPIC_STATUS, "online", True)
        self._subscribe_to_mqtt_topic(self.TOPIC_UPDATE_NOW)
        self._subscribe_to_mqtt_topic(self.TOPIC_SET_LOG_LEVEL)
        try:
            self._app.subscribe_to_mqtt_topics()
        except Exception as e:
            self._flask.logger.exception(f"Error occurred: {e}")

    def _mqtt_message_received(self, client, userdata, message) -> None:
        self._mqtt_messages_received_metric.inc()
        try:
            data = str(message.payload.decode("utf-8"))
        except UnicodeDecodeError:
            self._flask.logger.warning(
                f"MQTT message on topic {message.topic} could not be decoded as UTF-8: {message.payload!r}"
            )
            return

        self._flask.logger.debug(
            f"MQTT message received: topic={message.topic}, "
            f"qos={message.qos}, data: {data}"
        )
        prefix = self._flask.config.get("MQTT_TOPIC_PREFIX", "")
        topic = message.topic.removeprefix(prefix)

        try:
            if topic == self.TOPIC_UPDATE_NOW and data.lower() in {"yes", "true", "1"}:
                self._update_now()
            elif topic == self.TOPIC_SET_LOG_LEVEL and data.upper() in {
                "TRACE",
                "DEBUG",
                "INFO",
                "WARNING",
                "ERROR",
                "CRITICAL",
            }:
                level = data.upper()
                self._flask.logger.setLevel(level)
                if level == "TRACE":
                    logging.getLogger("werkzeug").setLevel(logging.DEBUG)
                else:
                    logging.getLogger("werkzeug").setLevel(logging.ERROR)
            else:
                if callback := self._mqtt_callbacks.get(topic):
                    callback(topic, data)
                else:
                    self._app.mqtt_message_received(topic, data)
        except Exception as e:
            self._flask.logger.exception(
                f"Error occurred while processing MQTT message, "
                f"topic={topic}, data: {data}: {e}"
            )

    ###########################################################
    # Public methods
    ###########################################################

    def run(self, app: App, config: Config, config_file: str | None = None) -> int:
        """
        Start the application and block until it is stopped
        by a signal or shutdown() is called

        :param app: The application to run
        :param config: The configuration to use
        :param config_file: The configuration file to use
        :return: 0 if application was started successfully, \
                 1 if application was already started
        """
        return self.start(app=app, config=config, blocked=True, config_file=config_file)

    def start(
        self,
        app: App,
        config: Config,
        blocked: bool = False,
        config_file: str | None = None,
    ) -> int:
        """
        Start the application

        :param app: The application to run
        :param config: The configuration to use
        :param blocked: If True, block until application is stopped \
                        by a signal or shutdown() is called
        :param config_file: The configuration file to use
        :return: 0 if application was started successfully, \
                 1 if application was already started
        """
        with self._lock:
            if retval := self._start(
                app=app, config=config, blocked=blocked, config_file=config_file
            ):
                return retval
        if blocked:
            self._do_wait()
        return 0

    def shutdown(self) -> None:
        """
        Stop the application
        """
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
