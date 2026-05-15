# install_startup_task.ps1
# Registers downloads_watcher.py as a Windows Task Scheduler job.
# Runs SILENTLY at login (no console window) using pythonw.exe.
# Run once as Administrator.

$TaskName    = "DownloadsCategorizer"
$ScriptPath  = "C:\Users\Karl\Documents\productivity-os\02_downloads_categorizer\downloads_watcher.py"

# pythonw.exe = windowless Python — same as python.exe but no console popup
$PythonPath  = "C:\Users\Karl\AppData\Local\Programs\Python\Python312\pythonw.exe"

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$ScriptPath`"" `
    -WorkingDirectory "C:\Users\Karl\Documents\productivity-os\02_downloads_categorizer"

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -RunLevel Highest `
    -Description "Karl Productivity OS - Downloads Auto-Categorizer (silent)" | Out-Null

Write-Host ""
Write-Host "Task registered: $TaskName"
Write-Host "  Path:    $ScriptPath"
Write-Host "  Runner:  pythonw.exe (no console window)"
Write-Host "  Trigger: At login — runs silently in background"
Write-Host ""
Write-Host "To start right now (no window will appear — that's correct):"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "To check it's actually running:"
Write-Host "  Get-Process pythonw"
Write-Host ""
Write-Host "To stop it:"
Write-Host "  Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "  # or just: Stop-Process -Name pythonw"
