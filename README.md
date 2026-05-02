# mqtt-communication-checker

Local dev helper to publish signed MQTT messages for existing sensors and verify that the local stores were updated.

It does not create sensors. It reads existing documents from MongoDB database `sensors`, collection `sensors`.

## Requirements

Local services must already be running:

- Mosquitto
- MongoDB
- RabbitMQ
- `producer`
- `consumer`
- `online-receiver` if you want to verify the `online/.../features/...` Redis path
- Redis for online verification
- Registered AC and/or thermostat controller documents if you want to verify commands

Install Python dependencies:

```bash
poetry install
```

Run:

```bash
poetry run mqtt-communication-checker
```

Useful environment overrides:

```bash
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USERNAME=device_pubsub
MQTT_PASSWORD='DevicePassword1!'
MONGO_URI='mongodb://localhost:27017'
MONGO_DB=sensors
CONTROLLERS_MONGO_DB=controllers
CONTROLLERS_COLLECTION=controllers
REDIS_URL='redis://localhost:6379'
AMQP_URI='amqp://localhost:5672'
RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
PRODUCER_PROCESS_PATTERN=producer
CONSUMER_PROCESS_PATTERN=consumer
ONLINE_RECEIVER_HEALTH_URL='http://localhost:8088/keepalive'
PRODUCER_HEALTH_URL=
CONSUMER_HEALTH_URL=
REQUIRE_PREFLIGHT=true
```

Before publishing messages, the script checks that the local stack is up:

- Mosquitto: TCP connect to `MQTT_HOST:MQTT_PORT`
- RabbitMQ: TCP connect to `RABBITMQ_HOST:RABBITMQ_PORT`, or `AMQP_URI` when host/port are not set
- MongoDB: `ping`
- Redis: `PING`
- `producer`: process-name check using `PRODUCER_PROCESS_PATTERN`, or `PRODUCER_HEALTH_URL` if set
- `consumer`: process-name check using `CONSUMER_PROCESS_PATTERN`, or `CONSUMER_HEALTH_URL` if set
- `online-receiver`: HTTP check using `ONLINE_RECEIVER_HEALTH_URL`

Set `REQUIRE_PREFLIGHT=false` to print preflight failures but continue with the MQTT checks.

The script publishes one fixed sensor value for each existing feature:

- `temperature`: `21.5`
- `humidity`: `55.5`
- `light`: `123.4`
- `airpressure`: `1013.25`
- `motion`: `1`
- `airquality`: `2`

For `online`, it publishes the dedicated online status topic and verifies Redis:

- online status topic: `online/{deviceUuid}/features/{featureUuid}`

If a Mongo verification fails, the script stops immediately. That usually means the MQTT message was accepted by Mosquitto but the producer, RabbitMQ, or consumer hop did not complete.

The script also checks controller commands for registered AC and thermostat devices. It reads existing documents from MongoDB database `controllers`, collection `controllers`, sets each command value in DB, verifies `status.value`, and publishes the signed MQTT command array to:

- command topic: `devices/{deviceUuid}/values`

Command values used for AC devices (`ac-beko`, `ac-lg`):

- `on`: `1`
- `setpoint`: `27`
- `mode`: `1`
- `fanSpeed`: `1`

Command values used for thermostat devices:

- `setpoint`: `22.4`
- `tolerance`: `2`
