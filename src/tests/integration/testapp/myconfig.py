from mqtt_framework import Config


class MyConfig(Config):
    def __init__(self) -> None:
        super().__init__(self.APP_NAME)

    APP_NAME = "myapp"

    # App specific variables

    TEST_VARIABLE = 123456
