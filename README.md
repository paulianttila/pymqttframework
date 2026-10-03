# Python MQTT Framework

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Latest release](https://img.shields.io/github/v/release/paulianttila/pymqttframework.svg)](https://github.com/paulianttila/pymqttframework/releases)
[![CI](https://github.com/paulianttila/pymqttframework/workflows/CI/badge.svg)](https://github.com/paulianttila/pymqttframework/actions?query=workflow%3ACI)

A lightweight, robust application framework for MQTT-based Python services.
The goal of this framework is to simplify application architecture and eliminate repetitive boilerplate for connection lifecycle, scheduling, REST interfaces, rate limiting, and metrics.

---

## Features

- **Reliable MQTT Client**: Automatic connection management, status publication (`online`/`offline` via LWT), and simplified pub/sub routing.
- **Dual Scheduling**: Built-in interval and cron schedulers (supporting both 5-field standard UNIX and 6-field Spring expressions) to drive periodic updates.
- **Cascading Configuration**: Seamless configuration via Python classes, configuration files (`.toml`, `.json`, `.py`), and prefixed environment variables (`CFG_*`).
- **Built-in REST API**: Health checks (`/healthy`), scheduling introspection (`/jobs`), manual trigger (`/update`), and support for custom endpoints.
- **Rate Limiting**: Integrated endpoint rate limiting powered by Flask-Limiter.
- **Prometheus Metrics**: Pre-instrumented operational metrics (`/metrics`) and custom metric registry access.
- **Full Type Safety**: Compliant with PEP 561 (`py.typed`) using Python `Protocol` definitions for loose coupling.
- **Clean Lifecycle**: Zero-latency, graceful shutdown on `SIGINT`/`SIGTERM` with individual resource protection.

---

## Installation

```bash
pip install pymqttframework
```

Or using [uv](https://docs.astral.sh/uv/):

```bash
uv add pymqttframework
```

---

## Environment Variables

All settings can be configured via environment variables using the `CFG_` prefix. Values passed via environment variables override those loaded from configuration files.

| **Variable**                 | **Default**     | **Description**                                                                                                 |
|------------------------------|-----------------|-----------------------------------------------------------------------------------------------------------------|
| `CFG_APP_NAME`               |                 | Name of the application.                                                                                        |
| `CFG_CONFIG_FILE`            | None            | Path to configuration file (`.toml`, `.json`, or `.py`). See [Configuration files](#configuration-files).       |
| `CFG_LOG_LEVEL`              | `INFO`          | Logging level: `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`.                                     |
| `CFG_UPDATE_INTERVAL`        | `60`            | Periodic update interval in seconds (`0` = disabled).                                                          |
| `CFG_UPDATE_CRON_SCHEDULE`   | None            | Periodic update cron schedule. Supports 5-field UNIX and 6-field Spring syntax.                                 |
| `CFG_DELAY_BEFORE_FIRST_TRY` | `5`             | Initial delay in seconds before the first scheduled update.                                                     |
| `CFG_WEB_HOST`               | `0.0.0.0`       | Bind address for the internal REST/metrics web server.                                                          |
| `CFG_WEB_PORT`               | `5000`          | Port for the internal web server.                                                                               |
| `CFG_WEB_STATIC_DIR`         | `/web/static`   | Directory path for static assets.                                                                               |
| `CFG_WEB_TEMPLATE_DIR`       | `/web/templates`| Directory path for Jinja templates.                                                                             |
| `CFG_MQTT_BROKER_URL`        | `127.0.0.1`     | Hostname or IP of the MQTT broker.                                                                              |
| `CFG_MQTT_BROKER_PORT`       | `1883`          | Port of the MQTT broker.                                                                                        |
| `CFG_MQTT_CLIENT_ID`         | `<app_name>`    | MQTT client identifier.                                                                                         |
| `CFG_MQTT_USERNAME`          | None            | Username for MQTT broker authentication.                                                                        |
| `CFG_MQTT_PASSWORD`          | None            | Password for MQTT broker authentication.                                                                        |
| `CFG_MQTT_KEEPALIVE`         | `30`            | Keepalive interval in seconds.                                                                                  |
| `CFG_MQTT_TOPIC_PREFIX`      | `<app_name>/`   | Topic prefix automatically prepended to all published and subscribed topics.                                    |
| `CFG_MQTT_TLS_ENABLED`       | `False`         | Enable TLS/SSL connection to the broker.                                                                        |
| `CFG_MQTT_TLS_CA_CERTS`      | None            | Path to CA certificate file.                                                                                    |
| `CFG_MQTT_TLS_CERTFILE`      | None            | Path to PEM-encoded client certificate file.                                                                    |
| `CFG_MQTT_TLS_KEYFILE`       | None            | Path to PEM-encoded client private key file.                                                                    |
| `CFG_MQTT_TLS_VERSION`       | `PROTOCOL_TLSv1_2` | TLS protocol version (from Python `ssl` module).                                                                |
| `CFG_MQTT_TLS_INSECURE`      | `False`         | Disable hostname verification in server certificate.                                                            |
| `CFG_MQTT_LAST_WILL_TOPIC`   | `<app_name>/status`| Topic to publish the last will message to.                                                                   |
| `CFG_MQTT_LAST_WILL_MESSAGE` | `offline`       | Last will and testament (LWT) payload published when client disconnects ungracefully.                           |
| `CFG_MQTT_LAST_WILL_RETAIN`  | `True`          | Retain flag for the last will message.                                                                          |

---

## Configuration Files

A configuration file can be supplied directly to `Framework.run()` / `Framework.start()` or via the `CFG_CONFIG_FILE` environment variable.

Supported formats:
- **TOML** (`.toml`)
- **JSON** (`.json`)
- **Python** (`.py`)

In configuration files, variable names should be specified without the `CFG_` prefix:

```toml
# config.toml
LOG_LEVEL = "DEBUG"
UPDATE_INTERVAL = 30
MQTT_BROKER_URL = "mqtt.local"
MQTT_BROKER_PORT = 1883
```

---

## Built-in MQTT Topics

The framework automatically manages the following topics under the configured `<app_name>/` prefix:

| **Topic** | **Description** |
|---|---|
| `<prefix>/status` | Automatically published with retain: `online` on connect, `offline` on graceful shutdown or via LWT. |
| `<prefix>/updateNow` | Publishing `true`, `yes`, or `1` triggers an immediate manual update via `do_update(TriggerSource.MANUAL)`. |
| `<prefix>/setLogLevel` | Dynamically updates the logger level (`TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |

---

## Built-in REST Interface

The framework exposes the following endpoints on `http://<WEB_HOST>:<WEB_PORT>`:

| **Path** | **Method** | **Description** |
|---|---|---|
| `/healthy` | `GET` | Calls `app.do_healthy_check()`. Returns `200 OK` or `500 FAIL`. (Rate limited: 10/min) |
| `/update` | `GET` | Triggers immediate manual update via `do_update(TriggerSource.MANUAL)`. (Rate limited: 2/min) |
| `/jobs` | `GET` | Returns currently scheduled interval and cron jobs with next run times in JSON format. |
| `/metrics` | `GET` | Exposes Prometheus operational metrics. |

---

## Prometheus Metrics

The `/metrics` endpoint exposes default framework metrics alongside any custom metrics registered via `callbacks.get_metrics_registry()`:

| **Metric Name** | **Type** | **Description** |
|---|---|---|
| `mqtt_messages_received_total` | Counter | Total number of MQTT messages received by subscribed topics. |
| `mqtt_messages_sent_total` | Counter | Total number of MQTT messages successfully published. |
| `do_update` | Summary | Latency summary and execution count for `app.do_update()` invocations (`do_update_count`, `do_update_sum`). |
| `do_update_exceptions_total` | Counter | Total count of unhandled exceptions raised during `app.do_update()`. |
| `flask_http_request_duration_seconds` | Histogram | Standard HTTP request latency histogram for all REST endpoints. |
| `flask_http_request_total` | Counter | Standard HTTP request counter categorized by method, status code, and handler. |

---

## Scheduling & Cron Syntax

The framework supports two complementary scheduling mechanisms:

1. **Interval Schedule (`CFG_UPDATE_INTERVAL`)**:
   Runs `app.do_update(TriggerSource.INTERVAL)` every `N` seconds. Set to `0` to disable interval updates.

2. **Cron Schedule (`CFG_UPDATE_CRON_SCHEDULE`)**:
   Runs `app.do_update(TriggerSource.CRON)` according to standard cron expressions. Both 5-field UNIX and 6-field Spring syntax are supported:
   - **5-field UNIX** (`minute hour day month day-of-week`):
     ```bash
     CFG_UPDATE_CRON_SCHEDULE="*/15 * * * *"    # Every 15 minutes
     CFG_UPDATE_CRON_SCHEDULE="0 6 * * 1-5"     # 6:00 AM on weekdays
     ```
   - **6-field Spring** (`second minute hour day month day-of-week`):
     ```bash
     CFG_UPDATE_CRON_SCHEDULE="0 */15 * * * *"  # Every 15 minutes at second 0
     CFG_UPDATE_CRON_SCHEDULE="30 0 12 * * *"   # 12:00:30 PM daily
     ```

When an update is triggered manually via `/update` or `<prefix>/updateNow`, the next scheduled interval run is automatically reset to prevent overlapping runs.

---

## API Reference

### `App` Protocol (`pymqttframework.app.App`)

Applications implement the `App` protocol (or any subset of methods needed):

```python
class App(Protocol):
    def init(self, callbacks: Callbacks) -> None:
        """Called during framework initialization. Store callbacks, register HTTP routes, etc."""
        ...

    def get_version(self) -> str:
        """Return the application version string."""
        ...

    def stop(self) -> None:
        """Invoked during graceful application shutdown to clean up resources."""
        ...

    def subscribe_to_mqtt_topics(self) -> None:
        """Called upon initial connection and reconnection. Subscribe to topics without app prefix."""
        ...

    def mqtt_message_received(self, topic: str, message: str) -> None:
        """Invoked when a message arrives on a subscribed topic (topic has app prefix stripped)."""
        ...

    def do_healthy_check(self) -> bool:
        """Called by the /healthy REST endpoint. Return True for 200 OK, False for 500 FAIL."""
        ...

    def do_update(self, trigger_source: TriggerSource) -> None:
        """Called on interval, cron, or manual trigger. Perform periodic polling/sync."""
        ...
```

### `Callbacks` Interface (`pymqttframework.callbacks.Callbacks`)

Injected into `app.init(callbacks)`:

| **Method** | **Description** |
|---|---|
| `get_config()` | Returns read-only mapping of application configuration (`ReadOnlyDict`). |
| `get_logger()` | Returns the preconfigured logging instance. |
| `get_metrics_registry()` | Returns the Prometheus `CollectorRegistry` for registering custom application metrics. |
| `add_url_rule(rule, endpoint=None, view_func=None, **options)` | Registers a custom Flask route on the internal HTTP server. |
| `publish_value_to_mqtt_topic(topic, value, retain=False)` | Publishes a message to an MQTT topic (automatically prepends `<app_name>/`). |
| `subscribe_to_mqtt_topic(topic, callback=None)` | Subscribes to an MQTT topic with an optional dedicated callback handler `callback(topic, message)`. |

### `Framework` Class (`pymqttframework.Framework`)

| **Method** | **Description** |
|---|---|
| `run(app, config, config_file=None) -> int` | Runs the application, registers signal handlers (`SIGINT`, `SIGTERM`), and blocks until stopped. |
| `start(app, config, blocked=False, config_file=None) -> int` | Starts services. When `blocked=False`, runs background worker threads asynchronously. |
| `shutdown() -> None` | Gracefully shuts down web server, scheduler, and MQTT client, publishing `offline` status. |

---

## Usage Example

```python
from pymqttframework import Framework, Config
from pymqttframework.app import TriggerSource
from pymqttframework.callbacks import Callbacks


class MyConfig(Config):
    APP_NAME = "sensor_hub"

    def __init__(self) -> None:
        super().__init__(self.APP_NAME)

    # Custom application configuration
    POLL_SENSOR_ENABLED = True


class MyApp:
    def init(self, callbacks: Callbacks) -> None:
        self.logger = callbacks.get_logger()
        self.config = callbacks.get_config()
        self.metrics_registry = callbacks.get_metrics_registry()
        self.publish = callbacks.publish_value_to_mqtt_topic
        self.subscribe = callbacks.subscribe_to_mqtt_topic
        self.counter = 0

        # Register custom HTTP route
        callbacks.add_url_rule("/status", view_func=lambda: {"count": self.counter})

    def get_version(self) -> str:
        return "1.0.0"

    def stop(self) -> None:
        self.logger.info("Application shutting down...")

    def subscribe_to_mqtt_topics(self) -> None:
        # Topic is relative to app prefix (subscribes to 'sensor_hub/commands')
        self.subscribe("commands")

    def mqtt_message_received(self, topic: str, message: str) -> None:
        self.logger.info("Received message on '%s': %s", topic, message)

    def do_healthy_check(self) -> bool:
        return True

    def do_update(self, trigger_source: TriggerSource) -> None:
        self.logger.debug("Update triggered by %s", trigger_source)
        self.counter += 1
        self.publish("counter", self.counter)


if __name__ == "__main__":
    Framework().run(MyApp(), MyConfig())
```

---

## Architecture

The framework is organized into decoupled, modular components:

- **`Framework`** ([`framework.py`](file:///Users/pali/Projects/pymqttframework/src/pymqttframework/framework.py)): Coordinator facade managing signals and startup/shutdown lifecycle.
- **`MqttManager`** ([`mqtt.py`](file:///Users/pali/Projects/pymqttframework/src/pymqttframework/mqtt.py)): Encapsulates Flask-MQTT, topic routing, safe payload decoding, and publishing.
- **`WebServer`** ([`server.py`](file:///Users/pali/Projects/pymqttframework/src/pymqttframework/server.py)): Manages Flask, WSGIServer background thread, rate limiting, and endpoints.
- **`FrameworkScheduler`** ([`scheduler.py`](file:///Users/pali/Projects/pymqttframework/src/pymqttframework/scheduler.py)): Manages APScheduler, cron/interval job registration, and safe rescheduling.
- **`config_loader`** ([`config_loader.py`](file:///Users/pali/Projects/pymqttframework/src/pymqttframework/config_loader.py)): Multi-format configuration ingestion and environment variable normalization.
- **`FrameworkMetrics`** ([`metrics.py`](file:///Users/pali/Projects/pymqttframework/src/pymqttframework/metrics.py)): Prometheus metrics definitions.

---

## Development & Testing

### Running Unit Tests

```bash
uv run pytest -v --cov=pymqttframework
```

### Running Integration Tests Locally

The integration test suite runs Tavern tests against a live Mosquitto MQTT broker:

```bash
./run_integration_tests.sh
```

*Note: The script automatically detects if a local Mosquitto broker is active, or launches and tears down a background instance automatically using your local Mosquitto installation (`brew install mosquitto` on macOS or `apt-get install mosquitto` on Linux).*

### Code Quality & Formatting

```bash
# Linting
uv tool run ruff check .

# Formatting check
uv tool run black --check --diff .

# Type checking
uv run mypy src

# Security scan
uv tool run bandit -c pyproject.toml -r .
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
