import json
import socket
import ssl
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .ota import upgrade_action


SESSIONS: dict[str, "Session"] = {}
SESSIONS_LOCK = threading.Lock()
LOG_LOCK = threading.Lock()
LOG_PATH: Path | None = None


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {message}"
    print(line, flush=True)
    if LOG_PATH is None:
        return
    with LOG_LOCK:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def recv_exact(connection: socket.socket, count: int) -> bytes:
    data = b""
    while len(data) < count:
        chunk = connection.recv(count - len(data))
        if not chunk:
            raise ConnectionError("connection closed")
        data += chunk
    return data


def recv_packet(connection: socket.socket) -> tuple[int, bytes]:
    first = recv_exact(connection, 1)[0]
    multiplier = 1
    remaining = 0
    while True:
        byte = recv_exact(connection, 1)[0]
        remaining += (byte & 0x7F) * multiplier
        if not byte & 0x80:
            break
        multiplier *= 128
        if multiplier > 128**3:
            raise ValueError("invalid MQTT remaining length")
    return first, recv_exact(connection, remaining)


def encode_length(value: int) -> bytes:
    encoded = bytearray()
    while True:
        byte = value % 128
        value //= 128
        if value:
            byte |= 0x80
        encoded.append(byte)
        if not value:
            return bytes(encoded)


def mqtt_string(data: bytes, offset: int) -> tuple[str, int]:
    length = struct.unpack("!H", data[offset : offset + 2])[0]
    offset += 2
    value = data[offset : offset + length].decode("utf-8", errors="replace")
    return value, offset + length


def parse_connect(payload: bytes) -> dict:
    protocol, offset = mqtt_string(payload, 0)
    level = payload[offset]
    flags = payload[offset + 1]
    keepalive = struct.unpack("!H", payload[offset + 2 : offset + 4])[0]
    offset += 4
    client_id, offset = mqtt_string(payload, offset)
    if flags & 0x04:
        will_topic, offset = mqtt_string(payload, offset)
        _, offset = mqtt_string(payload, offset)
    else:
        will_topic = None
    if flags & 0x80:
        username, offset = mqtt_string(payload, offset)
    else:
        username = None
    return {
        "protocol": protocol,
        "level": level,
        "keepalive": keepalive,
        "client_id": client_id,
        "will_topic": will_topic,
        "username": username,
    }


def parse_subscribe(payload: bytes) -> tuple[int, list[dict]]:
    packet_id = struct.unpack("!H", payload[:2])[0]
    offset = 2
    topics = []
    while offset < len(payload):
        topic, offset = mqtt_string(payload, offset)
        qos = payload[offset]
        offset += 1
        topics.append({"topic": topic, "qos": qos})
    return packet_id, topics


def publish_packet(topic: str, payload: bytes, packet_id: int) -> bytes:
    topic_bytes = topic.encode()
    body = (
        struct.pack("!H", len(topic_bytes))
        + topic_bytes
        + struct.pack("!H", packet_id)
        + payload
    )
    return b"\x32" + encode_length(len(body)) + body


class Session:
    def __init__(self, connection: socket.socket, peer: str):
        self.connection = connection
        self.peer = peer
        self.client_id = ""
        self.send_lock = threading.Lock()
        self.next_packet_id = 1

    def publish(self, topic: str, payload: bytes) -> None:
        with self.send_lock:
            packet_id = self.next_packet_id
            self.next_packet_id = self.next_packet_id % 65535 + 1
            self.connection.sendall(publish_packet(topic, payload, packet_id))

    def run(self) -> None:
        while True:
            packet_type, body = recv_packet(self.connection)
            kind = packet_type >> 4
            if kind == 1:
                connect = parse_connect(body)
                self.client_id = connect["client_id"]
                with SESSIONS_LOCK:
                    SESSIONS[self.client_id] = self
                log(f"peer={self.peer} CONNECT {json.dumps(connect)}")
                self.connection.sendall(b"\x20\x02\x00\x00")
            elif kind == 8:
                packet_id, topics = parse_subscribe(body)
                log(
                    f"peer={self.peer} SUBSCRIBE id={packet_id} "
                    f"topics={json.dumps(topics)}"
                )
                grants = bytes(min(item["qos"], 1) for item in topics)
                self.connection.sendall(
                    b"\x90"
                    + encode_length(len(grants) + 2)
                    + struct.pack("!H", packet_id)
                    + grants
                )
            elif kind == 3:
                topic, offset = mqtt_string(body, 0)
                qos = (packet_type >> 1) & 0x03
                if qos:
                    packet_id = struct.unpack(
                        "!H", body[offset : offset + 2]
                    )[0]
                    offset += 2
                    self.connection.sendall(
                        b"\x40\x02" + struct.pack("!H", packet_id)
                    )
                log(f"peer={self.peer} PUBLISH topic={topic}")
            elif kind == 4:
                packet_id = struct.unpack("!H", body[:2])[0]
                log(f"peer={self.peer} PUBACK id={packet_id}")
            elif kind == 12:
                self.connection.sendall(b"\xd0\x00")
            elif kind == 14:
                return

    def close(self) -> None:
        if self.client_id:
            with SESSIONS_LOCK:
                if SESSIONS.get(self.client_id) is self:
                    SESSIONS.pop(self.client_id, None)
        try:
            self.connection.close()
        except OSError:
            pass


