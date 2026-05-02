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
REDIS_URL='redis://localhost:6379'
```

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
