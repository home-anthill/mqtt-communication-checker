import hashlib
import hmac
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

import paho.mqtt.publish as publish
import redis
from pymongo import MongoClient
from pymongo.errors import PyMongoError


SENSOR_FEATURE_VALUES = {
    "temperature": 21.5,
    "humidity": 55.5,
    "light": 123.4,
    "airpressure": 1013.25,
    "motion": 1,
    "airquality": 2,
}

FLOAT_FEATURES = {"temperature", "humidity", "light", "airpressure"}
ONLINE_FEATURE_NAME = "online"
POLL_SECONDS = 20
POLL_INTERVAL_SECONDS = 1
SERVICE_CHECK_TIMEOUT_SECONDS = 3

COMMAND_FEATURE_VALUES_BY_MODEL = {
    "ac-beko": {
        "on": 1,
        "setpoint": 27,
        "mode": 1,
        "fanSpeed": 1,
    },
    "ac-lg": {
        "on": 1,
        "setpoint": 27,
        "mode": 1,
        "fanSpeed": 1,
    },
    "thermostat": {
        "setpoint": 22.4,
        "tolerance": 2,
    },
}


def env(name, default):
    return os.environ.get(name, default)


def env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    return int(os.environ.get(name, str(default)))


def parse_host_port_from_uri(uri, default_host, default_port):
    parsed = urlparse(uri)
    return parsed.hostname or default_host, parsed.port or default_port


def check_tcp_service(name, host, port):
    try:
        with socket.create_connection((host, port), timeout=SERVICE_CHECK_TIMEOUT_SECONDS):
            return True, f"OK {name}: {host}:{port} is reachable"
    except OSError as err:
        return False, f"FAIL {name}: {host}:{port} is not reachable ({err})"


def check_mongodb(mongo_client):
    try:
        mongo_client.admin.command("ping")
        return True, "OK MongoDB: ping succeeded"
    except PyMongoError as err:
        return False, f"FAIL MongoDB: ping failed ({err})"


def check_redis(redis_client):
    try:
        redis_client.ping()
        return True, "OK Redis: ping succeeded"
    except redis.RedisError as err:
        return False, f"FAIL Redis: ping failed ({err})"


def check_http_service(name, url):
    try:
        with urlopen(url, timeout=SERVICE_CHECK_TIMEOUT_SECONDS) as response:
            if 200 <= response.status < 300:
                return True, f"OK {name}: {url} returned HTTP {response.status}"
            return False, f"FAIL {name}: {url} returned HTTP {response.status}"
    except (OSError, URLError) as err:
        return False, f"FAIL {name}: {url} is not reachable ({err})"


