# install_switcher.ps1
# Sets up Project 17 — Intent Switcher
# Registers the AutoHotkey hotkey script to run at Windows login.
# Run once as Administrator.

$TaskName   = "IntentSwitcherHotkeys"
$AhkExe     = "C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"
$AhkScript  = "C:\Users\Karl\Documents\productivity-os\17_intent_switcher\intent_switcher_hotkeys.ahk"
$SwitcherDir = "C:\Users\Karl\Documents\productivity-os\17_intent_switcher"

Write-Host ""
Write-Host "Intent Switcher — Project 17 Setup" -ForegroundColor Cyan
Write-Host "─────────────────────────────────────" -ForegroundColor DarkGray

# ── Step 1: Create the project folder
if (-not (Test-Path $SwitcherDir)) {
    New-Item -ItemType Directory -Path $SwitcherDir -Force | Out-Null
    Write-Host "  Created folder: $SwitcherDir" -ForegroundColor Green
}

# ── Step 2: Install Python dependencies
Write-Host ""
Write-Host "  Installing Python dependencies..." -ForegroundColor Yellow
pip install pyyaml --quiet
Write-Host "  ✓ pyyaml ready" -ForegroundColor Green

# ── Step 3: Check for AutoHotkey
if (-not (Test-Path $AhkExe)) {
    Write-Host ""
    Write-Host "  AutoHotkey v2 not found at expected path." -ForegroundColor Yellow
    Write-Host "  Download from: https://www.autohotkey.com/" -ForegroundColor Cyan
    Write-Host "  Or install via winget:" -ForegroundColor Cyan
    Write-Host "    winget install AutoHotkey.AutoHotkey" -ForegroundColor White
    Write-Host ""
    Write-Host "  Skipping hotkey task registration." -ForegroundColor DarkGray
    Write-Host "  You can still run the switcher manually:" -ForegroundColor DarkGray
    Write-Host "    python switcher.py" -ForegroundColor White
} else {
    Write-Host "  ✓ AutoHotkey found: $AhkExe" -ForegroundColor Green

    # Remove existing task
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

    $Action = New-ScheduledTaskAction `
        -Execute $AhkExe `
        -Argument "`"$AhkScript`""

    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

    $Settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -StartWhenAvailable

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -Description "Karl Productivity OS - Intent Switcher Global Hotkeys" | Out-Null

    Write-Host "  ✓ Hotkey task registered: $TaskName" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Start hotkeys now:" -ForegroundColor Cyan
    Write-Host "    Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor White
}

# ── Step 4: Create .vscode workspace file if it doesn't exist
$WorkspaceFile = "C:\Users\Karl\Documents\productivity-os\.vscode\productivity-os.code-workspace"
$WorkspaceDir  = Split-Path $WorkspaceFile

if (-not (Test-Path $WorkspaceFile)) {
    if (-not (Test-Path $WorkspaceDir)) {
        New-Item -ItemType Directory -Path $WorkspaceDir -Force | Out-Null
    }
    $workspace = @{
        folders = @(
            @{ path = "C:\Users\Karl\Documents\productivity-os" }
        )
        settings = @{}
    } | ConvertTo-Json -Depth 5
    Set-Content -Path $WorkspaceFile -Value $workspace
    Write-Host "  ✓ VSCode workspace created: $WorkspaceFile" -ForegroundColor Green
} else {
    Write-Host "  ✓ VSCode workspace already exists" -ForegroundColor Green
}

Write-Host ""
Write-Host "─────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Usage:" -ForegroundColor Cyan
Write-Host "    python switcher.py              # interactive picker"
Write-Host "    python switcher.py build        # switch to Build mode"
Write-Host "    python switcher.py --infer      # let Ollama pick"
Write-Host "    python switcher.py --status     # current session info"
Write-Host "    python switcher.py --end        # end session + save re-entry note"
Write-Host "    python switcher.py --history    # recent sessions"
Write-Host ""
Write-Host "  Hotkeys (after AHK starts):" -ForegroundColor Cyan
Write-Host "    Win+1  →  Build"
Write-Host "    Win+2  →  Debug"
Write-Host "    Win+3  →  Learn"
Write-Host "    Win+4  →  Admin"
Write-Host "    Win+5  →  Review"
Write-Host "    Win+0  →  Infer from activity"
Write-Host "    Win+-  →  End session"
Write-Host "    Win+=  →  Status"
Write-Host ""
