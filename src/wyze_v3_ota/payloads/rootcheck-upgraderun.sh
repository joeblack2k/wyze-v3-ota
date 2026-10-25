#!/bin/sh

PATH=/bin:/sbin:/usr/bin:/usr/sbin:/system/bin
export PATH

BUSYBOX=/system/bin/busybox
[ -x "$BUSYBOX" ] || BUSYBOX=/bin/busybox
[ -x "$BUSYBOX" ] || BUSYBOX=/usr/bin/busybox

BASE=/tmp/ctf
OUT=$BASE/ctf-root
CGI=$BASE/cgi-bin
mkdir -p "$OUT" "$CGI"

cp /tmp/Upgrade/dump.cgi "$CGI/dump"
cp /tmp/Upgrade/cat.cgi "$CGI/cat"
cp /tmp/Upgrade/status.cgi "$CGI/status"
chmod 755 "$CGI/dump" "$CGI/cat" "$CGI/status"

printf 'ready\n' > "$BASE/ready.txt"
"$BUSYBOX" httpd -p 0.0.0.0:8181 -h "$BASE" \
    > "$OUT/httpd-8181.log" 2>&1 &
"$BUSYBOX" httpd -p 0.0.0.0:9091 -h "$BASE" \
    > "$OUT/httpd-9091.log" 2>&1 &

id > "$OUT/id.txt" 2>&1
uname -a > "$OUT/uname.txt" 2>&1
cat /proc/mtd > "$OUT/mtd.txt" 2>&1
cat /proc/cmdline > "$OUT/cmdline.txt" 2>&1
cat /proc/partitions > "$OUT/partitions.txt" 2>&1
cat /proc/mounts > "$OUT/mounts.txt" 2>&1
ls -l /dev/mtd* /dev/mtdblock* > "$OUT/mtd-devices.txt" 2>&1
cp /etc/passwd "$OUT/passwd.txt" 2>/dev/null
cp /etc/shadow "$OUT/shadow.txt" 2>/dev/null

# Remove dumps left by older lab scripts. The cfg partition is only 320 KiB.
rm -rf /configs/ctf-root /configs/ctf-root-v4 2>/dev/null

for index in 0 1 2 3 4 5; do
    if [ -e "/dev/mtdblock$index" ]; then
        dd if="/dev/mtdblock$index" of="$OUT/mtd$index.bin" \
            bs=4096 > "$OUT/dd-block-mtd$index.log" 2>&1
    fi
done

md5sum "$OUT"/mtd*.bin > "$OUT/md5sums.txt" 2>&1
sync

{{CALLBACK_COMMAND}}

sleep 600
exit 0
