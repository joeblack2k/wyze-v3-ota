# Public certificate material

`public/fullchain.pem` contains the leaf certificate and issuing intermediate
used by the verified fixed-hostname lab workflow. `public/ca-cert.pem` is the
issuing intermediate certificate.

These are public certificates, not private keys. They are published for
inspection and offline lab interoperability. The fixed hostnames covered are:

- `wyze-firmware-upgrade-service.wyzecam.com`
- `wyze-upgrade-service.wyzecam.com`
- `s3-us-west-2.amazonaws.com`

Leaf certificate SHA-256 fingerprint:

`0F:AE:E5:A1:6E:C7:30:BE:F3:ED:16:29:56:B1:32:9E:F0:27:18:3B:2A:B7:5F:0A:85:97:4D:DC:8B:95:7C:17`

The issuing intermediate certificate SHA-256 fingerprint:

`45:A8:83:F3:49:AE:DF:D5:F3:A6:49:B5:49:8F:FB:12:17:12:BA:8B:44:8F:3F:2A:91:DB:C5:A7:66:FC:DD:BE`

The corresponding private keys are intentionally excluded from the source
tree. Authorized CTF releases may bundle the lab key material separately.
