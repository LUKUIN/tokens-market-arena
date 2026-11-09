# -*- coding: utf-8 -*-
# DeepClean Process — Tokens Trading Market (AI edition)
#
# Purpose: kill every leftover game process and clear runtime files under data/.
#          Historical reports in reports/ are never touched.
#
# When: run it right after a reset, to make sure no old process holds a port or a file.
#        Also run it if a reset reports "file in use" or the window never appears.

# AI / non-interactive use: force UTF-8 output, otherwise CJK text is garbled in Git Bash
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
try { $OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$ErrorActionPreference = "SilentlyContinue"

# v1.2.13: this script lives under tools/, so resolve the real project root first
# (the directory that holds run.py). Older builds referenced $root below before
# defining it, which meant the guard.py restore silently never ran.
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not (Test-Path (Join-Path $root "run.py"))) {
    $parent = Split-Path -Parent $root
    if (Test-Path (Join-Path $parent "run.py")) { $root = $parent }
}

# Restore any sources still sealed by guard.py before anything else.
if (Test-Path (Join-Path $root "guard.py")) {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { & python (Join-Path $root "guard.py") clean 2>$null }
}
$dataDir = Join-Path $root "src\data"
if (-not (Test-Path $dataDir)) { $dataDir = Join-Path $root "data" }

Write-Host ""
Write-Host "  Target directory: " -ForegroundColor Gray
Write-Host "    $root" -ForegroundColor DarkGray
Write-Host ""

# ---------- 1. Identify processes ----------
# Rule A: the command line contains one of these markers (startgame.pyc / tm_api / tm_watch / tm_engine)
# Rule B: listening on any port 8734-8745 (server and spectator lock)
$markers = @("tm_api", "tm_watch", "tm_engine", "startgame", "TokensMarket", "TokensMarketHuman", "guard.py")
$ports   = 8734..8745

$targets = @{}
$all = Get-CimInstance Win32_Process -Filter "Name='python.exe'"

# Group A: command-line match
foreach ($p in $all) {
    $cmd = $p.CommandLine
    if (-not $cmd) { continue }
    foreach ($m in $markers) {
        if ($cmd -like "*$m*") {
            $targets[$p.ProcessId] = "command line contains $m"
            break
        }
    }
}

# Group B: port in use
foreach ($port in $ports) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($c) {
        foreach ($x in $c) {
            if ($x.OwningProcess -and -not $targets.ContainsKey([int]$x.OwningProcess)) {
                $targets[[int]$x.OwningProcess] = "listening on port $port"
            }
        }
    }
}

# ---------- 2. List and terminate ----------
if ($targets.Count -eq 0) {
    Write-Host "  No leftover game processes found." -ForegroundColor Green
} else {
    Write-Host "  Found these processes:" -ForegroundColor Yellow
    foreach ($k in $targets.Keys) {
        $p = $all | Where-Object { $_.ProcessId -eq $k } | Select-Object -First 1
        $name = if ($p) { $p.ProcessId } else { $k }
        Write-Host ("    PID {0,-7} {1}" -f $k, $targets[$k]) -ForegroundColor DarkYellow
    }
    Write-Host ""
    foreach ($k in $targets.Keys) {
        try {
            Stop-Process -Id $k -Force -ErrorAction Stop
            Write-Host ("    terminated PID {0}" -f $k) -ForegroundColor Green
        } catch {
            Write-Host ("    failed to terminate PID {0}: {1}" -f $k, $_.Exception.Message) -ForegroundColor Red
        }
    }
}

# ---------- 3. Wait for handles to be released ----------
Start-Sleep -Milliseconds 900

# ---------- 4. Re-check ----------
$left = @()
foreach ($p in (Get-CimInstance Win32_Process -Filter "Name='python.exe'")) {
    $cmd = $p.CommandLine
    if (-not $cmd) { continue }
    foreach ($m in $markers) {
        if ($cmd -like "*$m*") { $left += $p.ProcessId; break }
    }
}
foreach ($port in $ports) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($c) { foreach ($x in $c) { if ($x.OwningProcess) { $left += [int]$x.OwningProcess } } }
}
$left = $left | Sort-Object -Unique
if ($left.Count -gt 0) {
    Write-Host ""
    Write-Host ("  [WARN] processes still alive: {0}" -f ($left -join ", ")) -ForegroundColor Red
    Write-Host "    Might be a permission issue, or the process belongs to another user." -ForegroundColor DarkYellow
} else {
    Write-Host ""
    Write-Host "  Re-check: every related process has exited." -ForegroundColor Green
}

