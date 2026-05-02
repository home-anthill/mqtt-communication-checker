import hashlib
import hmac
import json
import os
import secrets
import sys
import time

import paho.mqtt.publish as publish
import redis
from pymongo import MongoClient


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


def env(name, default):
    return os.environ.get(name, default)


def build_signed_message(api_token, device_uuid, feature_uuid, payload):
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


def main():
    mongo = MongoClient(env("MONGO_URI", "mongodb://localhost:27017"))
    sensors_collection = mongo[env("MONGO_DB", "sensors")]["sensors"]
    redis_client = redis.Redis.from_url(env("REDIS_URL", "redis://localhost:6379"))

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
        message = build_signed_message(sensor["apiToken"], sensor["deviceUuid"], sensor["featureUuid"], payload)
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
        online_message = build_signed_message(
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


if __name__ == "__main__":
    sys.exit(main())
