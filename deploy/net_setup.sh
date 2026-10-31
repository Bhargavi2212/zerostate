#!/bin/sh
# zerostate-net owns ZeroState's network namespace: route to the ICS net and an egress allowlist.
# Fail closed: any error exits this container, so zerostate (depends_on healthy) never starts.
set -eu
PLC=192.168.95.2

ip route replace 192.168.95.0/24 via 192.168.90.200
iptables -P OUTPUT ACCEPT
iptables -F OUTPUT
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -p tcp -d "$PLC" --dport 502 -j ACCEPT
iptables -P OUTPUT DROP

# compose disables IPv6; if it is somehow still on, drop it too.
if [ "$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6 2>/dev/null || echo 1)" != "1" ]; then
  ip6tables -F OUTPUT
  ip6tables -A OUTPUT -o lo -j ACCEPT
  ip6tables -P OUTPUT DROP
fi

exec sleep infinity
