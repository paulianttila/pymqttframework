from prometheus_client import CollectorRegistry, Counter, Summary


class FrameworkMetrics:
    """Prometheus metrics container for MQTT framework."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.mqtt_messages_received = Counter(
            "mqtt_messages_received", "", registry=self.registry
        )
        self.mqtt_messages_sent = Counter(
            "mqtt_messages_sent", "", registry=self.registry
        )
        self.do_update = Summary(
            "do_update", "Time spent in do_update", registry=self.registry
        )
        self.do_update_exceptions = Counter(
            "do_update_exceptions",
            "How many exceptions caused by do_update",
            registry=self.registry,
        )
