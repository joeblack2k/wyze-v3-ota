import io
import os
import shutil
import subprocess
import tarfile
import tempfile
from importlib.resources import files
from pathlib import Path

from .constants import (
    FULL_FLASH_SIZE,
    STOCK_MTD_LAYOUT,
    THINGINO_ROOTFS_OFFSET,
    THINGINO_ROOTFS_SIZE,
    validate_stock_layout,
)
from .util import md5_file, sha256_file, write_json


def _payload_bytes(name: str) -> bytes:
    return files("wyze_v3_ota").joinpath("payloads", name).read_bytes()


def _add_tar_file(
    archive: tarfile.TarFile,
    name: str,
    data: bytes | Path,
    mode: int = 0o644,
) -> None:
    info = tarfile.TarInfo(name)
    info.uid = 0
    info.gid = 0
    info.mode = mode
    if isinstance(data, Path):
        info.size = data.stat().st_size
        with data.open("rb") as handle:
            archive.addfile(info, handle)
        return
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))


def build_rootcheck_payload(out_path: Path, callback_url: str = "") -> dict:
    callback_command = ""
    if callback_url:
        callback_command = (
            '"$BUSYBOX" wget -q -O /dev/null '
            f'"{callback_url}" > "$OUT/wget.log" 2>&1 &'
        )
    script = _payload_bytes("rootcheck-upgraderun.sh").decode()
    script = script.replace("{{CALLBACK_COMMAND}}", callback_command)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out_path, "w", format=tarfile.GNU_FORMAT) as archive:
        directory = tarfile.TarInfo("Upgrade")
        directory.uid = directory.gid = 0
        directory.mode = 0o755
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        _add_tar_file(archive, "Upgrade/upgraderun.sh", script.encode(), 0o755)
        for name in ("dump.cgi", "cat.cgi", "status.cgi"):
            _add_tar_file(
                archive, f"Upgrade/{name}", _payload_bytes(name), 0o755
            )

    return {
        "path": str(out_path),
        "size": out_path.stat().st_size,
        "md5": md5_file(out_path),
        "sha256": sha256_file(out_path),
    }


def _flash_script(slices: dict[str, Path]) -> bytes:
    validate_stock_layout()
    lines = [
        "#!/bin/sh",
        "",
        "PATH=/bin:/sbin:/usr/bin:/usr/sbin:/system/bin",
        "export PATH",
        "",
        "BUSYBOX=/system/bin/busybox",
        '[ -x "$BUSYBOX" ] || BUSYBOX=/bin/busybox',
        '[ -x "$BUSYBOX" ] || BUSYBOX=/usr/bin/busybox',
        "",
        "SRC=/tmp/Upgrade",
        "OUT=/tmp/thingino-flash",
        'mkdir -p "$OUT"',
        '"$BUSYBOX" httpd -p 0.0.0.0:8282 -h "$OUT" > /dev/null 2>&1 &',
        'echo "starting" > "$OUT/status.txt"',
        "",
        "flash_partition() {",
        "    index=$1",
        "    file=$2",
        "    expected=$3",
        "    expected_size=$4",
        '    actual=$("$BUSYBOX" md5sum "$file")',
        "    actual=${actual%% *}",
        '    if [ "$actual" != "$expected" ]; then',
        '        echo "slice md5 mismatch for mtd$index" > "$OUT/error.txt"',
        "        return 1",
        "    fi",
        '    actual_size=$("$BUSYBOX" wc -c < "$file")',
        '    if [ "$actual_size" -ne "$expected_size" ]; then',
        '        echo "slice size mismatch for mtd$index" > "$OUT/error.txt"',
        "        return 1",
        "    fi",
        "    sync",
        '    flash_eraseall "/dev/mtd$index" >> "$OUT/flash.log" 2>&1 || return 1',
        '    flashcp -v "$file" "/dev/mtd$index" >> "$OUT/flash.log" 2>&1 || return 1',
        "    sync",
        '    echo "mtd$index ok" >> "$OUT/flash.log"',
        '    echo "mtd$index ok" >> "$OUT/status.txt"',
        "}",
        "",
    ]
    for partition in STOCK_MTD_LAYOUT:
        lines.append(
            f'grep -q \'mtd{partition.index}: {partition.size:08x} '
            f'00008000 "{partition.name}"\' /proc/mtd || exit 1'
        )
    lines.extend(
        [
            "",
            'cat /proc/mtd > "$OUT/mtd-before.txt"',
            "umount -l /configs 2>/dev/null || true",
            "",
        ]
    )
    write_order = (4, 5, 2, 3, 1, 0)
    for index in write_order:
        partition = STOCK_MTD_LAYOUT[index]
        slice_path = slices[partition.image_filename]
        lines.append(
            f'flash_partition {index} "$SRC/{partition.image_filename}" '
            f"{md5_file(slice_path)} {partition.size} || exit 1"
        )
    lines.extend(
        [
            "",
            "sync",
            "sync",
            'echo "complete" >> "$OUT/status.txt"',
            "reboot -f",
            "",
        ]
    )
    return "\n".join(lines).encode()