# ---------- 4b. Restore sealed sources before touching anything else ----------
# A crashed match leaves the sources encrypted in %LOCALAPPDATA%\TokensMarketGuard and decoys in
# src/. Deleting data/ without restoring first leaves the tree looking like the code was destroyed.
$stateFile = Join-Path $root "_guard_vault\guard_state.json"
if (Test-Path $stateFile) {
    Write-Host ""
    Write-Host "  Sources are sealed from an interrupted match; restoring ..." -ForegroundColor Yellow
    $guardPy = Join-Path $root "guard.py"
    try {
        & python $guardPy clean 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    } catch {
        Write-Host "  [WARN] could not run guard.py clean: $_" -ForegroundColor Red
    }
    if (Test-Path $stateFile) {
        Write-Host "  [WARN] sources may still be decoys; run 'python guard.py clean' by hand." -ForegroundColor Red
    } else {
        Write-Host "  Sources restored." -ForegroundColor Green
    }
}

# ---------- 5. Clear runtime files under data/ (keep reports) ----------
$removed = 0
$keep = @("reports")
if (Test-Path $dataDir) {
    Get-ChildItem -Path $dataDir -Force | ForEach-Object {
        if ($keep -notcontains $_.Name) {
            Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
            $removed++
        }
    }
}
Write-Host ""
if ($removed -gt 0) {
    Write-Host ("  Removed {0} runtime items under data/ (reports kept)." -f $removed) -ForegroundColor Green
} else {
    Write-Host "  Nothing to clean under data/." -ForegroundColor Green
}

# ---------- 5b. Clear the engine's own _agent/ directory ----------
$agentDir = Join-Path $root "_agent"
if (Test-Path $agentDir) {
    Remove-Item -LiteralPath $agentDir -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $agentDir) {
        Write-Host "  [WARN] failed to remove _agent/ (still in use?)." -ForegroundColor Yellow
    } else {
        Write-Host "  _agent/ removed (the engine recreates it on the next start)." -ForegroundColor Green
    }
} else {
    Write-Host "  _agent/ does not exist, nothing to clean." -ForegroundColor DarkGray
}

# ---------- 5c. Clear temporary logs in the root ----------
$logCount = 0
Get-ChildItem -Path $root -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.Extension -in @(".log", ".tmp") -or $_.Name -like "*.log.*" -or $_.Name -like "nohup*") {
        Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
        $logCount++
    }
}
if ($logCount -gt 0) {
    Write-Host ("  Removed {0} temporary logs from the root." -f $logCount) -ForegroundColor Green
}

# ---------- 5d. Report files that do not belong to the project ----------
# Whatever was written into the project by something other than this repository shows up here.
# Reported, never deleted: removing unknown files automatically risks eating real work.
$gitDir = Join-Path $root ".git"
if (Test-Path $gitDir) {
    $untracked = @()
    & git -C $root status --porcelain --untracked-files=all 2>$null | ForEach-Object {
        if ($_ -match '^[?][?] ') { $untracked += $_.Substring(3).Trim('"') }
    }
    if ($untracked.Count -gt 0) {
        Write-Host ""
        Write-Host "  Not part of this project (left by an agent or a previous run):" -ForegroundColor Yellow
        foreach ($e in ($untracked | Sort-Object)) { Write-Host "    $e" -ForegroundColor DarkYellow }
        Write-Host "  Nothing was deleted; remove them by hand if they are leftovers." -ForegroundColor DarkGray
    } else {
        Write-Host ""
        Write-Host "  No untracked files." -ForegroundColor Green
    }
} else {
    Write-Host ""
    Write-Host "  Not a git checkout; skipping the untracked-file scan." -ForegroundColor DarkGray
}

# ---------- 5e. Final state ----------
Write-Host ""
Write-Host "  Final state:" -ForegroundColor Cyan
$dataLeft = @()
if (Test-Path $dataDir) {
    $dataLeft = Get-ChildItem -Path $dataDir -Force | Select-Object -ExpandProperty Name
}
Write-Host ("    data/  →  {0}" -f ($(if ($dataLeft.Count -gt 0) { $dataLeft -join ", " } else { "empty" }))) -ForegroundColor DarkGray
Write-Host ("    _agent/ →  {0}" -f $(if (Test-Path $agentDir) { "still present" } else { "removed" })) -ForegroundColor DarkGray
$sess = Join-Path $dataDir "session.json"
Write-Host ("    session.json →  {0}" -f $(if (Test-Path $sess) { "[WARN] still present" } else { "cleared" })) -ForegroundColor $(if (Test-Path $sess) { "Red" } else { "DarkGray" })

# ---------- 6. Summary ----------
Write-Host ""
Write-Host "  ----------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "  Cleanup finished. You can start the game again." -ForegroundColor Cyan
Write-Host "  ----------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""
