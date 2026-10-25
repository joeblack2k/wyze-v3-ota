import shutil
import tarfile
from copy import deepcopy
from pathlib import Path

from . import __version__
from .image import prepare
from .util import sha256_file, write_json


PACKAGE_ROOT = Path(__file__).resolve().parent


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _wrapper() -> str:
    return """#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/app${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m wyze_v3_ota "$@"
"""


def _serve_script() -> str:
    return """#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$ROOT/bin/wyze-v3-ota" serve \
  --cert "$ROOT/pki/fullchain.pem" \
  --key "$ROOT/pki/server.key" \
  --payload-dir "$ROOT/build" \
  --log "$ROOT/logs/serve.log"
"""


def _quickstart(ssid: str) -> str:
    wifi = (
        f"The prepared image is configured for SSID {ssid!r}.\n"
        if ssid
        else "The prepared image uses its existing WiFi configuration.\n"
    )
    return f"""wyze-v3-ota offline CTF kit

Runtime requirement: Python 3.11 or newer. No network downloads or pip
packages are required.

{wifi}
Start the MQTT and HTTPS servers:

  ./serve.sh

In another terminal:

  ./bin/wyze-v3-ota sessions
  ./bin/wyze-v3-ota upgrade --mac CAMERA_MAC \\
    --payload build/4.50.18.99.tar \\
    --public-host wyze-firmware-upgrade-service.wyzecam.com
  ./bin/wyze-v3-ota backup --host CAMERA_IP --out-dir backups/CAMERA_MAC
  ./bin/wyze-v3-ota verify-backup \\
    --manifest backups/CAMERA_MAC/backup-manifest.json
  ./bin/wyze-v3-ota flash --mac CAMERA_MAC --host CAMERA_IP \\
    --image build/thingino-wyze-campan3.bin --build-dir build \\
    --backup-manifest backups/CAMERA_MAC/backup-manifest.json \\
    --public-host wyze-firmware-upgrade-service.wyzecam.com --yes

The PKI directory contains the complete leaf certificate chain and leaf key
used by the HTTPS and MQTT listeners. The CA private key is not required to
operate this fixed-hostname kit. When present under pki/ca, it can issue
additional leaf certificates for other authorized hostnames.

Keep this directory private. It contains a TLS private key and a firmware
image with embedded WiFi credentials.
"""


def _archive(kit_dir: Path) -> Path:
    target = kit_dir.parent / f"{kit_dir.name}.tar.gz"
    with tarfile.open(target, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        archive.add(kit_dir, arcname=kit_dir.name)
    target.chmod(0o600)
    return target


def _relative_manifest(manifest: dict) -> dict:
    result = deepcopy(manifest)
    result["image"]["path"] = f"build/{Path(result['image']['path']).name}"
    result["rootcheck"]["path"] = (
        f"build/{Path(result['rootcheck']['path']).name}"
    )
    result["thingino"]["path"] = (
        f"build/{Path(result['thingino']['path']).name}"
    )
    for entry in result["thingino"]["slices"].values():
        entry["path"] = f"build/slices/{Path(entry['path']).name}"
    result["sd_recovery"]["path"] = (
        f"build/sd-recovery/{Path(result['sd_recovery']['path']).name}"
    )
    return result


def build_ctf_kit(
    destination: Path,
    image: Path,
    cert: Path,
    key: Path,
    ssid: str = "",
    psk: str = "",
    callback_url: str = "",
    ca_cert: Path | None = None,
    ca_key: Path | None = None,
    archive: bool = False,
) -> dict:
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    app = destination / "app" / "wyze_v3_ota"
    shutil.copytree(
        PACKAGE_ROOT,
        app,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (destination / "bin").mkdir(exist_ok=True)
    _write_executable(destination / "bin" / "wyze-v3-ota", _wrapper())
    _write_executable(destination / "serve.sh", _serve_script())

    pki = destination / "pki"
    pki.mkdir(exist_ok=True)
    shutil.copyfile(cert, pki / "fullchain.pem")
    shutil.copyfile(key, pki / "server.key")
    (pki / "server.key").chmod(0o600)
    ca_manifest = None
    if ca_cert or ca_key:
        if not ca_cert or not ca_key:
            raise ValueError("ca_cert and ca_key must be provided together")
        ca_dir = pki / "ca"
        ca_dir.mkdir(exist_ok=True)
        cert_target = ca_dir / "ca-cert.pem"
        key_target = ca_dir / "ca-key.pem"
        shutil.copyfile(ca_cert, cert_target)
        shutil.copyfile(ca_key, key_target)
        key_target.chmod(0o600)
        ca_manifest = {
            "certificate": {
                "path": "pki/ca/ca-cert.pem",
                "sha256": sha256_file(cert_target),
            },
            "private_key": {
                "path": "pki/ca/ca-key.pem",
                "mode": "0600",
                "sha256": sha256_file(key_target),
            },
        }

    manifest = _relative_manifest(
        prepare(
            image,
            destination / "build",
            ssid=ssid,
            psk=psk,
            callback_url=callback_url,
        )
    )
    write_json(destination / "build" / "manifest.json", manifest)
    (destination / "logs").mkdir(exist_ok=True)
    (destination / "backups").mkdir(exist_ok=True)
    (destination / "QUICKSTART.txt").write_text(_quickstart(ssid))

    kit_manifest = {
        "kit": "wyze-v3-ota-ctf",
        "version": __version__,
        "runtime": "python>=3.11, stdlib only",
        "wifi_ssid": ssid if ssid else None,
        "wifi_psk_in_image": bool(psk),
        "pki": {
            "fullchain": {
                "path": "pki/fullchain.pem",
                "sha256": sha256_file(pki / "fullchain.pem"),
            },
            "server_key": {
                "path": "pki/server.key",
                "mode": "0600",
                "sha256": sha256_file(pki / "server.key"),
            },
            "ca": ca_manifest,
        },
        "build": manifest,
    }
    write_json(destination / "kit-manifest.json", kit_manifest)

    result = {
        "path": str(destination),
        "manifest": str(destination / "kit-manifest.json"),
        "archive": None,
    }
    if archive:
        result["archive"] = str(_archive(destination))
    return result
