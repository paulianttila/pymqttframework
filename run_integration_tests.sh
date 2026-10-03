#!/usr/bin/env bash

# exit when any command fails
set -e

PWD=$(pwd)

# set configuration for test app
export CFG_MQTT_BROKER_URL=localhost
export CFG_MQTT_BROKER_PORT=1884
export CFG_MQTT_USERNAME=myapp
export CFG_MQTT_PASSWORD=myapp123
export CFG_MQTT_TLS_ENABLED=True
export CFG_MQTT_TLS_CA_CERTS=${PWD}/tests/integration/mosquitto/cert/ca/ca.crt
export CFG_MQTT_TLS_CERTFILE=${PWD}/tests/integration/mosquitto/cert/client/client.crt
export CFG_MQTT_TLS_KEYFILE=${PWD}/tests/integration/mosquitto/cert/client/client.key
export CFG_WEB_STATIC_DIR=${PWD}/example/web/static
export CFG_WEB_TEMPLATE_DIR=${PWD}/example/web/templates
export CFG_WEB_PORT=8080
export CFG_LOG_LEVEL=TRACE
export CFG_UPDATE_INTERVAL=1
export CFG_UPDATE_CRON_SCHEDULE="* * * * * *"
export CFG_DELAY_BEFORE_FIRST_TRY=1

MOSQUITTO_PID=
TEST_APP_PID=

is_port_open() {
  local port=$1
  python3 -c "import socket; s = socket.socket(); s.settimeout(0.5); exit(0 if s.connect_ex(('127.0.0.1', ${port})) == 0 else 1)" 2>/dev/null
}

start_mosquitto() {
  if is_port_open 1884; then
    echo "Mosquitto broker already running on port 1884"
    return
  fi

  if ! command -v mosquitto >/dev/null 2>&1; then
    echo "Error: 'mosquitto' command not found." >&2
    echo "Install via 'brew install mosquitto' on macOS or 'apt-get install mosquitto' on Linux." >&2
    exit 1
  fi

  echo "Setting up Mosquitto passwords..."
  chmod 0600 tests/integration/mosquitto/mosquitto.passwd 2>/dev/null || true
  mosquitto_passwd -b tests/integration/mosquitto/mosquitto.passwd tavern tavern123
  mosquitto_passwd -b tests/integration/mosquitto/mosquitto.passwd myapp myapp123

  echo "Starting Mosquitto broker on port 1884..."
  mosquitto -c tests/integration/mosquitto/mosquitto.conf >/dev/null 2>&1 &
  MOSQUITTO_PID=$!
  echo "Mosquitto PID=${MOSQUITTO_PID}"

  echo "Waiting for Mosquitto to be ready..."
  for i in {1..50}; do
    if is_port_open 1884; then
      echo "Mosquitto is ready"
      return
    fi
    sleep 0.1
  done

  echo "Error: Timed out waiting for Mosquitto to start on port 1884" >&2
  exit 1
}

start_test_app() {
  echo "Starting test app..."
  cd tests/integration/testapp
  uv run main.py &
  TEST_APP_PID=$!
  echo "Test app PID=${TEST_APP_PID}"
  cd ../../..

  echo "Waiting for test app to be ready on port 8080..."
  for i in {1..50}; do
    if is_port_open 8080; then
      echo "Test app is ready"
      return
    fi
    sleep 0.1
  done

  echo "Error: Timed out waiting for test app on port 8080" >&2
  exit 1
}

run_tests() {
  # add testing_utils.py to tavern tests
  export PYTHONPATH=${PYTHONPATH}:${PWD}/tests/integration/

  # run tests
  echo "Running Tavern integration tests..."
  uv tool run --from tavern tavern-ci tests/integration/integration-tests.tavern.yaml
}

clean_up() {
  echo "Cleaning up processes..."
  if [ -n "${TEST_APP_PID}" ]; then
    echo "Stopping test app (PID=${TEST_APP_PID})..."
    kill "${TEST_APP_PID}" 2>/dev/null || true
  fi
  if [ -n "${MOSQUITTO_PID}" ]; then
    echo "Stopping Mosquitto (PID=${MOSQUITTO_PID})..."
    kill "${MOSQUITTO_PID}" 2>/dev/null || true
  fi
}

trap clean_up EXIT INT TERM

echo "Current folder: ${PWD}"

start_mosquitto
start_test_app
run_tests
