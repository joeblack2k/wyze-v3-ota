import json
import urllib.request

from .constants import WYZE_MODEL


def upgrade_action(url: str, md5: str, model: str = WYZE_MODEL) -> dict:
    return {
        "method": "METHOD_ACTION",
        "params": {
            "cmd": "iot-device::upgrade",
            "url": url,
            "md5": md5,
            "model": model,
            "firmwareEncryptType": 0,
        },
    }


def payload_url(public_host: str, filename: str, port: int = 8443) -> str:
    host = public_host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"https://{host}:{port}/{filename}"


def admin_publish(
    admin_host: str,
    admin_port: int,
    client_id: str,
    topic: str,
    payload: dict | str | bytes,
) -> dict:
    if isinstance(payload, bytes):
        payload_value: dict = {"payload_hex": payload.hex()}
    elif isinstance(payload, str):
        payload_value = {"payload": payload}
    else:
        payload_value = {"payload": payload}
    body = json.dumps(
        {
            "client_id": client_id,
            "topic": topic,
            **payload_value,
        },
        separators=(",", ":"),
    ).encode()
    request = urllib.request.Request(
        f"http://{admin_host}:{admin_port}/publish",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def send_upgrade(
    mac: str,
    url: str,
    md5: str,
    admin_host: str = "127.0.0.1",
    admin_port: int = 8884,
    model: str = WYZE_MODEL,
) -> dict:
    identifier = mac.replace(":", "").lower()
    return admin_publish(
        admin_host,
        admin_port,
        identifier,
        f"wyze/{model.lower()}/{identifier}/action",
        upgrade_action(url, md5, model),
    )
