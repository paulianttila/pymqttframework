from mqtt_framework.app import App


class MyApp:
    def init(self, app) -> None:
        pass

    def get_version(self) -> str:
        pass

    def stop(self) -> None:
        pass

    def subscribe_to_mqtt_topics(self) -> None:
        pass

    def mqtt_message_received(self, topic: str, message: str) -> None:
        pass

    def do_healthy_check(self) -> bool:
        return True

    def do_update(self) -> None:
        pass


class NotApp:
    def init(self, app) -> None:
        pass

    def get_version(self) -> str:
        pass

    def stop(self) -> None:
        pass


def test_app():
    assert issubclass(MyApp, App)


def test_notapp():
    assert not issubclass(NotApp, App)
