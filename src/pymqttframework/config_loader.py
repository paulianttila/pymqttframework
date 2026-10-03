import json
import logging
import os
import tomllib

from flask import Flask

from pymqttframework.config import Config


def load_config(
    flask_app: Flask, config: Config, config_file: str | None = None
) -> None:
    """Load and normalize application configuration into Flask app."""
    flask_app.config.from_object(config)

    if config_file is None:
        config_file = os.getenv("CFG_CONFIG_FILE", None)

    if config_file is not None:
        if config_file.endswith(".toml"):
            flask_app.config.from_file(config_file, load=tomllib.load, text=False)
        elif config_file.endswith(".json"):
            flask_app.config.from_file(config_file, load=json.load)
        else:
            flask_app.config.from_pyfile(config_file)

    flask_app.config.from_prefixed_env("CFG")

    # Normalize boolean environment variables
    for bool_key in (
        "MQTT_TLS_ENABLED",
        "MQTT_TLS_INSECURE",
        "MQTT_LAST_WILL_RETAIN",
    ):
        val = flask_app.config.get(bool_key)
        if isinstance(val, str):
            flask_app.config[bool_key] = val.lower() in ("true", "1", "yes")

    # Update static and template directories if configured
    if flask_app.config.get("WEB_STATIC_DIR"):
        flask_app.static_folder = flask_app.config["WEB_STATIC_DIR"]
    if flask_app.config.get("WEB_TEMPLATE_DIR"):
        flask_app.template_folder = flask_app.config["WEB_TEMPLATE_DIR"]

    log_level = flask_app.config.get("LOG_LEVEL", "INFO")
    if log_level == "TRACE":
        logging.getLogger("werkzeug").setLevel(logging.DEBUG)
    else:
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
    flask_app.logger.setLevel(log_level)
