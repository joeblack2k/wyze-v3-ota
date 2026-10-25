import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wyze_v3_ota.constants import (  # noqa: E402
    FULL_FLASH_SIZE,
    STOCK_MTD_LAYOUT,
    validate_stock_layout,
)


class LayoutTests(unittest.TestCase):
    def test_layout_is_contiguous_and_complete(self) -> None:
        validate_stock_layout()
        self.assertEqual(
            sum(partition.size for partition in STOCK_MTD_LAYOUT),
            FULL_FLASH_SIZE,
        )

    def test_expected_partition_names(self) -> None:
        self.assertEqual(
            [partition.name for partition in STOCK_MTD_LAYOUT],
            ["boot", "fit", "rootfs", "rback", "cfg", "oem"],
        )


if __name__ == "__main__":
    unittest.main()
