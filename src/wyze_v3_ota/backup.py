import time
import urllib.error
import urllib.request
from pathlib import Path

from .constants import STOCK_MTD_LAYOUT, validate_stock_layout
from .util import sha256_file, write_json


def _get(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": "wyze-v3-ota/0.1"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _fetch_static(
    host: str,
    port: int,
    partition_index: int,
    expected_size: int,
    timeout: float,
    deadline: float,
) -> bytes:
    url = f"http://{host}:{port}/ctf-root/mtd{partition_index}.bin"
    last_size = -1
    while time.monotonic() < deadline:
        try:
            data = _get(url, timeout)
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2)
            continue
        last_size = len(data)
        if len(data) == expected_size:
            return data
        time.sleep(2)
    raise TimeoutError(
        f"{url} stayed at {last_size} bytes; expected {expected_size}"
    )


def fetch_backup(
    host: str,
    out_dir: Path,
    port: int = 8181,
    timeout: float = 30.0,
    total_timeout: float = 300.0,
) -> dict:
    validate_stock_layout()
    out_dir.mkdir(parents=True, exist_ok=True)
    first_dir = out_dir / "copy1"
    second_dir = out_dir / "copy2"
    first_dir.mkdir(exist_ok=True)
    second_dir.mkdir(exist_ok=True)
    deadline = time.monotonic() + total_timeout
    partitions = []

    for partition in STOCK_MTD_LAYOUT:
        first = _fetch_static(
            host,
            port,
            partition.index,
            partition.size,
            timeout,
            deadline,
        )
        second_url = (
            f"http://{host}:{port}/cgi-bin/dump?n={partition.index}"
        )
        second = _get(second_url, max(timeout, partition.size / 100000))
        if len(second) != partition.size:
            raise ValueError(
                f"CGI copy for {partition.name} is {len(second)} bytes; "
                f"expected {partition.size}"
            )
        if first != second:
            raise ValueError(
                f"independent reads for {partition.name} do not match"
            )
        first_path = first_dir / partition.filename
        second_path = second_dir / partition.filename
        first_path.write_bytes(first)
        second_path.write_bytes(second)
        partitions.append(
            {
                "index": partition.index,
                "name": partition.name,
                "size": partition.size,
                "sha256": sha256_file(first_path),
            }
        )

    full_image = out_dir / f"stock-{host.replace('.', '-')}-16MiB.bin"
    with full_image.open("wb") as handle:
        for partition in STOCK_MTD_LAYOUT:
            handle.write((first_dir / partition.filename).read_bytes())
    manifest = {
        "host": host,
        "model": "HL_PAN3",
        "partitions": partitions,
        "image": {
            "path": str(full_image),
            "size": full_image.stat().st_size,
            "sha256": sha256_file(full_image),
        },
    }
    write_json(out_dir / "backup-manifest.json", manifest)
    return manifest


def verify_backup(manifest_path: Path) -> dict:
    from .util import read_json

    manifest = read_json(manifest_path)
    image = Path(manifest["image"]["path"])
    if image.stat().st_size != 0x1000000:
        raise ValueError("backup image is not exactly 16 MiB")
    if sha256_file(image) != manifest["image"]["sha256"]:
        raise ValueError("backup image hash does not match manifest")
    return manifest
