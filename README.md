# mqtt-communication-checker

Local dev helper to publish signed MQTT messages for existing device features and verify that the local stores were updated.

It does not create profiles, devices, sensors, or controllers. It reads profiles and device ownership from MongoDB database `api-server`, then joins selected device features to the MQTT-facing `sensors.sensors` and `controllers.controllers` documents.

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
API_TOKEN_ENCRYPTION_KEY='<FROM_API_SERVER_ENV_VAR>' poetry run mqtt-communication-checker
```

The CLI is interactive:

1. It fails immediately if `API_TOKEN_ENCRYPTION_KEY` is missing or invalid.
2. It asks which profile to use. Profiles are listed with GitHub email, name/login, owned-device count, and profile id.
3. It asks which device features to update. Device rows are group headings; check individual features with `Space`, move with `Up`/`Down`, and continue with `Enter`.
4. It generates a valid random value for each selected feature and publishes commands one by one in the displayed order.

Feature rows include the feature UUID next to the feature name.

Useful environment overrides:

```bash
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USERNAME=device_pubsub
MQTT_PASSWORD='DevicePassword1!'
MONGO_URI='mongodb://localhost:27017'
API_SERVER_MONGO_DB=api-server
PROFILES_COLLECTION=profiles
API_DEVICES_COLLECTION=devices
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

Set `REQUIRE_PREFLIGHT=false` to print preflight failures but continue to the interactive prompts.

The script generates random valid values for selected sensor features:

- `temperature`: float in a realistic Celsius range with up to four decimals
- `humidity`: float percentage from `0` to `100` with one decimal
- `light`: decimal lux value from `0` to `1000` with one decimal
- `airpressure`: float hPa value with up to four decimals
- `motion`: `0` or `1`
- `airquality`: integer enum value from `0` to `4`

For `online`, it publishes the dedicated online status topic and verifies Redis:

- online status topic: `online/{deviceUuid}/features/{featureUuid}`

To publish only the online/power-outage update, select only the `online` feature in the interactive feature list.

If a Mongo verification fails, the script stops immediately. That usually means the MQTT message was accepted by Mosquitto but the producer, RabbitMQ, or consumer hop did not complete.

The script also sends controller commands for selected controller features. It reads existing documents from MongoDB database `controllers`, collection `controllers`, sets each command value in DB, verifies `status.value`, and publishes a signed MQTT command array with one command at a time to:

- command topic: `devices/{deviceUuid}/values`

Generated command values include:

- `on`: `0` or `1`
- `setpoint`: random temperature setpoint
- `mode`: random integer enum
- `fanSpeed`: random integer enum
- `tolerance`: random thermostat tolerance
