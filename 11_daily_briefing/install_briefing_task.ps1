# install_briefing_task.ps1
# Registers briefing.py as a Windows Task Scheduler job.
# Runs every morning at 8:00 AM and can also be triggered manually.
# Run once as Administrator.

$TaskName    = "ProductivityOS_DailyBriefing"
$ScriptPath  = "C:\Users\Karl\Documents\productivity-os\11_daily_briefing\briefing.py"
$PythonPath  = "C:\Users\Karl\AppData\Local\Programs\Python\Python312\pythonw.exe"
$WorkDir     = "C:\Users\Karl\Documents\productivity-os\11_daily_briefing"
$RunTime     = "08:00"   # <-- change this to your preferred morning time

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$ScriptPath`"" `
    -WorkingDirectory $WorkDir

# Run daily at specified time
$Trigger = New-ScheduledTaskTrigger -Daily -At $RunTime

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -RunLevel Highest `
    -Description "Karl Productivity OS - Daily Briefing (runs every morning at $RunTime)" | Out-Null

Write-Host ""
Write-Host "Task registered: $TaskName"
Write-Host "  Script: $ScriptPath"
Write-Host "  Runs daily at: $RunTime"
Write-Host ""
Write-Host "To run RIGHT NOW (manual trigger):"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "Or run manually from terminal anytime:"
Write-Host "  python `"$ScriptPath`"                    # full briefing"
Write-Host "  python `"$ScriptPath`" --extract          # update Tasks.md only"
Write-Host "  python `"$ScriptPath`" --tasks            # show current task list"
Write-Host "  python `"$ScriptPath`" --days 14          # scan further back"
