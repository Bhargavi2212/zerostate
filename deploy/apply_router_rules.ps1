# Installs ZeroState's router rules and IDS rules into the running GRFICS router container.
# Idempotent. Re-run after any router restart or rule apply in the router web UI (both wipe these rules).
# .60 = ZeroState (via zerostate-net), .70 = the eval operator: each may reach only PLC:502.
$Sources = '192.168.90.60', '192.168.90.70'
$PLC = '192.168.95.2'

function Has($rule) {
    docker exec router iptables -C FORWARD @rule 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

foreach ($src in $Sources) {
    $allow = @('-s', $src, '-d', $PLC, '-p', 'tcp', '--dport', '502', '-j', 'ACCEPT')
    $drop = @('-s', $src, '-j', 'DROP')
    # Allow must sit directly above drop, and both above the router's allow-all: reinsert as a pair.
    if (-not ((Has $allow) -and (Has $drop))) {
        while (Has $allow) { docker exec router iptables -D FORWARD @allow }
        while (Has $drop) { docker exec router iptables -D FORWARD @drop }
        docker exec router iptables -I FORWARD 1 @allow
        docker exec router iptables -I FORWARD 2 @drop
    }
}

$chain = @(docker exec router iptables -S FORWARD)
$chain | ForEach-Object { Write-Output $_ }
$iAll = [array]::IndexOf($chain, '-A FORWARD -j ACCEPT')
foreach ($src in $Sources) {
    $iAllow = [array]::IndexOf($chain, "-A FORWARD -s $src/32 -d $PLC/32 -p tcp -m tcp --dport 502 -j ACCEPT")
    $iDrop = [array]::IndexOf($chain, "-A FORWARD -s $src/32 -j DROP")
    if ($iAllow -lt 0 -or $iDrop -ne $iAllow + 1 -or ($iAll -ge 0 -and $iAll -lt $iDrop)) {
        Write-Error "FORWARD order wrong for ${src}: allow=$iAllow drop=$iDrop allow-all=$iAll"
        exit 1
    }
}

# IDS: alert on Modbus writes from ZeroState (must stay 0) and the operator (positive control).
$log = '/var/log/suricata/suricata.log'
$before = [int](docker exec router sh -c "wc -l < $log")
docker cp "$PSScriptRoot\suricata_zerostate.rules" router:/etc/suricata/rules/zerostate.rules
docker exec router supervisorctl restart suricata | Out-Null
$loaded = $null
for ($i = 0; $i -lt 30 -and -not $loaded; $i++) {
    Start-Sleep -Seconds 2
    $new = @(docker exec router sh -c "tail -n +$($before + 1) $log")
    $loaded = $new | Select-String 'rules successfully loaded'
}
if (-not $loaded) { Write-Error 'Suricata did not report loading rules within 60 s'; exit 1 }
Write-Output $loaded.Line
$bad = $new | Select-String 'zerostate.rules|9100001|9100002'
if ($bad) { $bad | ForEach-Object { Write-Output $_.Line }; Write-Error 'Suricata rejected a ZeroState rule'; exit 1 }
$status = docker exec router supervisorctl status suricata
if ($status -notmatch 'RUNNING') { Write-Error "Suricata not running: $status"; exit 1 }
Write-Output 'Router rules and IDS rules in place.'
