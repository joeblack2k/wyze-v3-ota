#!/bin/sh

printf 'Content-Type: text/plain\r\n\r\n'
cat /proc/mtd
ls -l /tmp/ctf/ctf-root 2>&1
ps w | grep -E 'dd|httpd|upgraderun' | grep -v grep
