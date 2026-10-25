#!/bin/sh

printf 'Content-Type: application/octet-stream\r\n\r\n'
n=${QUERY_STRING#n=}
case "$n" in
    0|1|2|3|4|5)
        exec /bin/busybox cat "/dev/mtd$n"
        ;;
esac
exit 2
