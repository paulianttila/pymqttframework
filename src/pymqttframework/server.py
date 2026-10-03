from collections.abc import Callable
import os
import threading
from typing import Any

from cheroot.wsgi import Server as WSGIServer
from flask import Flask, Response, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from prometheus_client import CollectorRegistry
from prometheus_flask_exporter import PrometheusMetrics

from pymqttframework.config import Config


class WebServer:
    """Manages the Flask REST API, rate limiting, and Cheroot WSGI server."""

    def __init__(self, trace_log_func: Callable[..., None] | None = None) -> None:
        self._trace_log = trace_log_func or (lambda msg, *a, **kw: None)
        static_folder = os.environ.get("CFG_WEB_STATIC_DIR", Config.WEB_STATIC_DIR)
        template_folder = os.environ.get(
            "CFG_WEB_TEMPLATE_DIR", Config.WEB_TEMPLATE_DIR
        )
        self.flask = Flask(
            __name__, static_folder=static_folder, template_folder=template_folder
        )
        self._limiter = Limiter(
            get_remote_address,
            default_limits=["1 per second"],
            storage_uri="memory://",
            strategy="fixed-window",
        )
        self._limiter.init_app(self.flask)
        self._wsgi_server: WSGIServer | None = None
        self._server_thread: threading.Thread | None = None

    def init_metrics(self, registry: CollectorRegistry) -> PrometheusMetrics:
        """Initialize Prometheus metrics exporter for Flask."""
        self._metrics = PrometheusMetrics(app=None, registry=registry)
        self._metrics.init_app(self.flask)
        return self._metrics

    def register_routes(
        self,
        healthy_check_func: Callable[[], bool],
        update_now_func: Callable[[], None],
        get_jobs_func: Callable[[], list[dict[str, str]]],
    ) -> None:
        """Register default endpoints (/healthy, /update, /jobs)."""

        @self.flask.route("/healthy")
        @self._limiter.limit("10 per minute")
        def do_healthy_check() -> tuple[str, int]:
            if healthy_check_func():
                self.flask.logger.debug("Healthy check OK")
                return "OK", 200
            self.flask.logger.warning("Healthy check FAIL")
            return "FAIL", 500

        @self.flask.route("/update")
        @self._limiter.limit("2 per minute")
        def update() -> tuple[str, int]:
            update_now_func()
            return "OK", 200

        @self.flask.route("/jobs")
        @self._limiter.limit("1 per second")
        def printjobs() -> tuple[Response, int]:
            return jsonify({"jobs": get_jobs_func()}), 200

    def add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: Callable | None = None,
        provide_automatic_options: bool | None = None,
        **options: Any,
    ) -> None:
        """Add a custom route to Flask application."""
        self.flask.add_url_rule(
            rule,
            endpoint=endpoint,
            view_func=view_func,
            provide_automatic_options=provide_automatic_options,
            **options,
        )

    def _start_wsgi_server_blocking(self, host: str, port: int) -> None:
        self._trace_log("Start WSGIServer")
        self._wsgi_server = WSGIServer((host, port), self.flask)
        self._wsgi_server.start()
        self._trace_log("WSGIServer stopped")

    def start(self, host: str, port: int) -> None:
        """Start WSGI server in a background thread."""
        self._server_thread = threading.Thread(
            target=self._start_wsgi_server_blocking, args=(host, port)
        )
        self._server_thread.start()

    def stop(self) -> None:
        """Stop WSGI server and join the background thread."""
        self._trace_log("Stop WSGIServer")
        if self._wsgi_server is not None:
            self._wsgi_server.stop()
        if self._server_thread is not None:
            self._server_thread.join()
