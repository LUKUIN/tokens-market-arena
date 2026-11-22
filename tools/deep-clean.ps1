$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if (-not (Test-Path -LiteralPath (Join-Path $root "run.py") -PathType Leaf)) {
    throw "Game launcher not found."
}

$dataDir = Join-Path $root "src\data"
$agentDir = Join-Path $root "_agent"
$vaultDir = Join-Path $root "_guard_vault"
$sourceDir = Join-Path $root "src"
foreach ($path in @($sourceDir, $dataDir, $agentDir, $vaultDir)) {
    $item = Get-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw ("Cleanup skipped a linked path: " + $path)
    }
}

$marker = Join-Path $dataDir ".running"
if (Test-Path -LiteralPath $marker -PathType Leaf) {
    $fields = ([string](Get-Content -LiteralPath $marker -Raw)).Trim() -split "\t"
    $ownerId = 0
    if ($fields.Length -eq 2 -and [int]::TryParse($fields[1], [ref]$ownerId) -and
            (Get-Process -Id $ownerId -ErrorAction SilentlyContinue)) {
        throw "This checkout still has an active game process. Close the match before cleanup."
    }
}

$guardState = Join-Path $vaultDir "guard_state.json"
if (Test-Path -LiteralPath $guardState -PathType Leaf) {
    $restore = "import guard; guard.restore_if_sealed()"
    Push-Location -LiteralPath $root
    try {
        & python -B -c $restore
        if ($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $guardState)) {
            throw "Source restore did not finish. Runtime files were kept."
        }
    } finally {
        Pop-Location
    }
}

foreach ($name in @("session.json", "session.json.tmp", ".running", ".scratchpad.jsonl", ".seal")) {
    $path = Join-Path $dataDir $name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -Force
    }
}

if (Test-Path -LiteralPath $agentDir -PathType Container) {
    $resolvedAgent = (Resolve-Path -LiteralPath $agentDir).Path
    if ($resolvedAgent -ne $agentDir) {
        throw ("Cleanup skipped a linked path: " + $agentDir)
    }
    Get-ChildItem -LiteralPath $resolvedAgent -Force | ForEach-Object {
        $reparsePoint = [bool]($_.Attributes -band [IO.FileAttributes]::ReparsePoint)
        Remove-Item -LiteralPath $_.FullName -Force -Recurse:(!$reparsePoint)
    }
}
Write-Host "Stale runtime files removed. Reports were kept."
