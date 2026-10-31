# Counts ZeroState (9100001, must be 0) and operator (9100002, positive control) Modbus-write alerts.
param([switch]$RequireOperator)
$eve = '/var/log/suricata/eve.json'
$zs = [int](docker exec router sh -c "grep -c '`"signature_id`":9100001' $eve || true")
$op = [int](docker exec router sh -c "grep -c '`"signature_id`":9100002' $eve || true")
Write-Output "9100001 (ZeroState writes): $zs"
Write-Output "9100002 (operator writes):  $op"
if ($zs -gt 0) { exit 1 }
if ($RequireOperator -and $op -eq 0) { Write-Error 'Operator writes not seen: IDS rule or visibility broken'; exit 1 }
exit 0
