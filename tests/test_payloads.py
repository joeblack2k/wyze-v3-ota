import hashlib
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wyze_v3_ota.constants import (  # noqa: E402
    FULL_FLASH_SIZE,
    STOCK_MTD_LAYOUT,
    THINGINO_ROOTFS_OFFSET,
)
from wyze_v3_ota.image import (  # noqa: E402
    build_rootcheck_payload,
    build_thingino_payload,
)
from wyze_v3_ota.ota import payload_url, upgrade_action  # noqa: E402


def synthetic_image() -> bytes:
    image = bytearray((index * 37 + 11) & 0xFF for index in range(FULL_FLASH_SIZE))
    image[THINGINO_ROOTFS_OFFSET : THINGINO_ROOTFS_OFFSET + 4] = b"hsqs"
    return bytes(image)


class PayloadTests(unittest.TestCase):
    def test_rootcheck_tar_contains_only_diagnostic_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "rootcheck.tar"
            result = build_rootcheck_payload(target, "http://10.0.0.2:8080/hit")
            with tarfile.open(target) as archive:
                names = sorted(archive.getnames())
                script = archive.extractfile(
                    "Upgrade/upgraderun.sh"
                ).read().decode()
            self.assertEqual(
                names,
                [
                    "Upgrade",
                    "Upgrade/cat.cgi",
                    "Upgrade/dump.cgi",
                    "Upgrade/status.cgi",
                    "Upgrade/upgraderun.sh",
                ],
            )
            self.assertIn("mtdblock", script)
            self.assertIn("/tmp/ctf", script)
            self.assertIn("http://10.0.0.2:8080/hit", script)
            self.assertEqual(
                result["md5"], hashlib.md5(target.read_bytes()).hexdigest()
            )

    def test_flash_tar_contains_exact_stock_slices(self) -> None:
        image = synthetic_image()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "thingino.bin"
            source.write_bytes(image)
            target = root / "thingino-ota.tar"
            result = build_thingino_payload(source, root / "build", target)
            with tarfile.open(target) as archive:
                for partition in STOCK_MTD_LAYOUT:
                    member = archive.getmember(
                        f"Upgrade/{partition.image_filename}"
                    )
                    self.assertEqual(member.size, partition.size)
                    data = archive.extractfile(member).read()
                    self.assertEqual(
                        data,
                        image[
                            partition.offset : partition.offset + partition.size
                        ],
                    )
                script = archive.extractfile(
                    "Upgrade/upgraderun.sh"
                ).read().decode()
            self.assertIn('flash_partition 0 ', script)
            self.assertLess(
                script.index("flash_partition 1 "),
                script.index("flash_partition 0 "),
            )
            self.assertEqual(
                result["md5"], hashlib.md5(target.read_bytes()).hexdigest()
            )

    def test_action_shape(self) -> None:
        action = upgrade_action("https://example.test/update.tar", "a" * 32)
        self.assertEqual(action["method"], "METHOD_ACTION")
        self.assertEqual(action["params"]["model"], "HL_PAN3")
        self.assertEqual(action["params"]["firmwareEncryptType"], 0)

    def test_payload_url(self) -> None:
        self.assertEqual(
            payload_url("example.test", "x.tar", 8443),
            "https://example.test:8443/x.tar",
        )


if __name__ == "__main__":
    unittest.main()