def check_process(name, pattern):
    try:
        result = subprocess.run(
            ["pgrep", "-fl", pattern],
            check=False,
            capture_output=True,
            text=True,
            timeout=SERVICE_CHECK_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as err:
        return False, f"FAIL {name}: cannot check process pattern '{pattern}' ({err})"

    matches = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode == 0 and matches:
        return True, f"OK {name}: process matched '{pattern}'"
    return False, f"FAIL {name}: no process matched '{pattern}'"


def check_process_or_http(name, process_env, process_default, url_env):
    url = os.environ.get(url_env)
    if url:
        return check_http_service(name, url)
    return check_process(name, env(process_env, process_default))


def run_preflight_checks(mongo_client, redis_client):
    print("Running service preflight checks...")

    mqtt_host = env("MQTT_HOST", "localhost")
    mqtt_port = env_int("MQTT_PORT", 1883)

    rabbit_host, rabbit_port = parse_host_port_from_uri(env("AMQP_URI", "amqp://localhost:5672"), "localhost", 5672)
    rabbit_host = env("RABBITMQ_HOST", rabbit_host)
    rabbit_port = env_int("RABBITMQ_PORT", rabbit_port)

    checks = [
        check_tcp_service("Mosquitto", mqtt_host, mqtt_port),
        check_tcp_service("RabbitMQ", rabbit_host, rabbit_port),
        check_mongodb(mongo_client),
        check_redis(redis_client),
        check_process_or_http("producer", "PRODUCER_PROCESS_PATTERN", "producer", "PRODUCER_HEALTH_URL"),
        check_process_or_http("consumer", "CONSUMER_PROCESS_PATTERN", "consumer", "CONSUMER_HEALTH_URL"),
        check_http_service("online-receiver", env("ONLINE_RECEIVER_HEALTH_URL", "http://localhost:8088/keepalive")),
    ]

    failures = 0
    for ok, message in checks:
        print(message)
        if not ok:
            failures += 1

    if failures and env_bool("REQUIRE_PREFLIGHT", True):
        print(f"Preflight failed with {failures} unavailable service(s).")
        return 1
    if failures:
        print(f"Preflight found {failures} unavailable service(s), continuing because REQUIRE_PREFLIGHT=false.")
    else:
        print("Preflight completed successfully.")
    return 0


def build_mqtt_signed_message(api_token, device_uuid, feature_uuid, payload):
    timestamp = int(time.time())
    nonce = secrets.token_hex(16)
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=False)
    signed_payload = f"{device_uuid}\n{feature_uuid}\n{timestamp}\n{nonce}\n{payload_json}"
    signature = hmac.new(api_token.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return {
        "deviceUuid": device_uuid,
        "featureUuid": feature_uuid,
        "timestamp": timestamp,
        "nonce": nonce,
        "signature": signature,
        "payload": payload,
    }


def build_mqtt_signed_command(controller, value):
    timestamp = int(time.time())
    nonce = secrets.token_hex(16)
    payload = {"value": value}
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=False)
    signed_payload = "\n".join(
        [
            controller["deviceUuid"],
            controller["mac"],
            controller["model"],
            controller["featureUuid"],
            controller["featureName"],
            str(timestamp),
            nonce,
            payload_json,
        ]
    )
    signature = hmac.new(controller["apiToken"].encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return {
        "deviceUuid": controller["deviceUuid"],
        "mac": controller["mac"],
        "model": controller["model"],
        "featureUuid": controller["featureUuid"],
        "featureName": controller["featureName"],
        "timestamp": timestamp,
        "nonce": nonce,
        "signature": signature,
        "payload": payload,
    }


def publish_mqtt(topic, message):
    username = env("MQTT_USERNAME", "device_pubsub")
    password = env("MQTT_PASSWORD", "DevicePassword1!")
    auth = {"username": username, "password": password} if username else None
    publish.single(
        topic,
        payload=json.dumps(message, separators=(",", ":")),
        qos=1,
        retain=False,
        hostname=env("MQTT_HOST", "localhost"),
        port=int(env("MQTT_PORT", "1883")),
        auth=auth,
    )


def publish_mqtt_json(topic, message):
    username = env("MQTT_USERNAME", "device_pubsub")
    password = env("MQTT_PASSWORD", "DevicePassword1!")
    auth = {"username": username, "password": password} if username else None
    publish.single(
        topic,
        payload=json.dumps(message, separators=(",", ":")),
        qos=1,
        retain=False,
        hostname=env("MQTT_HOST", "localhost"),
        port=int(env("MQTT_PORT", "1883")),
        auth=auth,
    )


def wait_for_mongo_value(collection, sensor, expected_value):
    query = {
        "deviceUuid": sensor["deviceUuid"],
        "featureUuid": sensor["featureUuid"],
        "featureName": sensor["featureName"],
    }
    deadline = time.time() + POLL_SECONDS
    while time.time() < deadline:
        found = collection.find_one(query)
        if found and values_match(found.get("value"), expected_value):
            return True, found.get("value")
        time.sleep(POLL_INTERVAL_SECONDS)
    found = collection.find_one(query)
    return False, None if found is None else found.get("value")


def wait_for_controller_value(collection, controller, expected_value):
    query = {
        "apiToken": controller["apiToken"],
        "deviceUuid": controller["deviceUuid"],
        "mac": controller["mac"],
        "featureUuid": controller["featureUuid"],
        "featureName": controller["featureName"],
    }
    deadline = time.time() + POLL_SECONDS
    while time.time() < deadline:
        found = collection.find_one(query)
        actual = ((found or {}).get("status") or {}).get("value")
        if values_match(actual, expected_value):
            return True, actual
        time.sleep(POLL_INTERVAL_SECONDS)
    found = collection.find_one(query)
    return False, None if found is None else (found.get("status") or {}).get("value")


def values_match(actual, expected):
    if isinstance(expected, float):
        return actual is not None and abs(float(actual) - expected) < 0.0001
    return actual == expected


def wait_for_redis_online(redis_client, sensor):
    key = f"online_{sensor['deviceUuid']}_feature_{sensor['featureUuid']}"
    deadline = time.time() + POLL_SECONDS
    while time.time() < deadline:
        data = redis_client.hgetall(key)
        if data and (b"createdAt" in data or b"modifiedAt" in data):
            return True, key
        time.sleep(POLL_INTERVAL_SECONDS)
    return False, key


def get_first_sensor_per_feature(collection, feature_names):
    sensors = {}
    for feature_name in feature_names:
        sensor = collection.find_one({"featureName": feature_name})
        if sensor:
            sensors[feature_name] = sensor
    return sensors


def run_sensor_checks(sensors_collection, redis_client):
    sensors = get_first_sensor_per_feature(sensors_collection, SENSOR_FEATURE_VALUES)
    online_sensor = sensors_collection.find_one({"featureName": ONLINE_FEATURE_NAME})
    if not sensors and not online_sensor:
        print("No existing sensors found. Register devices first, then rerun this script.")
        return 1

    failures = 0
    for feature_name, expected_value in SENSOR_FEATURE_VALUES.items():
        sensor = sensors.get(feature_name)
        if not sensor:
            print(f"SKIP {feature_name}: no existing sensor document found")
            continue

        value = float(expected_value) if feature_name in FLOAT_FEATURES else int(expected_value)
        payload = {"value": value}
        message = build_mqtt_signed_message(sensor["apiToken"], sensor["deviceUuid"], sensor["featureUuid"], payload)
        topic = f"sensors/{sensor['deviceUuid']}/{feature_name}"

        print(f"PUBLISH {topic} value={value}")
        publish_mqtt(topic, message)

        ok, actual = wait_for_mongo_value(sensors_collection, sensor, value)
        if ok:
            print(f"OK Mongo {feature_name}: value={actual}")
        else:
            failures += 1
            print(f"FAIL Mongo {feature_name}: expected={value}, actual={actual}")
            print("Stopping after first Mongo verification failure. Check producer, RabbitMQ, and consumer logs.")
            return 1

    if online_sensor:
        online_message = build_mqtt_signed_message(
            online_sensor["apiToken"],
            online_sensor["deviceUuid"],
            online_sensor["featureUuid"],
            {},
        )
        online_topic = f"online/{online_sensor['deviceUuid']}/features/{online_sensor['featureUuid']}"
        print(f"PUBLISH {online_topic}")
        publish_mqtt(online_topic, online_message)

        ok, key = wait_for_redis_online(redis_client, online_sensor)
        if ok:
            print(f"OK Redis online: key={key}")
        else:
            failures += 1
            print(f"FAIL Redis online: key={key} was not updated")
    else:
        print("SKIP online: no existing online sensor document found")

    if failures:
        print(f"Completed with {failures} failure(s).")
        return 1

    print("Completed successfully.")
    return 0


def get_controller_devices(collection):
    docs = list(
        collection.find(
            {"model": {"$in": list(COMMAND_FEATURE_VALUES_BY_MODEL.keys())}},
            {
                "apiToken": 1,
                "deviceUuid": 1,
                "mac": 1,
                "model": 1,
                "featureUuid": 1,
                "featureName": 1,
                "status": 1,
            },
        )
    )
    devices = {}
    for doc in docs:
        key = (doc["deviceUuid"], doc["mac"], doc["model"])
        devices.setdefault(key, {})[doc["featureName"]] = doc
    return devices


def set_controller_db_value(collection, controller, expected_value):
    now = datetime.now(timezone.utc)
    result = collection.update_one(
        {
            "apiToken": controller["apiToken"],
            "deviceUuid": controller["deviceUuid"],
            "mac": controller["mac"],
            "featureUuid": controller["featureUuid"],
            "featureName": controller["featureName"],
        },
        {
            "$set": {
                "status": {
                    "value": expected_value,
                    "createdAt": now,
                    "modifiedAt": now,
                },
                "modifiedAt": now,
            }
        },
    )
    return result.matched_count == 1


def run_command_checks(controllers_collection):
    devices = get_controller_devices(controllers_collection)
    if not devices:
        print("No existing AC or thermostat controller documents found. Register devices first, then rerun this script.")
        return 0

    failures = 0
    for (device_uuid, mac, model), features in devices.items():
        expected_features = COMMAND_FEATURE_VALUES_BY_MODEL[model]
        print(f"COMMAND DEVICE {model} deviceUuid={device_uuid} mac={mac}")

        commands = []
        for feature_name, expected_value in expected_features.items():
            controller = features.get(feature_name)
            if not controller:
                failures += 1
                print(f"FAIL Command {model}/{feature_name}: no registered controller document found")
                continue

            if not set_controller_db_value(controllers_collection, controller, expected_value):
                failures += 1
                print(f"FAIL DB set {model}/{feature_name}: controller document was not updated")
                continue

            ok, actual = wait_for_controller_value(controllers_collection, controller, expected_value)
            if ok:
                print(f"OK DB {model}/{feature_name}: value={actual}")
            else:
                failures += 1
                print(f"FAIL DB {model}/{feature_name}: expected={expected_value}, actual={actual}")
                continue

            commands.append(build_mqtt_signed_command(controller, expected_value))

        if commands:
            topic = f"devices/{device_uuid}/values"
            print(f"PUBLISH {topic} commands={len(commands)}")
            publish_mqtt_json(topic, commands)

    if failures:
        print(f"Command checks completed with {failures} failure(s).")
        return 1

    print("Command checks completed successfully.")
    return 0


def main():
    mongo = MongoClient(env("MONGO_URI", "mongodb://localhost:27017"), serverSelectionTimeoutMS=3000)
    sensors_collection = mongo[env("MONGO_DB", "sensors")]["sensors"]
    controllers_collection = mongo[env("CONTROLLERS_MONGO_DB", "controllers")][
        env("CONTROLLERS_COLLECTION", "controllers")
    ]
    redis_client = redis.Redis.from_url(env("REDIS_URL", "redis://localhost:6379"))

    preflight_result = run_preflight_checks(mongo, redis_client)
    if preflight_result:
        return preflight_result

    sensor_result = run_sensor_checks(sensors_collection, redis_client)
    command_result = run_command_checks(controllers_collection)
    return 1 if sensor_result or command_result else 0


if __name__ == "__main__":
    sys.exit(main())
