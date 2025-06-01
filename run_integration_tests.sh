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

TEST_APP_PID=

start_test_app() {
  # start the test app whch use framework
  echo "Start test app"
  cd tests/integration/testapp
  uv run main.py &
  TEST_APP_PID=$!
  echo "PID=${TEST_APP_PID}"
  jobs
  cd ../../..
}

run_tests() {
  # add testing_utils.py to tavern tests
  export PYTHONPATH=${PYTHONPATH}:${PWD}/tests/integration/

  # run tests
  uv tool run --from tavern tavern-ci tests/integration/integration-tests.tavern.yaml
}

clean_up() {
  echo "Stop test app, PID=${TEST_APP_PID}"
  kill ${TEST_APP_PID}
}

echo "Current folder: ${PWD}"

start_test_app
run_tests
clean_up
