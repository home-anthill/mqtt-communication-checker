import argparse
import base64
import hashlib
import hmac
import json
import os
import random
import secrets
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from bson import ObjectId
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import paho.mqtt.publish as publish
from pydantic import BaseModel, ConfigDict, Field
import questionary
import redis
from pymongo import MongoClient
from pymongo.errors import PyMongoError

if TYPE_CHECKING:
    from paho.mqtt.publish import AuthParameter


ONLINE_FEATURE_NAME = "online"
POLL_SECONDS = 20
POLL_INTERVAL_SECONDS = 1
SERVICE_CHECK_TIMEOUT_SECONDS = 3
API_TOKEN_NONCE_SIZE = 12
DEFAULT_API_SERVER_ENV_PATH = Path(__file__).resolve().parents[1].parent / "api-server" / ".env"
API_TOKEN_ENCRYPTION_KEY_MISSING_MESSAGE = """API_TOKEN_ENCRYPTION_KEY is required.
Set it manually, or create ../api-server/.env with API_TOKEN_ENCRYPTION_KEY:
  API_TOKEN_ENCRYPTION_KEY='KEY_FROM_API_SERVER' poetry run mqtt-communication-checker"""

SENSOR_RANDOM_RANGES = {
    "temperature": (18.0, 30.0, 4),
    "humidity": (0.0, 100.0, 1),
    "light": (0.0, 1000.0, 1),
    "airpressure": (300, 1200, 4),
}

INT_FEATURE_RANDOM_VALUES = {
    "motion": [0, 1],
    "airquality": [0, 1, 2, 3],
    "online": [None],
    "on": [0, 1],
    "mode": list(range(0, 5)),
    "tolerance": list(range(0, 11)),
}

MODEL_CONTROLLER_RANDOM_VALUES = {
    "ac-beko": {
        "setpoint": list(range(17, 31)),
        "fanSpeed": [0, 1, 2, 4, 5],
    },
    "ac-lg": {
        "setpoint": list(range(16, 31)),
        "fanSpeed": [10, 2, 0, 5],
    },
}

SUPPORTED_SENSOR_FEATURES = {
    "temperature",
    "humidity",
    "light",
    "motion",
    "airpressure",
    "airquality",
    ONLINE_FEATURE_NAME,
}

SUPPORTED_CONTROLLER_FEATURES = {
    "on",
    "setpoint",
    "mode",
    "fanSpeed",
    "tolerance",
}

SUPPORTED_SPEC_FORMATS = {"bool", "int", "float", "list"}

FEATURE_TYPE_COLORS = {
    "sensor": "fg:ansigreen",
    "controller": "fg:ansiblue",
    "online": "fg:ansimagenta",
}


