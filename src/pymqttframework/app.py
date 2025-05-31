from enum import Enum
from typing import Protocol, runtime_checkable

from pymqttframework.callbacks import Callbacks


class TriggerSource(Enum):
    INTERVAL = 1
    MANUAL = 2
    CRON = 3


@runtime_checkable
class App(Protocol):
    def init(self, callbacks: Callbacks) -> None:
        """Initialize the app"""
        ...

    def get_version(self) -> str:
        """Provide application version"""
        ...

    def stop(self) -> None:
        """This function is called when app will be shutdown for clean up"""
        ...

    def subscribe_to_mqtt_topics(self) -> None:
        """Subscribe to all nesessary MQTT topics (without app prefix)"""
        ...

    def mqtt_message_received(self, topic: str, message: str) -> None:
        """
        Message received for one of the subscribed MQTT topics (without app prefix)
        """
        ...

    def do_healthy_check(self) -> bool:
        """Do healt check. Return True for OK"""
        ...

    def do_update(self, trigger_source: TriggerSource) -> None:
        """Do periodic work and e.g. update data to MQTT if polled system"""
        ...
