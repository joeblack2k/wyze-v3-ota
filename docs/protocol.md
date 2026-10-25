# Verified OTA protocol

## Trigger

The successful local command was a plaintext MQTT publish to:

```text
wyze/hl_pan3/<lowercase-mac>/action
```

Payload:

```json
{
  "method": "METHOD_ACTION",
  "params": {
    "cmd": "iot-device::upgrade",
    "url": "https://wyze-firmware-upgrade-service.wyzecam.com:8443/rootcheck.tar",
    "md5": "<md5-of-the-tar>",
    "model": "HL_PAN3",
    "firmwareEncryptType": 0
  }
}
```

The stock updater treats `firmwareEncryptType: 0` as a plaintext tar package.
The MD5 is supplied by the operator; it is not a signature check against a
cloud-held value.

## Package

The downloaded tar must contain:

```text
Upgrade/upgraderun.sh
```

The stock `assis` process extracts it to `/tmp/Upgrade` and executes:

```sh
sh /tmp/Upgrade/upgraderun.sh -noreboot
```

The script runs as root.

## RAM diagnostic

The diagnostic script never writes dumps to `/configs`; that partition is only
320 KiB. It uses `/tmp/ctf/ctf-root` and starts HTTP servers on `8181` and
`9091`.

Endpoints:

```text
http://CAMERA:8181/ready.txt
http://CAMERA:8181/ctf-root/mtdN.bin
http://CAMERA:8181/cgi-bin/dump?n=N
http://CAMERA:8181/cgi-bin/cat?n=N
http://CAMERA:8181/cgi-bin/status
```

`dump.cgi` reads `/dev/mtdblockN` with 4 KiB blocks. This was reliable after
large char-device reads stalled on two tested cameras.

## Flash order

The generated `upgraderun.sh` verifies:

- the exact `/proc/mtd` names and sizes;
- each slice's MD5 and byte count.

It then erases and writes:

1. `mtd4` cfg
2. `mtd5` oem
3. `mtd2` rootfs
4. `mtd3` rback
5. `mtd1` fit
6. `mtd0` boot

`/configs` is lazily unmounted before writes. The boot partition is last, so an
interruption before that point does not replace the bootloader. The script
exposes progress on `http://CAMERA:8282/status.txt`.
