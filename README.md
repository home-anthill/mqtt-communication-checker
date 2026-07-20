<h1 align="center">
  <br>
  <img src="https://github.com/home-anthill/docs/blob/master/icons/logo512.png?raw=true" alt="ks89/home-anthill" width="220">
  <br>
home-anthill
  <br>
mqtt-communication-checker
</h1>


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

Run static type checks:

```bash
poetry run pyrefly check
```

Run:

```bash
poetry run mqtt-communication-checker
```

Run non-interactively for every supported feature on every device in every profile:

```bash
poetry run mqtt-communication-checker --all
```

By default, the checker reads `API_TOKEN_ENCRYPTION_KEY` from `../api-server/.env`.
Set `API_TOKEN_ENCRYPTION_KEY` in the shell to override that value for a single run:

```bash
API_TOKEN_ENCRYPTION_KEY='<FROM_API_SERVER_ENV_VAR>' poetry run mqtt-communication-checker
```

The CLI is interactive:

1. It fails immediately if `API_TOKEN_ENCRYPTION_KEY` is missing from the environment and `../api-server/.env`, or if the resolved value is invalid.
2. It asks which profile to use. Profiles are listed with GitHub email, name/login, owned-device count, and profile id.
3. It asks which device features to update. Device rows are group headings; check individual features with `Space`, move with `Up`/`Down`, and continue with `Enter`.
4. It generates a valid random value for each selected feature and publishes commands one by one in the displayed order.

Feature rows include the feature UUID next to the feature name.

Use `--all` to skip the profile and feature selectors. In this mode, the checker sends every selectable sensor and controller feature across all profiles, and skips features whose values cannot be generated.

Useful environment overrides:

```bash
API_TOKEN_ENCRYPTION_KEY='<FROM_API_SERVER_ENV_VAR>'
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
- `producer`: exact process-name check using `PRODUCER_PROCESS_PATTERN`, or `PRODUCER_HEALTH_URL` if set
- `consumer`: exact process-name check using `CONSUMER_PROCESS_PATTERN`, or `CONSUMER_HEALTH_URL` if set
- `online-receiver`: HTTP check using `ONLINE_RECEIVER_HEALTH_URL`

Set `REQUIRE_PREFLIGHT=false` to print preflight failures but continue to the interactive prompts.

The script first reads each selected device feature's `spec` object and generates a value that fits it:

- `bool`: numeric MQTT value `0` or `1`
- `int`/`float`: random value between `min` and `max`, aligned to `step` when present
- `list`: random item from `list[].value`

For known sensor names, numeric specs are also constrained to the MQTT value ranges supported by the local consumer.
For example, `light` values are generated from the overlap between the device spec and `0` to `1000` lux.

If an older device feature has no `spec`, the script falls back to built-in defaults for known feature names:

- `temperature`: float in a realistic Celsius range with up to four decimals
- `humidity`: float percentage from `0` to `100` with one decimal
- `light`: decimal lux value from `0` to `1000` with one decimal
- `airpressure`: float hPa value with up to four decimals
- `motion`: `0` or `1`
- `airquality`: integer enum value from `0` to `4`
- thermostat sensor `mode`: integer enum from `-1` (cooling fault) to `2` (heating)

For `online`, it publishes the dedicated online status topic and verifies Redis:

- online status topic: `online/{deviceUuid}/features/{featureUuid}`

To publish only the online update, select only the `online` feature in the interactive feature list.

If a Mongo verification fails, the script stops immediately. That usually means the MQTT message was accepted by Mosquitto but the producer, RabbitMQ, or consumer hop did not complete.

The script also sends controller commands for selected controller features. It reads existing documents from MongoDB database `controllers`, collection `controllers`, sets each command value in DB, verifies `status.value`, and publishes a signed MQTT command array with one command at a time to:

- command topic: `devices/{deviceUuid}/values`

Generated command values include:

- `on`: `0` or `1`
- `setpoint`: random temperature setpoint
- `mode`: random integer enum
- `fanSpeed`: random integer enum
- `tolerance`: random thermostat tolerance

For AC controller models, generated command values are constrained to the firmware-supported ranges before any stored device spec is used:

- `ac-lg`: `setpoint` from `16` to `30`, `fanSpeed` values `1`, `2`, `3`, or `4`
- `ac-beko`: `setpoint` from `17` to `30`, `fanSpeed` values `1`, `2`, `3`, `4`, or `5`


## :open_book: Documentation :open_book:

Take a look here [home-anthill/docs](https://github.com/home-anthill/docs)


## :fire: Releases :fire:

GitHub releases [HERE](https://github.com/home-anthill/mqtt-communication-checker/releases)

Versions:

- ??/07/2026 - 2.0.0
- 28/05/2026 - 1.0.0


## :sparkling_heart: A big thank you to :sparkling_heart:

##### the authors of the main icon of this project:

- <a href="https://www.freepik.com/free-vector/underground-ant-nest-with-red-ants_18582279.htm">Image by brgfx</a> from <a href="https://www.freepik.com/" title="Freepik">Freepik</a>


# :copyright: License :copyright:

The MIT License (MIT)

Copyright (c) 2026 Stefano Cappa (Ks89)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NON INFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

<br/>
