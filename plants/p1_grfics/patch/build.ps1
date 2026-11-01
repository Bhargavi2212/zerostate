# Builds zerostate/grfics-simulation:p1-1 from the pinned GRFICSv3 clone plus our patches.
# Never edits the clone: copies the simulation sources to a temp dir, normalises them to LF,
# applies the patches there, and builds.
param([string]$Vendor = 'D:\grfics\vendor\grficsv3')
$Commit = '8d611b773fa74e3a82ff149c447cff8380eaa99a'  # pragma: allowlist secret (git commit id)

$head = git -C $Vendor rev-parse HEAD
if ($head -ne $Commit) { Write-Error "clone at $head, expected $Commit"; exit 1 }

$tmp = Join-Path $env:TEMP 'zs-grfics-build'
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp -Confirm:$false }
New-Item -ItemType Directory $tmp | Out-Null
Copy-Item -Recurse "$Vendor\simulation\simulation" "$tmp\simulation"

# The Windows checkout has CRLF; the patches (like upstream) are LF.
$utf8 = New-Object System.Text.UTF8Encoding($false)
Get-ChildItem -Recurse -File "$tmp\simulation" | ForEach-Object {
    $text = [IO.File]::ReadAllText($_.FullName)
    [IO.File]::WriteAllText($_.FullName, $text.Replace("`r`n", "`n"), $utf8)
}

# Own repo for the temp dir: inside a parent repo, git apply silently skips paths outside the cwd.
git -C $tmp init -q
foreach ($p in 'TE_process.patch', 'remote_io.patch') {
    git -C $tmp apply --whitespace=nowarn "$PSScriptRoot\$p"
    if ($LASTEXITCODE -ne 0) { Write-Error "patch $p failed"; exit 1 }
}
foreach ($f in 'simulation\TE_process.cc', 'simulation\remote_io\modbus\feed1.py') {
    if (-not (Select-String -Quiet -Pattern 'ZS patch p1-1' -Path "$tmp\$f")) { Write-Error "patch not applied to $f"; exit 1 }
}

Copy-Item "$PSScriptRoot\Dockerfile.derived" "$tmp\Dockerfile"
docker build -t zerostate/grfics-simulation:p1-1 $tmp
if ($LASTEXITCODE -ne 0) { Write-Error 'docker build failed'; exit 1 }
docker image inspect zerostate/grfics-simulation:p1-1 --format '{{.Id}}'
