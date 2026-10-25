import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__
from .backup import fetch_backup, verify_backup
from .bundle import build_ctf_kit
from .image import (
    build_thingino_payload,
    patch_wifi,
    prepare,
    write_sd_recovery,
)
from .ota import payload_url, send_upgrade
from .server import serve
from .util import md5_file, sha256_file


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wyze-v3-ota",
        description=(
            "Authorized OTA lab tooling for Wyze Cam Pan v3 (HL_PAN3)."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare_parser = commands.add_parser(
        "prepare", help="prepare Thingino image, OTA payloads and SD recovery"
    )
    prepare_parser.add_argument("--image", type=Path, required=True)
    prepare_parser.add_argument("--build-dir", type=Path, required=True)
    prepare_parser.add_argument("--ssid", default="")
    prepare_parser.add_argument("--psk", default="")
    prepare_parser.add_argument("--callback-url", default="")

    patch_parser = commands.add_parser(
        "patch-wifi", help="patch only wpa_supplicant.conf in a Thingino image"
    )
    patch_parser.add_argument("--image", type=Path, required=True)
    patch_parser.add_argument("--output", type=Path, required=True)
    patch_parser.add_argument("--ssid", required=True)
    patch_parser.add_argument("--psk", required=True)

    serve_parser = commands.add_parser(
        "serve", help="serve HTTPS payloads and the local MQTT broker"
    )
    serve_parser.add_argument("--cert", type=Path, required=True)
    serve_parser.add_argument("--key", type=Path, required=True)
    serve_parser.add_argument("--payload-dir", type=Path, required=True)
    serve_parser.add_argument("--mqtt-port", type=int, default=8883)
    serve_parser.add_argument("--https-port", type=int, default=8443)
    serve_parser.add_argument("--admin-port", type=int, default=8884)
    serve_parser.add_argument("--log", type=Path)

    sessions_parser = commands.add_parser(
        "sessions", help="list MQTT sessions connected to the local broker"
    )
    _add_admin_args(sessions_parser)

    upgrade_parser = commands.add_parser(
        "upgrade", help="publish the proven plaintext upgrade action"
    )
    upgrade_parser.add_argument("--mac", required=True)
    upgrade_parser.add_argument("--url")
    upgrade_parser.add_argument("--md5")
    upgrade_parser.add_argument("--payload", type=Path)
    upgrade_parser.add_argument("--public-host")
    upgrade_parser.add_argument("--https-port", type=int, default=8443)
    _add_admin_args(upgrade_parser)

    backup_parser = commands.add_parser(
        "backup", help="pull and verify two independent stock flash backups"
    )
    backup_parser.add_argument("--host", required=True)
    backup_parser.add_argument("--out-dir", type=Path, required=True)
    backup_parser.add_argument("--port", type=int, default=8181)
    backup_parser.add_argument("--timeout", type=float, default=30)
    backup_parser.add_argument("--total-timeout", type=float, default=300)

    verify_parser = commands.add_parser(
        "verify-backup", help="verify a saved backup manifest and image"
    )
    verify_parser.add_argument("--manifest", type=Path, required=True)

    flash_parser = commands.add_parser(
        "flash", help="send the verified Thingino full-flash OTA payload"
    )
    flash_parser.add_argument("--mac", required=True)
    flash_parser.add_argument("--host", required=True)
    flash_parser.add_argument("--image", type=Path, required=True)
    flash_parser.add_argument("--build-dir", type=Path, required=True)
    flash_parser.add_argument("--backup-manifest", type=Path, required=True)
    flash_parser.add_argument("--public-host", required=True)
    flash_parser.add_argument("--https-port", type=int, default=8443)
    flash_parser.add_argument("--monitor-timeout", type=float, default=300)
    flash_parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm that the verified stock backup exists",
    )
    _add_admin_args(flash_parser)

    sd_parser = commands.add_parser(
        "sd-recovery", help="write autoupdate-full.bin for Thingino U-Boot"
    )
    sd_parser.add_argument("--image", type=Path, required=True)
    sd_parser.add_argument("--out-dir", type=Path, required=True)

    hash_parser = commands.add_parser(
        "hash", help="print size, MD5 and SHA-256 for a file"
    )
    hash_parser.add_argument("file", type=Path)

    kit_parser = commands.add_parser(
        "build-ctf-kit",
        help="build a self-contained offline CTF kit",
    )
    kit_parser.add_argument("--image", type=Path, required=True)
    kit_parser.add_argument("--cert", type=Path, required=True)
    kit_parser.add_argument("--key", type=Path, required=True)
    kit_parser.add_argument("--out-dir", type=Path, required=True)
    kit_parser.add_argument("--ssid", default="")
    kit_parser.add_argument("--psk", default="")
    kit_parser.add_argument("--callback-url", default="")
    kit_parser.add_argument("--ca-cert", type=Path)
    kit_parser.add_argument("--ca-key", type=Path)
    kit_parser.add_argument("--archive", action="store_true")
    return parser


