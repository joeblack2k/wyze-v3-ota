import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wyze_v3_ota.bundle import build_ctf_kit  # noqa: E402
from wyze_v3_ota.constants import (  # noqa: E402
    FULL_FLASH_SIZE,
    THINGINO_ROOTFS_OFFSET,
)


def synthetic_image() -> bytes:
    image = bytearray(FULL_FLASH_SIZE)
    image[THINGINO_ROOTFS_OFFSET : THINGINO_ROOTFS_OFFSET + 4] = b"hsqs"
    return bytes(image)


class BundleTests(unittest.TestCase):
    def test_offline_kit_contains_source_payloads_and_pki(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "image.bin"
            image.write_bytes(synthetic_image())
            cert = root / "cert.pem"
            key = root / "key.pem"
            cert.write_text("test certificate")
            key.write_text("test key")
            ca_cert = root / "ca-cert.pem"
            ca_key = root / "ca-key.pem"
            ca_cert.write_text("test ca certificate")
            ca_key.write_text("test ca key")
            destination = root / "kit"
            result = build_ctf_kit(
                destination,
                image,
                cert,
                key,
                ca_cert=ca_cert,
                ca_key=ca_key,
                archive=True,
            )
            self.assertTrue((destination / "bin" / "wyze-v3-ota").is_file())
            self.assertTrue((destination / "serve.sh").is_file())
            self.assertTrue(
                (destination / "app" / "wyze_v3_ota" / "cli.py").is_file()
            )
            self.assertTrue(
                (
                    destination
                    / "app"
                    / "wyze_v3_ota"
                    / "payloads"
                    / "dump.cgi"
                ).is_file()
            )
            self.assertTrue((destination / "pki" / "fullchain.pem").is_file())
            self.assertTrue(
                (destination / "pki" / "ca" / "ca-cert.pem").is_file()
            )
            self.assertEqual(
                stat.S_IMODE(
                    (destination / "pki" / "server.key").stat().st_mode
                ),
                0o600,
            )
            self.assertEqual(
                stat.S_IMODE(
                    (destination / "pki" / "ca" / "ca-key.pem")
                    .stat()
                    .st_mode
                ),
                0o600,
            )
            manifest = json.loads(
                (destination / "kit-manifest.json").read_text()
            )
            self.assertIsNone(manifest["wifi_ssid"])
            self.assertFalse(manifest["wifi_psk_in_image"])
            self.assertNotIn("testpass", json.dumps(manifest))
            self.assertTrue(Path(result["archive"]).is_file())


if __name__ == "__main__":
    unittest.main()
