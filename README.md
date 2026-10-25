# wyze-v3-ota

Authorized lab tooling for replacing the stock firmware on a **Wyze Cam Pan v3
(`HL_PAN3`, Ingenic T31X, GC2053, ATBM6031)** with **Thingino**.

The workflow in this repository was verified end-to-end on two Pan v3 cameras.
Both booted Thingino 2 "Figata", connected to WiFi, accepted SSH, exposed the
web UI, and produced a 1080p H.264 + AAC RTSP stream.

> Use this only on devices you own or are explicitly authorized to test.
> Flashing firmware can permanently brick a camera. A verified full-flash
> backup is mandatory before using the flash command.

## What worked

The working path uses three properties of the stock update flow:

1. The camera trusts the MQTT broker after `aws-iot.wyzecam.com` is redirected
   to the lab server.
2. The camera accepts a plaintext `METHOD_ACTION` command on its local broker
   session.
3. The stock updater downloads a `.tar`, extracts `Upgrade/upgraderun.sh`, and
   executes that script as root.

The tool therefore:

- serves an HTTPS payload and a minimal MQTT broker;
- sends the proven `iot-device::upgrade` command with an operator-supplied URL
  and MD5;
- installs a RAM-only diagnostic package that exposes six MTD block devices;
- downloads two independent copies of every partition and verifies them;
- builds a full Thingino OTA package from the supplied image;
- flashes `cfg`, `oem`, `rootfs`, `rback`, `fit`, and finally `boot`;
- provides an `autoupdate-full.bin` soft-brick recovery image.

The tool does **not** contain account tokens, WiFi credentials, certificate
private keys, device backups, or a prebuilt firmware image.

## Verified stock layout

The two tested stock cameras reported this 16 MiB layout:

| MTD | Name | Offset | Size |
| --- | --- | ---: | ---: |
| 0 | boot | `0x000000` | `0x050000` |
| 1 | fit | `0x050000` | `0x210000` |
| 2 | rootfs | `0x260000` | `0x6A0000` |
| 3 | rback | `0x900000` | `0x6A0000` |
| 4 | cfg | `0xFA0000` | `0x050000` |
| 5 | oem | `0xFF0000` | `0x010000` |

The package refuses to flash unless `/proc/mtd` matches those names and sizes.
The boot partition is always written last.

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Patching WiFi credentials inside the Thingino SquashFS additionally requires
`unsquashfs` and `mksquashfs`.

## Quick start

### 1. Prepare the image and payloads

```bash
wyze-v3-ota prepare \
  --image /path/to/thingino-wyze_campan3_t31x_gc2053_atbm6031.bin \
  --build-dir build \
  --ssid "Legacy" \
  --psk "your-wifi-password"
```

This produces:

- `build/thingino-wyze-campan3.bin`
- `build/4.50.18.99.tar` (RAM diagnostic)
- `build/4.50.18.100.tar` (full Thingino flash)
- `build/sd-recovery/autoupdate-full.bin`
- `build/manifest.json`

Omit `--ssid` and `--psk` if the source image is already configured.

### 2. Start the lab services

Use a certificate chain and key already trusted by the target's stock CA
bundle. You provide these files locally; they are ignored by Git.

```bash
wyze-v3-ota serve \
  --cert /secure/path/fullchain.pem \
  --key /secure/path/leaf.key \
  --payload-dir build \
  --log logs/serve.log
```

Services:

- MQTT over TLS: `0.0.0.0:8883`
- HTTPS payloads: `0.0.0.0:8443`
- Local admin API: `127.0.0.1:8884`

Redirect these names to the lab host at the DNS/router layer:

- `aws-iot.wyzecam.com`
- `wyze-firmware-upgrade-service.wyzecam.com`
- `s3-us-west-2.amazonaws.com`

Allow the camera to reach TCP `8883` and `8443` on the lab host.

### 3. Confirm the broker session

```bash
wyze-v3-ota sessions
```

The camera's lowercase MAC should appear.

### 4. Install the RAM diagnostic and capture backups

```bash
wyze-v3-ota upgrade \
  --mac D03F27A465D7 \
  --payload build/4.50.18.99.tar \
  --public-host wyze-firmware-upgrade-service.wyzecam.com
```

After the camera starts the diagnostic server:

```bash
wyze-v3-ota backup \
  --host CAMERA_IP \
  --out-dir backups/D03F27A465D7

wyze-v3-ota verify-backup \
  --manifest backups/D03F27A465D7/backup-manifest.json
```

The backup command reads every partition twice through independent paths,
compares the bytes, reconstructs a 16 MiB image, and stores a manifest.

### 5. Flash Thingino

```bash
wyze-v3-ota flash \
  --mac D03F27A465D7 \
  --host CAMERA_IP \
  --image build/thingino-wyze-campan3.bin \
  --build-dir build \
  --backup-manifest backups/D03F27A465D7/backup-manifest.json \
  --public-host wyze-firmware-upgrade-service.wyzecam.com \
  --yes
```

The command refuses to run unless the backup manifest verifies and its saved
host matches `--host`.

Thingino assigns a new WiFi MAC address and DHCP lease. Look for the hostname
`ing-wyze-campan3-*`.

Default post-flash access:

- SSH: `root` / `root`
- RTSP: `rtsp://thingino:thingino@CAMERA_IP/ch0`
- RTSP: `rtsp://thingino:thingino@CAMERA_IP/ch1`
- Web UI: `http://CAMERA_IP/`

## Soft-brick recovery

The prepared `autoupdate-full.bin` is for Thingino U-Boot only:

1. Copy it to the root of an MBR/FAT32 microSD card.
2. Power off the camera.
3. Insert the card and power on.
4. Leave it for several minutes.

Thingino U-Boot checks the file size and writes it to the 16 MiB SPI flash.
This recovery is not consumed by the stock Wyze bootloader.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m wyze_v3_ota --help
```

See [docs/protocol.md](docs/protocol.md) for the verified OTA envelope and
payload structure.