def _add_admin_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--admin-host", default="127.0.0.1")
    parser.add_argument("--admin-port", type=int, default=8884)


def _monitor_flash(host: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://{host}:8282/status.txt", timeout=5
            ) as response:
                current = response.read().decode(errors="replace")
        except (urllib.error.URLError, TimeoutError):
            if last:
                print("flash status endpoint closed after successful progress")
                return
            time.sleep(3)
            continue
        if current != last:
            print(current, end="", flush=True)
            last = current
        if "complete" in current:
            return
        time.sleep(3)
    raise TimeoutError("flash monitor timed out")


def _run(args: argparse.Namespace) -> int:
    if args.command == "prepare":
        _print_json(
            prepare(
                args.image,
                args.build_dir,
                ssid=args.ssid,
                psk=args.psk,
                callback_url=args.callback_url,
            )
        )
        return 0

    if args.command == "patch-wifi":
        _print_json(patch_wifi(args.image, args.output, args.ssid, args.psk))
        return 0

    if args.command == "serve":
        serve(
            args.cert,
            args.key,
            args.payload_dir,
            mqtt_port=args.mqtt_port,
            https_port=args.https_port,
            admin_port=args.admin_port,
            log_path=args.log,
        )
        return 0

    if args.command == "sessions":
        with urllib.request.urlopen(
            f"http://{args.admin_host}:{args.admin_port}/sessions",
            timeout=10,
        ) as response:
            _print_json(json.loads(response.read().decode()))
        return 0

    if args.command == "upgrade":
        url = args.url
        md5 = args.md5
        if args.payload:
            if not args.public_host:
                raise SystemExit("--public-host is required with --payload")
            url = payload_url(
                args.public_host, args.payload.name, args.https_port
            )
            md5 = md5_file(args.payload)
        if not url or not md5:
            raise SystemExit("provide --url/--md5 or --payload/--public-host")
        _print_json(
            send_upgrade(
                args.mac,
                url,
                md5,
                admin_host=args.admin_host,
                admin_port=args.admin_port,
            )
        )
        return 0

    if args.command == "backup":
        _print_json(
            fetch_backup(
                args.host,
                args.out_dir,
                port=args.port,
                timeout=args.timeout,
                total_timeout=args.total_timeout,
            )
        )
        return 0

    if args.command == "verify-backup":
        _print_json(verify_backup(args.manifest))
        return 0

    if args.command == "flash":
        if not args.yes:
            raise SystemExit(
                "refusing to flash without --yes and a verified backup"
            )
        backup = verify_backup(args.backup_manifest)
        if backup["host"] != args.host:
            raise SystemExit(
                f"backup host {backup['host']} does not match --host {args.host}"
            )
        payload = build_thingino_payload(
            args.image,
            args.build_dir,
            args.build_dir / "4.50.18.100.tar",
        )
        _print_json(payload)
        _print_json(
            send_upgrade(
                args.mac,
                payload_url(
                    args.public_host,
                    Path(payload["path"]).name,
                    args.https_port,
                ),
                payload["md5"],
                admin_host=args.admin_host,
                admin_port=args.admin_port,
            )
        )
        time.sleep(5)
        _monitor_flash(args.host, args.monitor_timeout)
        return 0

    if args.command == "sd-recovery":
        _print_json(write_sd_recovery(args.image, args.out_dir))
        return 0

    if args.command == "hash":
        _print_json(
            {
                "path": str(args.file),
                "size": args.file.stat().st_size,
                "md5": md5_file(args.file),
                "sha256": sha256_file(args.file),
            }
        )
        return 0

    if args.command == "build-ctf-kit":
        _print_json(
            build_ctf_kit(
                args.out_dir,
                args.image,
                args.cert,
                args.key,
                ssid=args.ssid,
                psk=args.psk,
                callback_url=args.callback_url,
                ca_cert=args.ca_cert,
                ca_key=args.ca_key,
                archive=args.archive,
            )
        )
        return 0

    raise AssertionError(args.command)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except (ValueError, RuntimeError, TimeoutError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
