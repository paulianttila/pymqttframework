import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from apscheduler.triggers.cron import CronTrigger

from pymqttframework.app import TriggerSource
from pymqttframework.config import Config
from pymqttframework.framework import CallbacksImpl, Framework
from pymqttframework.read_only_dict import ReadOnlyDict


class DummyApp:
    def __init__(self) -> None:
        self.initialized = False
        self.stopped = False
        self.healthy = True
        self.last_update_source = None
        self.received_messages = []
        self.subscribed = False

    def init(self, callbacks) -> None:
        self.initialized = True
        self.callbacks = callbacks

    def get_version(self) -> str:
        return "1.2.3"

    def stop(self) -> None:
        self.stopped = True

    def subscribe_to_mqtt_topics(self) -> None:
        self.subscribed = True

    def mqtt_message_received(self, topic: str, message: str) -> None:
        self.received_messages.append((topic, message))

    def do_healthy_check(self) -> bool:
        return self.healthy

    def do_update(self, trigger_source: TriggerSource) -> None:
        self.last_update_source = trigger_source


class DummyConfig(Config):
    def __init__(self) -> None:
        super().__init__("testapp")


def test_readonly_dict() -> None:
    data = {"key": "val", "num": 42}
    ro = ReadOnlyDict(data)

    assert ro["key"] == "val"
    assert ro.get("num") == 42
    assert "key" in ro

    with pytest.raises(RuntimeError, match="Read only configuration"):
        ro["new_key"] = "test"

    with pytest.raises(RuntimeError, match="Read only configuration"):
        del ro["key"]

    with pytest.raises(RuntimeError, match="Read only configuration"):
        ro.pop("key")

    with pytest.raises(RuntimeError, match="Read only configuration"):
        ro.popitem()

    with pytest.raises(RuntimeError, match="Read only configuration"):
        ro.clear()

    with pytest.raises(RuntimeError, match="Read only configuration"):
        ro.update({"key": "new"})

    with pytest.raises(RuntimeError, match="Read only configuration"):
        ro.setdefault("other", 100)


def test_cron_trigger_5_and_6_fields() -> None:
    fw = Framework()
    fw._flask.config["UPDATE_CRON_SCHEDULE"] = "*/5 * * * *"
    trigger5 = fw._create_cron_trigger()
    assert isinstance(trigger5, CronTrigger)

    fw._flask.config["UPDATE_CRON_SCHEDULE"] = "0 */10 * * * *"
    trigger6 = fw._create_cron_trigger()
    assert isinstance(trigger6, CronTrigger)


def test_to_full_mqtt_topic_name() -> None:
    fw = Framework()
    fw._flask.config["MQTT_TOPIC_PREFIX"] = "myprefix/"
    assert fw._to_full_mqtt_topic_name("sensor/temp") == "myprefix/sensor/temp"


def test_load_config_formats(tmp_path, monkeypatch) -> None:
    # Test JSON config file
    json_file = tmp_path / "config.json"
    json_file.write_text(json.dumps({"JSON_VAR": 999, "LOG_LEVEL": "DEBUG"}))

    fw = Framework()
    cfg = DummyConfig()
    fw._load_config(cfg, config_file=str(json_file))
    assert fw._flask.config["JSON_VAR"] == 999
    assert fw._flask.config["LOG_LEVEL"] == "DEBUG"
    assert fw._flask.logger.level == logging.DEBUG

    # Test TOML config file
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('TOML_VAR = "hello"\nLOG_LEVEL = "TRACE"\n')
    fw._load_config(cfg, config_file=str(toml_file))
    assert fw._flask.config["TOML_VAR"] == "hello"
    assert fw._flask.config["LOG_LEVEL"] == "TRACE"

    # Test Python config file
    py_file = tmp_path / "config.py"
    py_file.write_text('PY_VAR = True\nLOG_LEVEL = "INFO"\n')
    fw._load_config(cfg, config_file=str(py_file))
    assert fw._flask.config["PY_VAR"] is True
    assert fw._flask.config["LOG_LEVEL"] == "INFO"

    # Test env var override and boolean normalization
    monkeypatch.setenv("CFG_ENV_VAR", "from_env")
    monkeypatch.setenv("CFG_MQTT_TLS_ENABLED", "False")
    monkeypatch.setenv("CFG_MQTT_TLS_INSECURE", "true")
    monkeypatch.setenv("CFG_WEB_STATIC_DIR", "/custom/static")
    monkeypatch.setenv("CFG_WEB_TEMPLATE_DIR", "/custom/templates")

    fw._load_config(cfg)
    assert fw._flask.config["ENV_VAR"] == "from_env"
    assert fw._flask.config["MQTT_TLS_ENABLED"] is False
    assert fw._flask.config["MQTT_TLS_INSECURE"] is True
    assert fw._flask.static_folder == "/custom/static"
    assert fw._flask.template_folder == "/custom/templates"