class ProfileChoice(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: ObjectId
    email: str
    name: str
    login: str
    devices: list[ObjectId] = Field(default_factory=list)
    label: str


class DeviceFeatureChoice(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    profile_id: ObjectId
    device_id: ObjectId
    device_uuid: str
    device_name: str
    mac: str
    model: str
    manufacturer: str
    feature_uuid: str
    feature_name: str
    feature_type: str
    feature_unit: str = ""
    feature: dict[str, Any] = Field(default_factory=dict)
    backing_document: dict[str, Any]


class PlannedFeatureValue(BaseModel):
    selection: DeviceFeatureChoice
    value: Any


def env(name, default):
    return os.environ.get(name, default)


def env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    return int(os.environ.get(name, str(default)))


def decode_base64_with_optional_padding(value, urlsafe):
    padding = "=" * (-len(value) % 4)
    decoder = base64.urlsafe_b64decode if urlsafe else base64.b64decode
    return decoder((value + padding).encode())


def dotenv_value(path, name):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ""

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped.removeprefix("export ").lstrip()

        key, separator, value = stripped.partition("=")
        if not separator or key.strip() != name:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value

    return ""


def raw_api_token_encryption_key():
    key = os.environ.get("API_TOKEN_ENCRYPTION_KEY", "")
    if key:
        return key
    return dotenv_value(DEFAULT_API_SERVER_ENV_PATH, "API_TOKEN_ENCRYPTION_KEY")


def api_token_encryption_key():
    key = raw_api_token_encryption_key()
    if not key:
        raise RuntimeError(API_TOKEN_ENCRYPTION_KEY_MISSING_MESSAGE)

    for urlsafe in (True, False):
        try:
            decoded = decode_base64_with_optional_padding(key, urlsafe)
        except (ValueError, TypeError):
            continue
        if len(decoded) == 32:
            return decoded

    raw = key.encode()
    if len(raw) == 32:
        return raw
    raise RuntimeError("API_TOKEN_ENCRYPTION_KEY must be 32 raw bytes or base64-encoded 32 bytes")


def decrypt_api_token(encrypted):
    raw = decode_base64_with_optional_padding(encrypted, urlsafe=True)
    if len(raw) <= API_TOKEN_NONCE_SIZE:
        raise RuntimeError("encrypted api token is too short")
    nonce = raw[:API_TOKEN_NONCE_SIZE]
    ciphertext = raw[API_TOKEN_NONCE_SIZE:]
    return AESGCM(api_token_encryption_key()).decrypt(nonce, ciphertext, None).decode()


def document_api_token(document, document_name):
    encrypted = document.get("apiTokenEncrypted")
    if not encrypted:
        raise RuntimeError(f"{document_name} document is missing apiTokenEncrypted")
    return decrypt_api_token(encrypted)


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
            ["pgrep", "-xl", pattern],
            check=False,
            capture_output=True,
            text=True,
            timeout=SERVICE_CHECK_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as err:
        return False, f"FAIL {name}: cannot check process pattern '{pattern}' ({err})"

    matches = [line for line in result.stdout.splitlines() if line.strip()]
    if result.returncode == 0 and matches:
        return True, f"OK {name}: process name matched '{pattern}'"
    return False, f"FAIL {name}: no process name matched '{pattern}'"


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


def build_mqtt_signed_message(api_token, device_uuid, feature_uuid, feature_name, payload):
    timestamp = int(time.time())
    nonce = secrets.token_hex(16)
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=False)
    signed_payload = f"{device_uuid}\n{feature_uuid}\n{feature_name}\n{timestamp}\n{nonce}\n{payload_json}"
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
    signature = hmac.new(document_api_token(controller, "controller").encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
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


def mqtt_auth() -> "AuthParameter | None":
    username = env("MQTT_USERNAME", "device_pubsub")
    if not username:
        return None
    return {"username": username, "password": env("MQTT_PASSWORD", "DevicePassword1!")}


def publish_mqtt(topic, message):
    publish.single(
        topic,
        payload=json.dumps(message, separators=(",", ":")),
        qos=1,
        retain=False,
        hostname=env("MQTT_HOST", "localhost"),
        port=int(env("MQTT_PORT", "1883")),
        auth=mqtt_auth(),
    )


def publish_mqtt_json(topic, message):
    publish.single(
        topic,
        payload=json.dumps(message, separators=(",", ":")),
        qos=1,
        retain=False,
        hostname=env("MQTT_HOST", "localhost"),
        port=int(env("MQTT_PORT", "1883")),
        auth=mqtt_auth(),
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
        "_id": controller["_id"],
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


def format_profile_label(document, owned_device_count):
    github = document.get("github") or {}
    email = github.get("email") or "no-email"
    name = github.get("name") or ""
    login = github.get("login") or ""
    identity = name or login or "unnamed"
    profile_id = document.get("_id")
    return f"{email} | {identity} | devices={owned_device_count} | id={profile_id}"


def list_profiles(profiles_collection):
    docs = list(
        profiles_collection.find(
            {},
            {
                "github.email": 1,
                "github.name": 1,
                "github.login": 1,
                "devices": 1,
            },
        ).sort("github.email", 1)
    )
    profiles = []
    for doc in docs:
        github = doc.get("github") or {}
        devices = doc.get("devices") or []
        profiles.append(
            ProfileChoice(
                id=doc["_id"],
                email=github.get("email") or "no-email",
                name=github.get("name") or "",
                login=github.get("login") or "",
                devices=devices,
                label=format_profile_label(doc, len(devices)),
            )
        )
    return profiles


def choose_profile(profiles_collection):
    profiles = list_profiles(profiles_collection)
    if not profiles:
        print("No profiles found in API server MongoDB.")
        return None

    return questionary.select(
        "Select one profile",
        choices=[questionary.Choice(title=profile.label, value=profile) for profile in profiles],
    ).ask()


def device_label(device):
    parts = [
        device.get("name") or "unnamed device",
        f"model={device.get('model') or '-'}",
        f"uuid={device.get('uuid') or '-'}",
        f"mac={device.get('mac') or '-'}",
    ]
    return " | ".join(parts)


def find_feature_document(sensors_collection, controllers_collection, profile, device, feature):
    query = {
        "profileOwnerId": profile.id,
        "deviceUuid": device.get("uuid"),
        "featureUuid": feature.get("uuid"),
        "featureName": feature.get("name"),
    }
    if feature.get("type") == "sensor":
        return sensors_collection.find_one(query)
    if feature.get("type") == "controller":
        return controllers_collection.find_one(query)
    return None


def is_supported_feature(feature):
    feature_name = feature.get("name") or ""
    feature_type = feature.get("type") or ""
    spec_format = (feature.get("spec") or {}).get("format")
    if feature_type in {"sensor", "controller"} and spec_format in SUPPORTED_SPEC_FORMATS:
        return True

    if feature_type == "sensor":
        return feature_name in SUPPORTED_SENSOR_FEATURES
    if feature_type == "controller":
        return feature_name in SUPPORTED_CONTROLLER_FEATURES
    return False


def feature_choice_title(feature):
    feature_name = feature.get("name") or ""
    feature_type = feature.get("type") or ""
    feature_unit = feature.get("unit") or "-"
    feature_uuid = feature.get("uuid") or "-"
    color_key = ONLINE_FEATURE_NAME if feature_name == ONLINE_FEATURE_NAME else feature_type
    color = FEATURE_TYPE_COLORS.get(color_key, "class:text")

    return [
        ("", "  "),
        (color, feature_name),
        ("", " | "),
        (color, feature_type),
        ("", f" | {feature_unit} | {feature_uuid}"),
    ]


def build_feature_choices(api_devices_collection, sensors_collection, controllers_collection, profile):
    if not profile.devices:
        return []

    devices = list(api_devices_collection.find({"_id": {"$in": profile.devices}}).sort("name", 1))
    choices: list[Any] = []
    for device in devices:
        choices.append(questionary.Separator(f"Device: {device_label(device)}"))
        features = sorted(device.get("features") or [], key=lambda item: item.get("order", 0))
        for feature in features:
            title = feature_choice_title(feature)
            if not feature.get("enable", False):
                choices.append(questionary.Choice(title=title, value=None, disabled="disabled feature"))
                continue
            if not is_supported_feature(feature):
                choices.append(questionary.Choice(title=title, value=None, disabled="unsupported feature"))
                continue

            backing_document = find_feature_document(sensors_collection, controllers_collection, profile, device, feature)
            if not backing_document:
                choices.append(questionary.Choice(title=title, value=None, disabled="missing MQTT document"))
                continue

            choices.append(
                questionary.Choice(
                    title=title,
                    value=DeviceFeatureChoice(
                        profile_id=profile.id,
                        device_id=device["_id"],
                        device_uuid=device.get("uuid") or "",
                        device_name=device.get("name") or "",
                        mac=device.get("mac") or "",
                        model=device.get("model") or "",
                        manufacturer=device.get("manufacturer") or "",
                        feature_uuid=feature.get("uuid") or "",
                        feature_name=feature.get("name") or "",
                        feature_type=feature.get("type") or "",
                        feature_unit=feature.get("unit") or "",
                        feature=feature,
                        backing_document=backing_document,
                    ),
                )
            )
    return choices


def choose_features(api_devices_collection, sensors_collection, controllers_collection, profile):
    choices = build_feature_choices(api_devices_collection, sensors_collection, controllers_collection, profile)
    if not choices:
        print(
            "No devices found for the selected profile. Register devices first via the suggested docs/fill-local-db.sh script, "
            "real ESP32 boards running the firmwares, ore via the API."
        )
        return []
    if not any(choice.value is not None and not choice.disabled for choice in choices):
        print("No selectable features found for the selected profile. Check sensor/controller registration documents.")
        return []

    selected = questionary.checkbox(
        "Select features to update",
        choices=choices,
        validate=lambda values: True if values else "Select at least one feature.",
    ).ask()
    return selected or []


def decimal_places(value):
    decimal = Decimal(str(value)).normalize()
    exponent = decimal.as_tuple().exponent
    if not isinstance(exponent, int):
        return 0
    return max(0, -exponent)


def normalize_generated_number(value, spec_format, digits):
    if spec_format == "int" or digits == 0:
        return int(value)
    return round(float(value), digits)


def generate_random_stepped_number(minimum, maximum, step, spec_format):
    minimum_decimal = Decimal(str(minimum))
    maximum_decimal = Decimal(str(maximum))
    step_decimal = Decimal(str(step))
    if step_decimal <= 0:
        raise RuntimeError(f"spec step must be greater than zero: {step}")
    if maximum_decimal < minimum_decimal:
        raise RuntimeError(f"spec max must be greater than or equal to min: min={minimum} max={maximum}")

    steps = int(((maximum_decimal - minimum_decimal) / step_decimal).to_integral_value(rounding=ROUND_FLOOR))
    value = minimum_decimal + (step_decimal * random.randint(0, steps))
    digits = max(decimal_places(minimum), decimal_places(maximum), decimal_places(step))
    return normalize_generated_number(value, spec_format, digits)


def effective_sensor_range(feature_name, minimum, maximum):
    if feature_name not in SENSOR_RANDOM_RANGES:
        return minimum, maximum

    default_minimum, default_maximum, _digits = SENSOR_RANDOM_RANGES[feature_name]
    effective_minimum = max(Decimal(str(minimum)), Decimal(str(default_minimum)))
    effective_maximum = min(Decimal(str(maximum)), Decimal(str(default_maximum)))
    if effective_maximum < effective_minimum:
        raise RuntimeError(
            f"{feature_name} spec range does not overlap supported MQTT range: "
            f"spec min={minimum} max={maximum}, supported min={default_minimum} max={default_maximum}"
        )
    return effective_minimum, effective_maximum


def generate_random_ranged_number(spec, feature_name, spec_format):
    if "min" not in spec or "max" not in spec:
        raise RuntimeError(f"{feature_name} spec requires min and max")

    minimum, maximum = effective_sensor_range(feature_name, spec["min"], spec["max"])
    step = spec.get("step")
    if step is not None:
        return generate_random_stepped_number(minimum, maximum, step, spec_format)

    if maximum < minimum:
        raise RuntimeError(f"spec max must be greater than or equal to min: min={minimum} max={maximum}")
    if spec_format == "int":
        return random.randint(int(minimum), int(maximum))
    return random.uniform(float(minimum), float(maximum))


def normalize_list_value(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def generate_random_spec_value(feature):
    spec = feature.get("spec") or {}
    if not spec:
        return None

    feature_name = feature.get("name") or "unnamed"
    spec_format = spec.get("format")
    if spec_format == "bool":
        return random.choice([0, 1])
    if spec_format in {"int", "float"}:
        return generate_random_ranged_number(spec, feature_name, spec_format)
    if spec_format == "list":
        values = [
            item.get("value")
            for item in spec.get("list") or []
            if isinstance(item, dict) and "value" in item
        ]
        if not values:
            raise RuntimeError(f"{feature_name} list spec requires at least one value")
        return normalize_list_value(random.choice(values))
    raise RuntimeError(f"unsupported spec format for {feature_name}: {spec_format}")


def device_model_key(selection):
    return selection.model.strip().lower()


def generate_random_feature_value(selection):
    feature_name = selection.feature_name
    if feature_name == ONLINE_FEATURE_NAME:
        return None

    model_values = MODEL_CONTROLLER_RANDOM_VALUES.get(device_model_key(selection), {})
    if selection.feature_type == "controller" and feature_name in model_values:
        return random.choice(model_values[feature_name])

    value = generate_random_spec_value(selection.feature)
    if value is not None:
        if feature_name in SENSOR_RANDOM_RANGES:
            return float(value)
        return value

    if feature_name in SENSOR_RANDOM_RANGES:
        minimum, maximum, digits = SENSOR_RANDOM_RANGES[feature_name]
        return round(random.uniform(minimum, maximum), digits)
    if feature_name in INT_FEATURE_RANDOM_VALUES:
        values = INT_FEATURE_RANDOM_VALUES[feature_name]
        return random.choice(values)
    raise RuntimeError(f"unsupported feature value rule: {selection.feature_type}/{feature_name}")


def planned_value_text(value):
    return "online heartbeat" if value is None else str(value)


def plan_selected_feature_values(selections):
    return [
        PlannedFeatureValue(selection=selection, value=generate_random_feature_value(selection))
        for selection in selections
    ]


def print_planned_feature_values(planned_values):
    print("Values to send:")
    for index, planned in enumerate(planned_values, start=1):
        selection = planned.selection
        print(
            f"[{index}/{len(planned_values)}] {selection.device_name or selection.device_uuid} | "
            f"{selection.feature_name} | {selection.feature_type} | {selection.feature_unit or '-'} | "
            f"{selection.feature_uuid} | value={planned_value_text(planned.value)}"
        )


def publish_online_update(online_sensor):
    online_message = build_mqtt_signed_message(
        document_api_token(online_sensor, "online sensor"),
        online_sensor["deviceUuid"],
        online_sensor["featureUuid"],
        ONLINE_FEATURE_NAME,
        {},
    )
    online_topic = f"online/{online_sensor['deviceUuid']}/features/{online_sensor['featureUuid']}"
    print(f"PUBLISH {online_topic}")
    publish_mqtt(online_topic, online_message)
    return online_topic


def set_controller_db_value(collection, controller, expected_value):
    now = datetime.now(timezone.utc)
    result = collection.update_one(
        {
            "_id": controller["_id"],
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


def run_selected_sensor(sensors_collection, redis_client, selection, value):
    sensor = selection.backing_document
    if selection.feature_name == ONLINE_FEATURE_NAME:
        publish_online_update(sensor)
        ok, key = wait_for_redis_online(redis_client, sensor)
        if ok:
            print(f"OK Redis online: key={key}")
            return 0
        print(f"FAIL Redis online: key={key} was not updated")
        return 1

    payload = {"value": value}
    message = build_mqtt_signed_message(
        document_api_token(sensor, "sensor"),
        sensor["deviceUuid"],
        sensor["featureUuid"],
        sensor["featureName"],
        payload,
    )
    topic = f"sensors/{sensor['deviceUuid']}/{sensor['featureName']}"

    print(f"PUBLISH {topic} featureUuid={sensor['featureUuid']} value={value}")
    publish_mqtt(topic, message)

    ok, actual = wait_for_mongo_value(sensors_collection, sensor, value)
    if ok:
        print(f"OK Mongo {selection.feature_name}: value={actual}")
        return 0
    print(f"FAIL Mongo {selection.feature_name}: expected={value}, actual={actual}")
    return 1


def run_selected_controller(controllers_collection, selection, value):
    controller = selection.backing_document
    if not set_controller_db_value(controllers_collection, controller, value):
        print(f"FAIL DB set {selection.model}/{selection.feature_name}: controller document was not updated")
        return 1

    ok, actual = wait_for_controller_value(controllers_collection, controller, value)
    if ok:
        print(f"OK DB {selection.model}/{selection.feature_name}: value={actual}")
    else:
        print(f"FAIL DB {selection.model}/{selection.feature_name}: expected={value}, actual={actual}")
        return 1

    topic = f"devices/{controller['deviceUuid']}/values"
    print(f"PUBLISH {topic} featureUuid={controller['featureUuid']} featureName={controller['featureName']} value={value}")
    publish_mqtt_json(topic, [build_mqtt_signed_command(controller, value)])
    return 0


def run_planned_feature_values(sensors_collection, controllers_collection, redis_client, planned_values):
    failures = 0
    for index, planned in enumerate(planned_values, start=1):
        selection = planned.selection
        value = planned.value
        print(
            f"[{index}/{len(planned_values)}] Sending {selection.device_name or selection.device_uuid} "
            f"{selection.feature_name} ({selection.feature_uuid}) value={planned_value_text(value)}"
        )
        if selection.feature_type == "sensor":
            failures += run_selected_sensor(sensors_collection, redis_client, selection, value)
        elif selection.feature_type == "controller":
            failures += run_selected_controller(controllers_collection, selection, value)
        else:
            failures += 1
            print(f"FAIL unsupported feature type: {selection.feature_type}")

    if failures:
        print(f"Completed with {failures} failure(s).")
        return 1
    print("Completed successfully.")
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    return parser.parse_args(argv)


def main(argv=None):
    try:
        parse_args(argv)
        api_token_encryption_key()

        mongo = MongoClient(env("MONGO_URI", "mongodb://localhost:27017"), serverSelectionTimeoutMS=3000)
        api_server_db = mongo[env("API_SERVER_MONGO_DB", "api-server")]
        profiles_collection = api_server_db[env("PROFILES_COLLECTION", "profiles")]
        api_devices_collection = api_server_db[env("API_DEVICES_COLLECTION", "devices")]
        sensors_collection = mongo[env("MONGO_DB", "sensors")]["sensors"]
        controllers_collection = mongo[env("CONTROLLERS_MONGO_DB", "controllers")][
            env("CONTROLLERS_COLLECTION", "controllers")
        ]

        redis_client = redis.Redis.from_url(env("REDIS_URL", "redis://localhost:6379"))

        preflight_result = run_preflight_checks(mongo, redis_client)
        if preflight_result:
            return preflight_result

        profile = choose_profile(profiles_collection)
        if profile is None:
            return 1

        selections = choose_features(api_devices_collection, sensors_collection, controllers_collection, profile)
        if not selections:
            return 1

        planned_values = plan_selected_feature_values(selections)
        print_planned_feature_values(planned_values)

        return run_planned_feature_values(sensors_collection, controllers_collection, redis_client, planned_values)
    except RuntimeError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
