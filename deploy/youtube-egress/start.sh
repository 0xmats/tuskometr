#!/bin/sh
set -eu
# Accept single IPv4 addresses only; never interpolate arbitrary config lines.
for address in "$EGRESS_BIND_ADDRESS" "$EGRESS_CLIENT_ADDRESS"; do
    case "$address" in
        ''|*[!0-9.]*) echo 'Egress requires IPv4 addresses' >&2; exit 1 ;;
    esac
done
# Bind only to localhost (testing) or the private Tailscale address.
case "$EGRESS_BIND_ADDRESS" in
    127.0.0.1|100.6[4-9].*|100.[7-9][0-9].*|100.1[01][0-9].*|100.12[0-7].*) ;;
    *) echo 'Bind egress to localhost or a Tailscale IPv4 address' >&2; exit 1 ;;
esac
cat > /tmp/tinyproxy.conf <<EOF
Port 18888
Listen $EGRESS_BIND_ADDRESS
Allow $EGRESS_BIND_ADDRESS
Allow $EGRESS_CLIENT_ADDRESS
Timeout 120
MaxClients 32
LogLevel Warning
PidFile "/tmp/tinyproxy.pid"
ConnectPort 443
Filter "/etc/tinyproxy/domains"
FilterType ere
FilterDefaultDeny Yes
EOF
exec tinyproxy -d -c /tmp/tinyproxy.conf
