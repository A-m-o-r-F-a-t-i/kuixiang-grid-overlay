$ErrorActionPreference = 'Stop'

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pythonw = Join-Path $ProjectDir '.venv\Scripts\pythonw.exe'
$OverlayScript = Join-Path $ProjectDir 'overlay.py'
$PidPath = Join-Path $ProjectDir 'overlay.pid'
$TaskName = 'KuixiangGridOverlay'

if (-not (Test-Path -LiteralPath $Pythonw)) {
    throw "缺少 Python 虚拟环境：$Pythonw"
}
if (-not (Test-Path -LiteralPath $OverlayScript)) {
    throw "缺少程序入口：$OverlayScript"
}

if (Test-Path -LiteralPath $PidPath) {
    $ExistingPid = [int](Get-Content -LiteralPath $PidPath -Raw).Trim()
    $Existing = Get-CimInstance Win32_Process -Filter "ProcessId=$ExistingPid" -ErrorAction SilentlyContinue
    if ($null -ne $Existing -and $Existing.CommandLine -like "*$OverlayScript*") {
        Write-Host "叠加层已在运行，PID=$ExistingPid。"
        exit 0
    }
    Remove-Item -LiteralPath $PidPath -Force -ErrorAction SilentlyContinue
}

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Action = New-ScheduledTaskAction `
    -Execute $Pythonw `
    -Argument ('"' + $OverlayScript + '"') `
    -WorkingDirectory $ProjectDir
$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentUser `
    -LogonType Interactive `
    -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)
$Task = New-ScheduledTask -Action $Action -Principal $Principal -Settings $Settings
Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

$Deadline = [DateTime]::UtcNow.AddSeconds(12)
do {
    Start-Sleep -Milliseconds 200
    if (-not (Test-Path -LiteralPath $PidPath)) {
        continue
    }
    $OverlayPid = [int](Get-Content -LiteralPath $PidPath -Raw).Trim()
    $ProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$OverlayPid" -ErrorAction SilentlyContinue
    if ($null -ne $ProcessInfo -and $ProcessInfo.CommandLine -like "*$OverlayScript*") {
        Write-Host "叠加层已启动，PID=$OverlayPid。"
        exit 0
    }
} while ([DateTime]::UtcNow -lt $Deadline)

$TaskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
throw "叠加层启动失败。LastTaskResult=$($TaskInfo.LastTaskResult)"
