#!/bin/sh
# zs-api-net owns zs-api's network namespace: OUTPUT allowlist = the model proxy only. Never a plant.
# Replies to the console on the published port (127.0.0.1:8090 on Windows) leave as ESTABLISHED.
# Fail closed: any error exits this container, so zs-api (depends_on healthy) never starts.
set -eu
PROXY=172.30.0.2   # zs-proxy: CONNECT api.meta.ai:443 only

iptables -P OUTPUT ACCEPT
iptables -F OUTPUT
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -p tcp -d "$PROXY" --dport 8888 -j ACCEPT
iptables -P OUTPUT DROP

# compose disables IPv6; if it is somehow still on, drop it too.
if [ "$(cat /proc/sys/net/ipv6/conf/all/disable_ipv6 2>/dev/null || echo 1)" != "1" ]; then
  ip6tables -F OUTPUT
  ip6tables -A OUTPUT -o lo -j ACCEPT
  ip6tables -P OUTPUT DROP
fi

exec sleep infinity
