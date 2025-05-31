from typing import Literal
from flask.wrappers import Response
from prometheus_client import Counter
from flask import render_template, jsonify

from mqtt_framework.app import App, TriggerSource
from mqtt_framework.callbacks import Callbacks


class MyApp(App):
    def init(self, callbacks: Callbacks) -> None:
        self.logger = callbacks.get_logger()
        self.config = callbacks.get_config()
        self.metrics_registry = callbacks.get_metrics_registry()
        self.add_url_rule = callbacks.add_url_rule
        self.publish_value_to_mqtt_topic = callbacks.publish_value_to_mqtt_topic
        self.subscribe_to_mqtt_topic = callbacks.subscribe_to_mqtt_topic

        self.exit = False
        self.healthy_check_state = True
        self.interval_trigger_counter = 0
        self.cron_trigger_counter = 0
        self.manual_trigger_counter = 0
        self.interval_trigger_counter_metric = Counter(
            "interval_trigger_counter", "", registry=self.metrics_registry
        )
        self.cron_trigger_counter_metric = Counter(
            "cron_trigger_counter", "", registry=self.metrics_registry
        )
        self.manual_trigger_counter_metric = Counter(
            "manual_trigger_counter", "", registry=self.metrics_registry
        )
        self.add_url_rule("/", view_func=self.result_html_page)
        self.add_url_rule("/json", view_func=self.result_json_data)

    def get_version(self) -> str:
        return "1.0.0"

    def stop(self) -> None:
        self.logger.debug("Stopping...")
        self.exit = True
        self.logger.debug("Exit")

    def subscribe_to_mqtt_topics(self) -> None:
        self.logger.debug("subscribe to topic test")
        self.subscribe_to_mqtt_topic("request")
        self.subscribe_to_mqtt_topic("config_variable_request")
        self.subscribe_to_mqtt_topic("healthy_check_state")
        self.subscribe_to_mqtt_topic("callback_request", self.callback_req_received)

    def mqtt_message_received(self, topic: str, message: str) -> None:
        self.logger.debug("received data %s for topic %s", message, topic)
        if topic == "request":
            self.publish_value_to_mqtt_topic("response", message)
        elif topic == "config_variable_request":
            self.publish_value_to_mqtt_topic(
                "config_variable_response", self.config["TEST_VARIABLE"]
            )
        elif topic == "healthy_check_state":
            self.healthy_check_state = message.lower() in ("true")
            self.publish_value_to_mqtt_topic(
                "healthy_check_state_response", self.healthy_check_state
            )

    def callback_req_received(self, topic: str, message: str) -> None:
        self.logger.debug("callback_req_received: %s", message)
        self.publish_value_to_mqtt_topic("callback_response", message)

    def do_healthy_check(self) -> bool:
        self.logger.debug("do_healthy_check called")
        return self.healthy_check_state

    def do_update(self, trigger_source: TriggerSource) -> None:
        self.logger.debug("update called, trigger_source=%s", trigger_source)

        if trigger_source == TriggerSource.MANUAL:
            self.manual_trigger_counter_metric.inc()
            self.manual_trigger_counter = self.manual_trigger_counter + 1
            self.publish_value_to_mqtt_topic("manual_trigger_counter_updated", "manual")
            self.publish_value_to_mqtt_topic(
                "manual_trigger_counter", self.manual_trigger_counter
            )

        elif trigger_source == TriggerSource.INTERVAL:
            self.interval_trigger_counter_metric.inc()
            self.interval_trigger_counter = self.interval_trigger_counter + 1
            self.publish_value_to_mqtt_topic(
                "interval_trigger_counter_updated", "interval"
            )
            self.publish_value_to_mqtt_topic(
                "interval_trigger_counter", self.interval_trigger_counter
            )

        elif trigger_source == TriggerSource.CRON:
            self.cron_trigger_counter_metric.inc()
            self.cron_trigger_counter = self.cron_trigger_counter + 1
            self.publish_value_to_mqtt_topic("cron_trigger_counter_updated", "cron")
            self.publish_value_to_mqtt_topic(
                "cron_trigger_counter", self.cron_trigger_counter
            )

    def result_html_page(self) -> str:
        return render_template(
            "index.html",
            interval_counter=self.interval_trigger_counter,
            cron_counter=self.cron_trigger_counter,
        )

    def result_json_data(self) -> tuple[Response, Literal[200]]:
        data = {"id": 1, "message": "json example data"}
        return jsonify(data), 200
