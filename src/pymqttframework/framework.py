#!/usr/bin/env python3

import contextlib
import importlib.metadata
import json
import os
import signal
import threading
import tomllib
import logging
import time
from typing import Callable
import tzlocal

from datetime import datetime, timedelta
from threading import Lock

from flask import Flask as Flask, Response
from flask import jsonify
from cheroot.wsgi import Server as WSGIServer

from flask_mqtt import Mqtt
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from prometheus_flask_exporter import PrometheusMetrics
from prometheus_client import CollectorRegistry, Counter, Summary

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from pymqttframework.app import App as App, TriggerSource
from pymqttframework.config import Config as Config
from pymqttframework.read_only_dict import ReadOnlyDict

# current MQTT-Framework version
__version__ = importlib.metadata.version("pymqttframework")


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
        self.__add_trace_level_to_logger()
        self.__init_flask()
        self.__init_flask_routes()
        self.__init_metrics()
        self.__init_mqtt()
        self._started = False
        self._mqtt_callbacks = {}

    def __add_trace_level_to_logger(self) -> None:
        logging.addLevelName(self._TRACE_LOG_LEVEL, "TRACE")

    def _trace_log(self, message, *args, **kwargs) -> None:
        if self._flask.logger.isEnabledFor(self._TRACE_LOG_LEVEL):
            self._flask.logger.log(self._TRACE_LOG_LEVEL, message, *args, **kwargs)

    def __init_flask(self) -> None:
        # config not yet available, so read values directly from env vars

        static_folder = Config.WEB_STATIC_DIR
        if os.environ.get("CFG_WEB_STATIC_DIR") is not None:
            static_folder = os.environ.get("CFG_WEB_STATIC_DIR")

        template_folder = Config.WEB_TEMPLATE_DIR
        if os.environ.get("CFG_WEB_TEMPLATE_DIR") is not None:
            template_folder = os.environ.get("CFG_WEB_TEMPLATE_DIR")

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
        port = self._flask.config["WEB_PORT"]
        self._WSGIServer = WSGIServer(("0.0.0.0", port), self._flask)
        self._WSGIServer.start()  # blocking
        self._trace_log("WSGIServer stopped")

    def _start_flask(self) -> None:
        self._server_thread = threading.Thread(target=self._start_wsgi_server_blocking)
        self._server_thread.start()

    def _stop_flask(self) -> None:
        self._trace_log("Stop WSGIServer")
        self._WSGIServer.stop()
        self._server_thread.join()

    def _signal_handler(self, sig, frame) -> None:
        self._trace_log(f"Signal {signal.strsignal(sig)} received")
        self.shutdown()

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _load_config(self, config: Config) -> None:
        self._flask.config.from_object(config)
        config_file = os.getenv("CFG_CONFIG_FILE", None)
        if config_file is not None:
            if config_file.endswith(".toml"):
                self._flask.config.from_file(config_file, load=tomllib.load, text=False)
            elif config_file.endswith(".json"):
                self._flask.config.from_file(config_file, load=json.load)
            else:
                self._flask.config.from_pyfile(config_file)
        self._flask.config.from_prefixed_env("CFG")

        if self._flask.config["LOG_LEVEL"] in ["TRACE "]:
            logging.getLogger("werkzeug").setLevel(logging.DEBUG)
        else:
            logging.getLogger("werkzeug").setLevel(logging.ERROR)
        self._flask.logger.setLevel(self._flask.config["LOG_LEVEL"])

    def _do_wait(self) -> None:
        self._trace_log("Start blocking")
        while not self._flask.config["EXIT"]:
            try:
                time.sleep(1)
            except KeyboardInterrupt:
                self._trace_log("KeyboardInterrupt received")
                self.shutdown()
                break
        self._trace_log("End blocking")

    def _add_scheduler_jobs(self, next_run_time) -> None:
        update_interval = self._flask.config["UPDATE_INTERVAL"]
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
                seconds=self._flask.config["UPDATE_INTERVAL"],
                next_run_time=next_run_time,
            )
        if cron_schedule := self._flask.config["UPDATE_CRON_SCHEDULE"]:
            self._trace_log(f"Schedule cron job: {cron_schedule}")
            self._scheduler.add_job(
                self._call_do_update,
                name="CRON_SCHEDULE",
                trigger=self._create_cron_trigger(),
                args=[TriggerSource.CRON],
                id="do_update_cron",
                max_instances=1,
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

    def _start(self, app: App, config: Config, blocked=False) -> int:
        if self._started:
            self._flask.logger.debug("Application already started")
            return 1

        self._load_config(config)

        if blocked:
            self._install_signal_handlers()

        self._app = app

        # share some variables and functions to app
        class CallbacksImpl:
            def __init__(self, obj) -> None:
                self.obj = obj

            def get_config(self) -> dict:
                return ReadOnlyDict(self.obj._flask.config)

            def get_logger(self) -> logging.Logger:
                return self.obj._flask.logger

            def get_metrics_registry(self) -> CollectorRegistry:
                return self.obj._metrics_registry

            def add_url_rule(
                self,
                rule: str,
                endpoint=None,
                view_func=None,
                provide_automatic_options=None,
                **options,
            ) -> None:
                self.obj._flask.add_url_rule(
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
                retain=False,
            ) -> None:
                self.obj._publish_value_to_mqtt_topic(topic, value, retain=retain)

            def subscribe_to_mqtt_topic(
                self, topic: str, callback: Callable[[str, str], None] | None = None
            ) -> None:
                self.obj._subscribe_to_mqtt_topic(topic, callback)

        self._limiter.init_app(self._flask)
        self._metrics.init_app(self._flask)
        self._app.init(CallbacksImpl(self))
        self._mqtt.init_app(self._flask)
        self._add_scheduler_jobs(
            next_run_time=datetime.now()
            + timedelta(seconds=self._flask.config["DELAY_BEFORE_FIRST_TRY"])
        )
        self._start_flask()
        self._flask.logger.critical(
            f"{app.__class__.__name__} version {app.get_version()} started, "
            f"framework version {__version__} "
        )

        self._scheduler.start()
        self._started = True
        return 0

    def _shutdown(self) -> None:
        self._app.stop()
        self._scheduler.shutdown(wait=True)
        self._stop_flask()
        self._mqtt.unsubscribe_all()
        self._publish_value_to_mqtt_topic(self.TOPIC_STATUS, "offline", True)
        self._mqtt._disconnect()
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
        self._scheduler.remove_all_jobs()
        self._scheduler.add_job(
            self._call_do_update,
            trigger="date",
            args=[TriggerSource.MANUAL],
            id="do_update_manual",
            max_instances=1,
            next_run_time=datetime.now(),
        )
        self._add_scheduler_jobs(
            next_run_time=datetime.now()
            + timedelta(seconds=self._flask.config["UPDATE_INTERVAL"])
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
        return self._flask.config["MQTT_TOPIC_PREFIX"] + topic

    def _subscribe_to_mqtt_topic(
        self, topic: str, callback: Callable[[str, str], None] | None = None
    ) -> None:
        fulltopic = self._to_full_mqtt_topic_name(topic)
        self._flask.logger.debug(f"Subscribe to MQTT topic: {fulltopic}")
        self._mqtt.subscribe(fulltopic)
        if callback:
            self._mqtt_callbacks[topic] = callback

    def _publish_value_to_mqtt_topic(
        self, topic: str, value: str | bytes | bytearray | int | float, retain=False
    ) -> None:
        self._mqtt_messages_sent_metric.inc()
        fulltopic = self._to_full_mqtt_topic_name(topic)
        self._flask.logger.debug(
            f"Publish to topic '{fulltopic}' retain {retain}: '{value}'"
        )
        with contextlib.suppress(Exception):
            self._mqtt.publish(fulltopic, value, retain=retain)  # type: ignore

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
        data = str(message.payload.decode("utf-8"))
        self._flask.logger.debug(
            f"MQTT message received: topic={message.topic}, "
            f"qos={message.qos}, data: {data}"
        )
        topic = message.topic.removeprefix(self._flask.config["MQTT_TOPIC_PREFIX"])

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
                self._flask.logger.setLevel(data.upper())
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

    def run(self, app: App, config: Config) -> int:
        """
        Start the application and block until it is stopped
        by a signal or shutdown() is called

        :param app: The application to run
        :param config: The configuration to use
        :return: 0 if application was started successfully, \
                 1 if application was already started
        """
        return self.start(app, config, blocked=True)

    def start(self, app: App, config: Config, blocked=False) -> int:
        """
        Start the application

        :param app: The application to run
        :param config: The configuration to use
        :param blocked: If True, block until application is stopped \
                        by a signal or shutdown() is called
        :return: 0 if application was started successfully, \
                 1 if application was already started
        """
        with self._lock:
            if retval := self._start(app, config, blocked):
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
                self._flask.logger.info("Closing...")
                try:
                    self._shutdown()
                except Exception as e:
                    self._flask.logger.exception(f"Error occurred: {e}")
                self._flask.logger.critical("Application stopped")
            else:
                self._flask.logger.debug("Application already stopped")