def test_rest_endpoints() -> None:
    fw = Framework()
    app = DummyApp()
    fw._app = app

    # Health check OK
    app.healthy = True
    msg, code = fw._rest_do_healthy_check()
    assert code == 200
    assert msg == "OK"

    # Health check Fail
    app.healthy = False
    msg, code = fw._rest_do_healthy_check()
    assert code == 500
    assert msg == "FAIL"

    # Update now endpoint
    with patch.object(fw, "_update_now") as mock_update:
        msg, code = fw._rest_update_now()
        assert code == 200
        assert msg == "OK"
        mock_update.assert_called_once()

    # Jobs endpoint
    with fw._flask.app_context():
        resp, code = fw._rest_get_jobs()
        assert code == 200
        data = resp.get_json()
        assert "jobs" in data


def test_mqtt_publishing() -> None:
    fw = Framework()
    fw._flask.config["MQTT_TOPIC_PREFIX"] = "app/"
    fw._mqtt._mqtt = MagicMock()

    # Successful publish (return code 0)
    fw._mqtt._mqtt.publish.return_value = (0, 1)
    fw._publish_value_to_mqtt_topic("data", "value123", retain=True)
    fw._mqtt._mqtt.publish.assert_called_once_with("app/data", "value123", retain=True)
    assert fw._metrics.mqtt_messages_sent._value.get() == 1.0

    # Non-zero return code (e.g. MQTT_ERR_NO_CONN = 4) logs error and does not increment
    fw._mqtt._mqtt.publish.return_value = (4, 2)
    with patch.object(fw._flask.logger, "error") as mock_log:
        fw._publish_value_to_mqtt_topic("data", "value123")
        mock_log.assert_called_once()
        assert "MQTT error code 4" in mock_log.call_args[0][0]
        assert fw._metrics.mqtt_messages_sent._value.get() == 1.0

    # Failed publish with exception logs error without raising and does not increment
    fw._mqtt._mqtt.publish.side_effect = RuntimeError("broker disconnected")
    with patch.object(fw._flask.logger, "error") as mock_log:
        fw._publish_value_to_mqtt_topic("data", "value123")
        mock_log.assert_called_once()
        assert fw._metrics.mqtt_messages_sent._value.get() == 1.0


def test_mqtt_message_received_dispatching() -> None:
    fw = Framework()
    fw._flask.config["MQTT_TOPIC_PREFIX"] = "app/"
    app = DummyApp()
    fw._app = app

    # 1. UpdateNow message
    with patch.object(fw, "_update_now") as mock_update:
        msg = SimpleNamespace(topic="app/updateNow", payload=b"true", qos=0)
        fw._mqtt_message_received(None, None, msg)
        mock_update.assert_called_once()

    # 2. SetLogLevel message
    msg = SimpleNamespace(topic="app/setLogLevel", payload=b"DEBUG", qos=0)
    fw._mqtt_message_received(None, None, msg)
    assert fw._flask.logger.level == logging.DEBUG

    # 3. Custom subscribed callback
    custom_cb = MagicMock()
    fw._subscribe_to_mqtt_topic("custom", custom_cb)
    msg = SimpleNamespace(topic="app/custom", payload=b"custom_payload", qos=0)
    fw._mqtt_message_received(None, None, msg)
    custom_cb.assert_called_once_with("custom", "custom_payload")

    # 4. Fallback to app.mqtt_message_received
    msg = SimpleNamespace(topic="app/sensors/temp", payload=b"22.5", qos=0)
    fw._mqtt_message_received(None, None, msg)
    assert ("sensors/temp", "22.5") in app.received_messages

    # 5. Invalid UTF-8 bytes payload handled safely
    msg_bad = SimpleNamespace(topic="app/sensors/temp", payload=b"\xff\xfe\xfd", qos=0)
    with patch.object(fw._flask.logger, "warning") as mock_warn:
        fw._mqtt_message_received(None, None, msg_bad)
        mock_warn.assert_called_once()

    # 6. Exception in app callback caught and logged
    with patch.object(app, "mqtt_message_received", side_effect=Exception("boom")):
        with patch.object(fw._flask.logger, "exception") as mock_exc:
            msg = SimpleNamespace(topic="app/sensors/err", payload=b"err", qos=0)
            fw._mqtt_message_received(None, None, msg)
            mock_exc.assert_called_once()