def handle_mqtt(connection: socket.socket, peer: str) -> None:
    session = Session(connection, peer)
    try:
        session.run()
    except Exception as error:
        log(f"peer={peer} error={error}")
    finally:
        session.close()


class AdminHandler(BaseHTTPRequestHandler):
    def _json(self, value: dict, status: int = 200) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/sessions":
            self.send_error(404)
            return
        with SESSIONS_LOCK:
            sessions = sorted(SESSIONS)
        self._json({"sessions": sessions})

    def do_POST(self) -> None:
        if self.path not in ("/publish", "/upgrade"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length).decode())
        client_id = request.get("client_id", "").replace(":", "").lower()
        if self.path == "/upgrade":
            topic = request.get(
                "topic", f"wyze/hl_pan3/{client_id}/action"
            )
            payload = upgrade_action(
                request["url"],
                request["md5"],
                request.get("model", "HL_PAN3"),
            )
        else:
            topic = request["topic"]
            if "payload_hex" in request:
                payload = bytes.fromhex(request["payload_hex"])
            else:
                payload = request["payload"]
        if not isinstance(payload, bytes):
            if not isinstance(payload, str):
                payload = json.dumps(payload, separators=(",", ":"))
            payload = payload.encode()
        with SESSIONS_LOCK:
            target = SESSIONS.get(client_id)
            sessions = [target] if target else list(SESSIONS.values())
        for session in sessions:
            session.publish(topic, payload)
        log(
            f"admin PUBLISH topic={topic} clients={len(sessions)} "
            f"bytes={len(payload)}"
        )
        self._json({"published": len(sessions)})

    def log_message(self, fmt: str, *args: object) -> None:
        return


class PayloadHandler(BaseHTTPRequestHandler):
    payload_dir: Path

    def do_HEAD(self) -> None:
        self._serve(send_body=False)

    def do_GET(self) -> None:
        self._serve(send_body=True)

    def _serve(self, send_body: bool) -> None:
        path = self.path.split("?", 1)[0]
        name = Path(path).name
        target = self.payload_dir / name
        if not path.endswith(".tar") or target.parent != self.payload_dir:
            self.send_error(404)
            return
        if not target.is_file():
            self.send_error(404)
            return
        log(f"https GET {path} bytes={target.stat().st_size}")
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(target.stat().st_size))
        self.send_header("Connection", "close")
        self.end_headers()
        if send_body:
            with target.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    self.wfile.write(chunk)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def serve(
    cert: Path,
    key: Path,
    payload_dir: Path,
    mqtt_port: int = 8883,
    https_port: int = 8443,
    admin_port: int = 8884,
    log_path: Path | None = None,
) -> None:
    global LOG_PATH
    LOG_PATH = log_path
    payload_dir = payload_dir.resolve()

    payload_handler = type(
        "ConfiguredPayloadHandler",
        (PayloadHandler,),
        {"payload_dir": payload_dir},
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    context.verify_mode = ssl.CERT_NONE

    https = ThreadingHTTPServer(("0.0.0.0", https_port), payload_handler)
    https.socket = context.wrap_socket(https.socket, server_side=True)
    threading.Thread(target=https.serve_forever, daemon=True).start()

    admin = ThreadingHTTPServer(("127.0.0.1", admin_port), AdminHandler)
    threading.Thread(target=admin.serve_forever, daemon=True).start()

    mqtt = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    mqtt.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    mqtt.bind(("0.0.0.0", mqtt_port))
    mqtt.listen(20)
    log(
        f"serving payloads={payload_dir} https=:{https_port} "
        f"mqtt=:{mqtt_port} admin=127.0.0.1:{admin_port}"
    )

    while True:
        raw, peer = mqtt.accept()
        peer_name = f"{peer[0]}:{peer[1]}"
        try:
            connection = context.wrap_socket(raw, server_side=True)
        except Exception as error:
            log(f"peer={peer_name} tls-error={error}")
            raw.close()
            continue
        log(f"peer={peer_name} tls-ok")
        threading.Thread(
            target=handle_mqtt,
            args=(connection, peer_name),
            daemon=True,
        ).start()
