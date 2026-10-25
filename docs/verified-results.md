# Verified results

## End-to-end result

Two Wyze Cam Pan v3 cameras were migrated from stock firmware to Thingino 2
"Figata" through the OTA path implemented here.

Verified on both cameras:

- Thingino boots with an Ingenic T31X kernel.
- GC2053 sensor initialization succeeds.
- ATBM6031 firmware loads and associates with the configured station network.
- SSH root login succeeds.
- Web UI assets and HTTPS listener start.
- RTSP accepts a client on `554`.
- The main RTSP stream is H.264 1920x1080.
- The main RTSP stream includes AAC audio.

## Backup verification

For each camera, all six stock MTD partitions were read twice:

1. from the files created by the RAM diagnostic;
2. directly from `/dev/mtdblockN` through the CGI endpoint.

The two reads were compared byte-for-byte. Both reconstructed images were
exactly 16 MiB.

## Firmware preparation verification

The image-preparation path:

- extracts the complete original SquashFS rootfs;
- rewrites `/etc/wpa_supplicant.conf`;
- rebuilds the rootfs with single-threaded XZ compression;
- performs a complete read-back extraction of the rebuilt rootfs;
- rejects any image if the rebuilt filesystem has an unreadable block;
- rejects a rootfs larger than `0x530000`;
- proves that the six MTD slices reconstruct the source image byte-for-byte.

This read-back check is mandatory. Multi-threaded XZ on a memory-constrained
build host produced unreadable SquashFS data blocks during development; the
single-threaded path plus full verification is the supported method.
