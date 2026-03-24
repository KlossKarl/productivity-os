; ─────────────────────────────────────────────────────────────
; Intent Switcher — Global Hotkeys
; Karl's Productivity OS - Project 17
;
; Install AutoHotkey v2: https://www.autohotkey.com/
; Then double-click this file (or run at startup via Task Scheduler)
;
; Hotkeys:
;   Win + 1  →  Build mode
;   Win + 2  →  Debug mode
;   Win + 3  →  Learn mode
;   Win + 4  →  Admin mode
;   Win + 5  →  Review mode
;   Win + 0  →  Infer mode from activity (Ollama)
;   Win + -  →  End current session + save re-entry note
;   Win + =  →  Show current session status
; ─────────────────────────────────────────────────────────────

#Requires AutoHotkey v2.0

PYTHON := "C:\Users\Karl\AppData\Local\Programs\Python\Python312\python.exe"
SWITCHER := "C:\Users\Karl\Documents\productivity-os\17_intent_switcher\switcher.py"

; Win + 1 → Build
#1:: {
    Run(PYTHON . " " . SWITCHER . " build", , "Hide")
}

; Win + 2 → Debug
#2:: {
    Run(PYTHON . " " . SWITCHER . " debug", , "Hide")
}

; Win + 3 → Learn
#3:: {
    Run(PYTHON . " " . SWITCHER . " learn", , "Hide")
}

; Win + 4 → Admin
#4:: {
    Run(PYTHON . " " . SWITCHER . " admin", , "Hide")
}

; Win + 5 → Review
#5:: {
    Run(PYTHON . " " . SWITCHER . " review", , "Hide")
}

; Win + 0 → Infer mode
#0:: {
    Run(PYTHON . " " . SWITCHER . " --infer", , "Hide")
}

; Win + - → End session
#-:: {
    Run(PYTHON . " " . SWITCHER . " --end", , "Hide")
}

; Win + = → Status (shows in a new terminal window)
#=:: {
    Run("cmd /k " . PYTHON . " " . SWITCHER . " --status")
}
