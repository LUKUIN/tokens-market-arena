# -*- coding: utf-8 -*-
# 进程深度清理 —— Tokens 交易市场（AI 版）
#
# 用途：杀掉所有残留的游戏进程，并清掉 data/ 下的运行时文件。
#       reports/ 里的历史战报不会被动。
#
# 何时用：每次「一键重置游戏」之后立刻跑一遍，确保没有旧进程占着端口或文件。
#         如果重置时提示「文件被占用」或启动后窗口不出现，也跑一遍。

$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$dataDir = Join-Path $root "src\data"
if (-not (Test-Path $dataDir)) { $dataDir = Join-Path $root "data" }

Write-Host ""
Write-Host "  目标目录：" -ForegroundColor Gray
Write-Host "    $root" -ForegroundColor DarkGray
Write-Host ""

# ---------- 1. 识别进程 ----------
# 规则 A：命令行里含这些关键字（涵盖 startgame.pyc / tm_api / tm_watch / tm_engine）
# 规则 B：监听 8734-8745 任一端口（服务与观众席锁）
$markers = @("tm_api", "tm_watch", "tm_engine", "startgame", "TokensMarket", "TokensMarketHuman")
$ports   = 8734..8745

$targets = @{}
$all = Get-CimInstance Win32_Process -Filter "Name='python.exe'"

# A 组：命令行匹配
foreach ($p in $all) {
    $cmd = $p.CommandLine
    if (-not $cmd) { continue }
    foreach ($m in $markers) {
        if ($cmd -like "*$m*") {
            $targets[$p.ProcessId] = "命令行含 $m"
            break
        }
    }
}

# B 组：端口占用
foreach ($port in $ports) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($c) {
        foreach ($x in $c) {
            if ($x.OwningProcess -and -not $targets.ContainsKey([int]$x.OwningProcess)) {
                $targets[[int]$x.OwningProcess] = "占用端口 $port"
            }
        }
    }
}

# ---------- 2. 列出并终止 ----------
if ($targets.Count -eq 0) {
    Write-Host "  没有发现残留的游戏进程。" -ForegroundColor Green
} else {
    Write-Host "  发现以下进程：" -ForegroundColor Yellow
    foreach ($k in $targets.Keys) {
        $p = $all | Where-Object { $_.ProcessId -eq $k } | Select-Object -First 1
        $name = if ($p) { $p.ProcessId } else { $k }
        Write-Host ("    PID {0,-7} {1}" -f $k, $targets[$k]) -ForegroundColor DarkYellow
    }
    Write-Host ""
    foreach ($k in $targets.Keys) {
        try {
            Stop-Process -Id $k -Force -ErrorAction Stop
            Write-Host ("    已终止 PID {0}" -f $k) -ForegroundColor Green
        } catch {
            Write-Host ("    终止 PID {0} 失败：{1}" -f $k, $_.Exception.Message) -ForegroundColor Red
        }
    }
}

# ---------- 3. 等待句柄释放 ----------
Start-Sleep -Milliseconds 900

# ---------- 4. 复查 ----------
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
    Write-Host ("  ⚠ 仍有进程存活：{0}" -f ($left -join ", ")) -ForegroundColor Red
    Write-Host "    可能权限不足，或进程属于其他用户。" -ForegroundColor DarkYellow
} else {
    Write-Host ""
    Write-Host "  复查：所有相关进程均已退出。" -ForegroundColor Green
}

# ---------- 5. 清 data/ 运行时文件（保留 reports） ----------
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
    Write-Host ("  已清理 data/ 下 {0} 项运行时文件（reports 保留）。" -f $removed) -ForegroundColor Green
} else {
    Write-Host "  data/ 下没有需要清理的残留。" -ForegroundColor Green
}

# ---------- 5b. 清引擎自撰目录 _agent/ ----------
$agentDir = Join-Path $root "_agent"
if (Test-Path $agentDir) {
    Remove-Item -LiteralPath $agentDir -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $agentDir) {
        Write-Host "  ⚠ _agent/ 清理失败（可能仍被占用）。" -ForegroundColor Yellow
    } else {
        Write-Host "  已删除 _agent/（引擎会在下次启动时重建）。" -ForegroundColor Green
    }
} else {
    Write-Host "  _agent/ 不存在，无需清理。" -ForegroundColor DarkGray
}

# ---------- 5c. 清根目录下的临时日志 ----------
$logCount = 0
Get-ChildItem -Path $root -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.Extension -in @(".log", ".tmp") -or $_.Name -like "*.log.*" -or $_.Name -like "nohup*") {
        Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
        $logCount++
    }
}
if ($logCount -gt 0) {
    Write-Host ("  已清理根目录 {0} 个临时日志。" -f $logCount) -ForegroundColor Green
}

# ---------- 5d. 最终状态确认 ----------
Write-Host ""
Write-Host "  最终状态：" -ForegroundColor Cyan
$dataLeft = @()
if (Test-Path $dataDir) {
    $dataLeft = Get-ChildItem -Path $dataDir -Force | Select-Object -ExpandProperty Name
}
Write-Host ("    data/  →  {0}" -f ($(if ($dataLeft.Count -gt 0) { $dataLeft -join ", " } else { "空" }))) -ForegroundColor DarkGray
Write-Host ("    _agent/ →  {0}" -f $(if (Test-Path $agentDir) { "仍存在" } else { "已删除" })) -ForegroundColor DarkGray
$sess = Join-Path $dataDir "session.json"
Write-Host ("    session.json →  {0}" -f $(if (Test-Path $sess) { "仍存在 ⚠" } else { "已清除" })) -ForegroundColor $(if (Test-Path $sess) { "Red" } else { "DarkGray" })

# ---------- 6. 汇总 ----------
Write-Host ""
Write-Host "  ----------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "  清理完成。现在可以重新启动游戏。" -ForegroundColor Cyan
Write-Host "  ----------------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""
