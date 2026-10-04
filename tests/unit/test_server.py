from unittest.mock import MagicMock, patch
from prometheus_client import CollectorRegistry
from pymqttframework.server import WebServer


def test_server_routes_and_metrics() -> None:
    server = WebServer()
    server.init_limiter()
    registry = CollectorRegistry()
    server.init_metrics(registry)

    healthy_mock = MagicMock(return_value=True)
    update_mock = MagicMock()
    jobs_mock = MagicMock(return_value=[{"id": "1", "name": "job"}])

    server.register_routes(
        healthy_check_func=healthy_mock,
        update_now_func=update_mock,
        get_jobs_func=jobs_mock,
    )

    client = server.flask.test_client()

    # Test /healthy OK
    res = client.get("/healthy")
    assert res.status_code == 200
    assert res.data == b"OK"
    healthy_mock.assert_called_once()

    # Test /healthy FAIL
    healthy_mock.return_value = False
    res = client.get("/healthy")
    assert res.status_code == 500
    assert res.data == b"FAIL"

    # Test /update
    res = client.get("/update")
    assert res.status_code == 200
    assert res.data == b"OK"
    update_mock.assert_called_once()

    # Test /jobs
    res = client.get("/jobs")
    assert res.status_code == 200
    data = res.get_json()
    assert data == {"jobs": [{"id": "1", "name": "job"}]}


def test_limiter_honors_config() -> None:
    server = WebServer()
    server.flask.config["RATELIMIT_ENABLED"] = False
    server.init_limiter()
    assert server._limiter.enabled is False


def test_server_start_stop() -> None:
    server = WebServer()
    with patch("pymqttframework.server.WSGIServer") as mock_wsgi:
        mock_instance = MagicMock()
        mock_wsgi.return_value = mock_instance
        server.start(host="127.0.0.1", port=9999)
        assert server._server_thread is not None
        server.stop()
        mock_instance.stop.assert_called_once()


def test_server_stop_before_start() -> None:
    server = WebServer()
    server.stop()
    with patch("pymqttframework.server.WSGIServer") as mock_wsgi:
        server.start(host="127.0.0.1", port=9999)
        mock_wsgi.assert_not_called()
        assert server._server_thread is None
