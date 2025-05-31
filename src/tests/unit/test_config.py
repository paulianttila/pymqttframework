from mqtt_framework import Config
import ssl


class MyConfig(Config):
    def __init__(self):
        super().__init__(self.APP_NAME)

    APP_NAME = "myapp"

    # App specific variables

    TEST_VARIABLE = 123456


def test_config():
    myconfig = MyConfig()

    assert myconfig.EXIT is False
    assert myconfig.LOG_LEVEL == "INFO"
    assert myconfig.UPDATE_INTERVAL == 60
    assert myconfig.DELAY_BEFORE_FIRST_TRY == 5
    assert myconfig.WEB_PORT == 5000
    assert myconfig.WEB_STATIC_DIR == "/web/static"
    assert myconfig.WEB_TEMPLATE_DIR == "/web/templates"

    assert myconfig.MQTT_BROKER_URL == "127.0.0.1"
    assert myconfig.MQTT_BROKER_PORT == 1883
    assert myconfig.MQTT_USERNAME is None
    assert myconfig.MQTT_PASSWORD is None
    assert myconfig.MQTT_KEEPALIVE == 30
    assert myconfig.MQTT_TLS_ENABLED is False
    assert myconfig.MQTT_TLS_CA_CERTS is None
    assert myconfig.MQTT_TLS_CERTFILE is None
    assert myconfig.MQTT_TLS_KEYFILE is None
    assert myconfig.MQTT_TLS_VERSION == ssl.PROTOCOL_TLSv1_2
    assert myconfig.MQTT_TLS_INSECURE is False
    assert myconfig.MQTT_LAST_WILL_MESSAGE == "offline"
    assert myconfig.MQTT_LAST_WILL_RETAIN is True

    assert myconfig.MQTT_CLIENT_ID == "myapp"
    assert myconfig.MQTT_TOPIC_PREFIX == "myapp/"
    assert myconfig.MQTT_LAST_WILL_TOPIC == "myapp/status"

    assert myconfig.APP_NAME == "myapp"
    assert myconfig.TEST_VARIABLE == 123456