def split_image(image_path: Path, out_dir: Path) -> dict[str, Path]:
    validate_stock_layout()
    data = image_path.read_bytes()
    if len(data) != FULL_FLASH_SIZE:
        raise ValueError(
            f"{image_path} is {len(data)} bytes; expected {FULL_FLASH_SIZE}"
        )
    if data[THINGINO_ROOTFS_OFFSET : THINGINO_ROOTFS_OFFSET + 4] != b"hsqs":
        raise ValueError("SquashFS magic not found at image offset 0x200000")
    out_dir.mkdir(parents=True, exist_ok=True)
    slices: dict[str, Path] = {}
    for partition in STOCK_MTD_LAYOUT:
        path = out_dir / partition.image_filename
        path.write_bytes(
            data[partition.offset : partition.offset + partition.size]
        )
        slices[partition.image_filename] = path

    reconstructed = b"".join(path.read_bytes() for path in slices.values())
    if reconstructed != data:
        raise ValueError("split image does not reconstruct byte-for-byte")
    return slices


def build_thingino_payload(
    image_path: Path, build_dir: Path, out_path: Path
) -> dict:
    build_dir.mkdir(parents=True, exist_ok=True)
    slices = split_image(image_path, build_dir / "slices")
    script = _flash_script(slices)

    with tarfile.open(out_path, "w", format=tarfile.GNU_FORMAT) as archive:
        directory = tarfile.TarInfo("Upgrade")
        directory.uid = directory.gid = 0
        directory.mode = 0o755
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        _add_tar_file(archive, "Upgrade/upgraderun.sh", script, 0o755)
        for partition in STOCK_MTD_LAYOUT:
            _add_tar_file(
                archive,
                f"Upgrade/{partition.image_filename}",
                slices[partition.image_filename],
            )

    return {
        "path": str(out_path),
        "size": out_path.stat().st_size,
        "md5": md5_file(out_path),
        "sha256": sha256_file(out_path),
        "slices": {
            name: {
                "path": str(path),
                "size": path.stat().st_size,
                "md5": md5_file(path),
            }
            for name, path in slices.items()
        },
    }


