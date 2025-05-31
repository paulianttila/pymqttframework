import sys
import time
from typing import NoReturn

from mqtt_framework import Framework

from myapp import MyApp
from myconfig import MyConfig


def start() -> NoReturn:
    sys.exit(Framework().run(MyApp(), MyConfig()))


def start_without_blocking() -> None:
    app = Framework()
    app.start(MyApp(), MyConfig())
    time.sleep(60)
    app.shutdown()


if __name__ == "__main__":
    start()
