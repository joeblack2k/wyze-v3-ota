# Pan v3 field report: stock 4.50.15.4800

This report records an additional successful installation and the troubleshooting
needed to complete it. It contains no device dumps, device identifiers, Wi-Fi
credentials, private keys, or prepared firmware.

## Tested configuration

| Component | Tested value |
| --- | --- |
| Camera | Wyze Cam Pan v3, `HL_PAN3` |
| Stock firmware | `4.50.15.4800` |
| OTA tool | `0.3.0`, commit `f51054d` |
| Host | Apple Silicon Mac, macOS 26.2; Python 3.13 virtual environment |
| SquashFS tools | Homebrew `squashfs` 4.7.5 |
| Router | TP-Link Deco AXE5400 with Static Routing available in the app |
| Target image | Image Builder `master`, commit `6a6e401`, model `wyze_campan3_t31x_gc2053_atbm6031` |

## Why DHCP DNS changes did not work

The camera remained reachable on the LAN, but no camera DNS requests reached a
local resolver selected through Deco's DHCP DNS settings. The matching
[stock recovery image](https://download.wyzecam.com/firmware/Panv3/recovery_wyzepan3_4.50.15.4800.bin.zip)
contained these active settings in `/etc/dnsmasq.conf`:

```ini
listen-address=127.0.0.1
no-resolv
all-servers
server=8.8.8.8
server=8.8.4.4
server=208.67.222.123
server=208.67.220.123
```

This configuration explains why advertising another DNS server through DHCP
was insufficient. Because `all-servers` is enabled, all four upstream paths
must be accounted for to avoid racing an unmodified public DNS answer.

The camera connected to the local broker after all four resolver addresses
were routed to a DNS forwarder on the lab host and the camera was power-cycled.

## Network setup that worked

The following are the requirements of the external DNS setup used in this test.
The tool's `serve` command provides MQTT and HTTPS; a DNS forwarder must be
configured separately.

1. Keep the lab host and camera on stable LAN addresses.
2. Configure the lab host to accept traffic addressed to all four resolver IPs.
   On this Mac, temporary `/32` aliases on the **incoming Wi-Fi interface**
   worked. Loopback aliases would require additional interface-check handling:
   this Mac had `net.inet.ip.check_interface=1`.
3. Bind the DNS forwarder to each resolver address on **UDP and TCP port 53**.
   Replies must use the resolver address the client queried as their source.
4. Apply the three hostname overrides from the README only to the camera's
   source IP. Forward other names and other LAN clients normally. The tested
   forwarder used `1.1.1.1` and `1.0.0.1` as upstreams, avoiding a forwarding loop
   through the four intercepted resolver addresses.
5. Test the forwarder before adding router routes. A query from a different
   LAN client should receive normal public answers, not the camera overrides.
6. Add the four host routes below, then power-cycle the camera. Check the
   forwarder's camera query log and `wyze-v3-ota sessions` before sending an
   upgrade command.

For example, with a lab host at **`192.0.2.10`** (an example address, not a value
to copy unchanged), Deco's **More > Advanced > Static Routing** entries were:

| Destination | Subnet mask | Gateway | Interface |
| --- | --- | --- | --- |
| `8.8.8.8` | `255.255.255.255` | Lab host LAN IP | LAN |
| `8.8.4.4` | `255.255.255.255` | Lab host LAN IP | LAN |
| `208.67.222.123` | `255.255.255.255` | Lab host LAN IP | LAN |
| `208.67.220.123` | `255.255.255.255` | Lab host LAN IP | LAN |

[TP-Link documents the route fields here](https://www.tp-link.com/au/support/faq/3993/).
These routes apply to the router's clients, so the forwarder must preserve
normal DNS behavior for other devices. The lab host must remain available
until the routes are removed. Changing DHCP DNS is unnecessary for this
fixed-resolver camera path.

## Updater behavior and timing

- The normal tool-generated `wyze/hl_pan3/<mac>/action` command worked. The
  camera's advertised subscriptions included `hl/devices/<mac>/cmd`; that
  difference did not require a topic change for this installation.
- Both the diagnostic and full-flash payload requests arrived about **98
  seconds** after their corresponding upgrade commands. The updater's
  preparation and status-reporting delays should not be mistaken for an
  immediate command failure.
- The MQTT connection closed during updater preparation. The diagnostic later
  became available at port `8181` without another upgrade command.
- `flash --monitor-timeout 900` was used. The default 300-second timeout was
  not tested independently. The new Thingino service appeared roughly four
  and a half minutes after the flash command.
- The camera received a different Wi-Fi MAC and DHCP lease after installing
  Thingino. `_thingino._tcp` discovery and the router's client list helped
  identify the new `ing-wyze-campan3-*` device.

## Backup and post-install checks

- The live `/proc/mtd` names, sizes, and erase sizes matched the stock layout
  documented in the README.
- All six partitions were read twice through independent paths and compared
  byte-for-byte. They reconstructed a 16 MiB image. A second local backup copy
  was also retained.
- The Wi-Fi-configured rootfs passed full extraction/read-back verification.
  Bytes outside the rootfs remained identical to the master image. The OTA
  slices and SD recovery image reconstructed the configured image exactly.
- SSH and the web UI worked after installation.
- Main RTSP: H.264, 1920x1080, AAC audio at 16 kHz.
- Substream RTSP: H.264, 640x360, AAC audio.
- Video packets were verified after a normal reboot.

## Power-related motor resets

Pan/tilt had worked on stock firmware while powered through a USB hub. With
Thingino, startup homing and a small movement test were followed by lost
connectivity and a new boot. Disabling startup homing temporarily allowed
stationary streaming and further diagnosis.

After switching to wall power:

- Both axes moved and returned to their starting positions without a boot-ID change.
- Full homing and return to the configured home position passed.
- Automatic startup homing was restored, and a normal reboot completed with
  homing, the web UI, and RTSP working.

This is evidence for a power-delivery problem in this setup, not proof that
all motor resets have the same cause. The wall adapter's exact rating and
cable length were not recorded. Wyze specifies a
[5 V, 2 A adapter for this camera](https://support.wyze.com/hc/en-us/articles/11795670894875-Wyze-Cam-Pan-v3-Tech-Specs).
Test suitable dedicated power before concluding that a motor-driver change
is required; no motor-driver patch was needed here.

## Cleanup

Remove the four router host routes **before** stopping the fixed-resolver DNS
forwarder or removing its temporary interface aliases. Remove only aliases
created for this installation.

If DHCP DNS settings were changed, restore their original values and renew
the affected leases before stopping that resolver. In this test, both the
Mac and the camera were checked to confirm they had received the router's
normal DNS servers. The temporary firmware server, DNS services, and aliases
were then removed; camera access and normal DNS resolution still worked.