def patch_wifi(
    source_image: Path,
    output_image: Path,
    ssid: str,
    psk: str,
    unsquashfs: str | None = None,
    mksquashfs: str | None = None,
) -> dict:
    unsquashfs = unsquashfs or os.environ.get("UNSQUASHFS") or shutil.which(
        "unsquashfs"
    )
    mksquashfs = mksquashfs or os.environ.get("MKSQUASHFS") or shutil.which(
        "mksquashfs"
    )
    if not unsquashfs or not mksquashfs:
        raise RuntimeError(
            "unsquashfs and mksquashfs are required to patch WiFi credentials"
        )
    if not ssid or not psk:
        raise ValueError("both SSID and PSK must be non-empty")

    image = bytearray(source_image.read_bytes())
    if len(image) != FULL_FLASH_SIZE:
        raise ValueError(f"expected {FULL_FLASH_SIZE} image bytes")
    partition = image[
        THINGINO_ROOTFS_OFFSET : THINGINO_ROOTFS_OFFSET + THINGINO_ROOTFS_SIZE
    ]

    with tempfile.TemporaryDirectory(prefix="wyze-v3-rootfs.") as temporary:
        root = Path(temporary)
        rootfs = root / "rootfs.sqfs"
        rootfs.write_bytes(partition)
        extracted = root / "root"
        subprocess.run(
            [
                unsquashfs,
                "-processors",
                "1",
                "-no-xattrs",
                "-f",
                "-d",
                str(extracted),
                str(rootfs),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        wpa = extracted / "etc" / "wpa_supplicant.conf"
        wpa.parent.mkdir(parents=True, exist_ok=True)
        wpa.write_text(
            "ctrl_interface=/var/run/wpa_supplicant\n"
            "ap_scan=1\n\n"
            "network={\n"
            f'  ssid="{ssid}"\n'
            f'  psk="{psk}"\n'
            "  key_mgmt=WPA-PSK\n"
            "  proto=WPA2\n"
            "  pairwise=CCMP\n"
            "  group=CCMP\n"
            "}\n"
        )
        rebuilt = root / "custom.sqfs"
        subprocess.run(
            [
                mksquashfs,
                str(extracted),
                str(rebuilt),
                "-noappend",
                "-comp",
                "xz",
                "-b",
                "262144",
                "-all-root",
                "-processors",
                "1",
                "-no-progress",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        rebuilt_data = rebuilt.read_bytes()
        if len(rebuilt_data) > THINGINO_ROOTFS_SIZE:
            raise ValueError(
                f"rebuilt rootfs is {len(rebuilt_data)} bytes; "
                f"partition limit is {THINGINO_ROOTFS_SIZE}"
            )
        verify_root = root / "verify"
        subprocess.run(
            [
                unsquashfs,
                "-processors",
                "1",
                "-no-xattrs",
                "-f",
                "-d",
                str(verify_root),
                str(rebuilt),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        if (verify_root / "etc" / "wpa_supplicant.conf").read_text() != (
            wpa.read_text()
        ):
            raise ValueError("rebuilt rootfs failed WiFi read-back verification")
        start = THINGINO_ROOTFS_OFFSET
        end = start + THINGINO_ROOTFS_SIZE
        image[start:end] = b"\0" * THINGINO_ROOTFS_SIZE
        image[start : start + len(rebuilt_data)] = rebuilt_data

    output_image.write_bytes(image)
    return {
        "path": str(output_image),
        "size": output_image.stat().st_size,
        "sha256": sha256_file(output_image),
    }


def write_sd_recovery(image_path: Path, out_dir: Path) -> dict:
    if image_path.stat().st_size != FULL_FLASH_SIZE:
        raise ValueError("recovery image must be exactly 16 MiB")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "autoupdate-full.bin"
    shutil.copyfile(image_path, target)
    return {
        "path": str(target),
        "size": target.stat().st_size,
        "sha256": sha256_file(target),
    }


def prepare(
    image_path: Path,
    build_dir: Path,
    ssid: str = "",
    psk: str = "",
    callback_url: str = "",
) -> dict:
    build_dir.mkdir(parents=True, exist_ok=True)
    prepared_image = build_dir / "thingino-wyze-campan3.bin"
    if ssid or psk:
        patch_wifi(image_path, prepared_image, ssid, psk)
    else:
        shutil.copyfile(image_path, prepared_image)
    if prepared_image.stat().st_size != FULL_FLASH_SIZE:
        raise ValueError("prepared image must be exactly 16 MiB")

    rootcheck = build_rootcheck_payload(
        build_dir / "4.50.18.99.tar", callback_url
    )
    thingino = build_thingino_payload(
        prepared_image, build_dir, build_dir / "4.50.18.100.tar"
    )
    recovery = write_sd_recovery(prepared_image, build_dir / "sd-recovery")
    manifest = {
        "model": "HL_PAN3",
        "image": {
            "path": str(prepared_image),
            "size": prepared_image.stat().st_size,
            "sha256": sha256_file(prepared_image),
        },
        "rootcheck": rootcheck,
        "thingino": thingino,
        "sd_recovery": recovery,
    }
    write_json(build_dir / "manifest.json", manifest)
    return manifest