def test_mqtt_connect_handler() -> None:
    fw = Framework()
    fw._flask.config["MQTT_TOPIC_PREFIX"] = "app/"
    app = DummyApp()
    fw._app = app

    with patch.object(fw._mqtt, "publish") as mock_pub:
        fw._mqtt_handle_connect(None, None, None, 0)
        mock_pub.assert_called_with(
            Framework.TOPIC_STATUS, "online", prefix="app/", retain=True
        )
        assert app.subscribed is True


def test_update_now_rescheduling() -> None:
    fw = Framework()
    fw._flask.config["UPDATE_INTERVAL"] = 10
    app = DummyApp()
    fw._app = app

    fw._update_now()
    jobs = fw._scheduler.get_jobs()
    job_ids = [j.id for j in jobs]
    assert "do_update_manual" in job_ids
    assert "do_update_interval" in job_ids


def test_callbacks_impl() -> None:
    fw = Framework()
    fw._flask.config["APP_VAR"] = "val"
    callbacks = CallbacksImpl(fw)

    cfg = callbacks.get_config()
    assert cfg["APP_VAR"] == "val"
    assert isinstance(cfg, ReadOnlyDict)
    assert callbacks.get_logger() == fw._flask.logger
    assert callbacks.get_metrics_registry() == fw._metrics_registry

    with patch.object(fw._flask, "add_url_rule") as mock_rule:
        callbacks.add_url_rule("/test", view_func=lambda: "ok")
        mock_rule.assert_called_once()

    with patch.object(fw, "_publish_value_to_mqtt_topic") as mock_pub:
        callbacks.publish_value_to_mqtt_topic("topic", "val", retain=True)
        mock_pub.assert_called_once_with("topic", "val", retain=True)

    with patch.object(fw, "_subscribe_to_mqtt_topic") as mock_sub:

        def cb(t: str, m: str) -> None:
            pass

        callbacks.subscribe_to_mqtt_topic("topic", cb)
        mock_sub.assert_called_once_with("topic", cb)


def test_start_and_shutdown_lifecycle() -> None:
    fw = Framework()
    app = DummyApp()
    cfg = DummyConfig()

    with (
        patch.object(fw, "_start_flask"),
        patch.object(fw._scheduler, "start"),
        patch.object(fw._mqtt, "init_app"),
    ):
        ret = fw.start(app, cfg, blocked=False)
        assert ret == 0
        assert fw._started is True
        assert app.initialized is True

        # Second start call returns 1
        ret2 = fw.start(app, cfg, blocked=False)
        assert ret2 == 1

        # Shutdown
        with (
            patch.object(fw, "_stop_flask"),
            patch.object(fw._scheduler, "shutdown"),
            patch.object(fw._mqtt, "unsubscribe_all"),
            patch.object(fw._mqtt, "disconnect"),
            patch.object(fw, "_publish_value_to_mqtt_topic"),
        ):
            fw.shutdown()
            assert fw._started is False
            assert app.stopped is True
            assert fw._stop_event.is_set()


def test_shutdown_with_exception_in_app_stop() -> None:
    fw = Framework()
    app = DummyApp()
    app.stop = MagicMock(side_effect=RuntimeError("stop error"))
    fw._app = app
    fw._started = True

    with (
        patch.object(fw, "_stop_flask") as mock_stop_flask,
        patch.object(fw._scheduler, "shutdown") as mock_sched_sd,
        patch.object(fw._mqtt, "unsubscribe_all"),
        patch.object(fw._mqtt, "disconnect"),
        patch.object(fw, "_publish_value_to_mqtt_topic"),
    ):
        fw.shutdown()
        # Even though app.stop raised, scheduler and flask were still shut down
        mock_stop_flask.assert_called_once()
        mock_sched_sd.assert_called_once()
        assert fw._started is False


def test_call_do_update() -> None:
    fw = Framework()
    app = DummyApp()
    fw._app = app

    fw._call_do_update(TriggerSource.INTERVAL)
    assert app.last_update_source == TriggerSource.INTERVAL


def test_trace_log() -> None:
    fw = Framework()
    with patch.object(fw._flask.logger, "log") as mock_log:
        fw._flask.logger.setLevel("TRACE")
        fw._trace_log("test message")
        mock_log.assert_called_once_with(5, "test message")


def test_run_wrapper() -> None:
    fw = Framework()
    app = DummyApp()
    cfg = DummyConfig()

    with patch.object(fw, "start", return_value=0) as mock_start:
        res = fw.run(app, cfg, config_file="dummy.toml")
        assert res == 0
        mock_start.assert_called_once_with(
            app=app, config=cfg, blocked=True, config_file="dummy.toml"
        )


def test_signal_handler() -> None:
    fw = Framework()
    with patch.object(fw, "shutdown") as mock_shutdown:
        fw._signal_handler(2, None)
        mock_shutdown.assert_called_once()
