# install_startup_task.ps1
# Registers downloads_watcher.py as a Windows Task Scheduler job
# Runs silently at login, restarts if it crashes.
# Run once as Administrator.

$TaskName    = "DownloadsCategorizer"
$ScriptPath  = "C:\Users\Karl\Documents\productivity-os\02_downloads_categorizer\downloads_watcher.py"
$PythonPath  = "C:\Users\Karl\AppData\Local\Programs\Python\Python312\python.exe"

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
    -Description "Karl Productivity OS - Downloads Auto-Categorizer" | Out-Null

Write-Host ""
Write-Host "Task registered: $TaskName"
Write-Host "  Path: $ScriptPath"
Write-Host "  Starts automatically at login"
Write-Host ""
Write-Host "To start right now:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
