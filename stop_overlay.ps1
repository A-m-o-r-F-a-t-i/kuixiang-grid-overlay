$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidPath = Join-Path $ProjectDir 'overlay.pid'
$TaskName = 'KuixiangGridOverlay'

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if (-not (Test-Path -LiteralPath $PidPath)) {
    Write-Host '叠加层未运行。'
    exit 0
}

$OverlayPid = [int](Get-Content -LiteralPath $PidPath -Raw).Trim()
$ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$OverlayPid" -ErrorAction SilentlyContinue
if ($null -eq $ProcessInfo -or $ProcessInfo.CommandLine -notlike "*$ProjectDir*") {
    Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
    Write-Host 'PID 已失效，已清理。'
    exit 0
}

Stop-Process -Id $OverlayPid -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
Write-Host "已停止叠加层进程 $OverlayPid。"
