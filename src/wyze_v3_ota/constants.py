from dataclasses import dataclass


WYZE_MODEL = "HL_PAN3"
FULL_FLASH_SIZE = 0x1000000
THINGINO_ROOTFS_OFFSET = 0x200000
THINGINO_ROOTFS_SIZE = 0x530000


@dataclass(frozen=True)
class MtdPartition:
    index: int
    name: str
    offset: int
    size: int

    @property
    def filename(self) -> str:
        return f"mtd{self.index}.bin"

    @property
    def image_filename(self) -> str:
        return f"mtd{self.index}-{self.name}.bin"


# Layout observed from /proc/mtd on two stock HL_PAN3 cameras.
STOCK_MTD_LAYOUT = (
    MtdPartition(0, "boot", 0x000000, 0x050000),
    MtdPartition(1, "fit", 0x050000, 0x210000),
    MtdPartition(2, "rootfs", 0x260000, 0x6A0000),
    MtdPartition(3, "rback", 0x900000, 0x6A0000),
    MtdPartition(4, "cfg", 0xFA0000, 0x050000),
    MtdPartition(5, "oem", 0xFF0000, 0x010000),
)


def validate_stock_layout() -> None:
    cursor = 0
    for partition in STOCK_MTD_LAYOUT:
        if partition.offset != cursor:
            raise ValueError(f"non-contiguous partition {partition.name}")
        cursor += partition.size
    if cursor != FULL_FLASH_SIZE:
        raise ValueError(f"layout covers {cursor} bytes, expected {FULL_FLASH_SIZE}")
