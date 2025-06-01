#!/usr/bin/env bash
echo "Set password for tavern and myapp"
mosquitto_passwd -b tests/integration/mosquitto/mosquitto.passwd tavern tavern123
mosquitto_passwd -b tests/integration/mosquitto/mosquitto.passwd myapp myapp123

echo "Run mosquitto"
mosquitto -c tests/integration/mosquitto/mosquitto.conf &
