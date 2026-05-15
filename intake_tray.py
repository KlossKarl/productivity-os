"""
Intake Tray — Productivity OS
System tray app with drag-and-drop drop zone.

Sits quietly in the Windows taskbar.
Click the icon → drop zone window opens.
Drag any file onto it → routed to the right pipeline automatically.

Install:
    pip install pystray pillow tkinterdnd2

Usage:
    python intake_tray.py
    python intake_tray.py --minimized    # start minimized to tray immediately
"""

import sys
import os
import shutil
import threading
import argparse
from pathlib import Path
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import font as tkfont
except ImportError:
    print("[ERROR] tkinter not available.")
    sys.exit(1)

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False
    print("[WARN] tkinterdnd2 not installed — drag-and-drop disabled, using file picker.")
    print("       To enable DnD: pip install tkinterdnd2")

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    print("[WARN] pystray/pillow not installed — running as window only (no tray icon).")
    print("       To enable tray: pip install pystray pillow")

try:
    import yaml
except ImportError:
    print("[ERROR] pyyaml not installed. Run: pip install pyyaml")
    sys.exit(1)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent
CONFIG_PATH  = PROJECT_ROOT / "config.yaml"

# File type → label for the activity log
ROUTE_LABELS = {
    '.mp3': 'audio', '.wav': 'audio', '.m4a': 'audio', '.m4b': 'audio',
    '.mp4': 'video', '.mkv': 'video', '.webm': 'video', '.mov': 'video',
    '.m4v': 'video', '.avi': 'video', '.ogg': 'audio', '.flac': 'audio',
    '.pdf': 'pdf',
    '.md': 'markdown', '.markdown': 'markdown',
    '.url': 'web', '.txt': 'web → checking...',
}

# ── Palette ──────────────────────────────────
BG          = "#0f0f0f"
BG_PANEL    = "#161616"
BG_DROP     = "#111111"
BG_DROP_HOV = "#1a1f1a"
ACCENT      = "#39ff7e"       # electric green
ACCENT_DIM  = "#1a4a2e"
TEXT        = "#e8e8e8"
TEXT_DIM    = "#555555"
TEXT_MUTED  = "#333333"
BORDER      = "#222222"
BORDER_HOV  = "#39ff7e"
FAIL        = "#ff4444"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f) or {}


def get_intake_folder() -> Path:
    cfg = load_config()
    intake = cfg.get('intake', {})
    default = PROJECT_ROOT / "intake"
    folder = Path(intake.get('folder', default))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def copy_to_intake(src: Path) -> bool:
    """Copy a file into the intake folder. The watcher picks it up from there."""
    try:
        intake = get_intake_folder()
        dest = intake / src.name
        if dest.exists():
            ts = datetime.now().strftime('%H%M%S')
            dest = intake / f"{src.stem}_{ts}{src.suffix}"
        shutil.copy2(src, dest)
        return True
    except Exception as e:
        print(f"[ERROR] copy_to_intake: {e}")
        return False


def route_label(path: Path) -> str:
    return ROUTE_LABELS.get(path.suffix.lower(), f"unknown ({path.suffix})")


# ─────────────────────────────────────────────
# TRAY ICON — generated programmatically
# ─────────────────────────────────────────────

def make_icon(size=64) -> "Image":
    """
    Draws a minimal icon: dark square, green inbox arrow.
    No image files needed.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Background pill
    d.rounded_rectangle([0, 0, size-1, size-1], radius=12,
                         fill=(15, 15, 15, 255), outline=(57, 255, 126, 200), width=2)

    # Down-arrow (inbox symbol)
    cx, cy = size // 2, size // 2
    aw = size // 3
    ah = size // 3
    col = (57, 255, 126, 255)

    # Shaft
    d.rectangle([cx - 3, cy - ah//2 - 4, cx + 3, cy + 2], fill=col)
    # Arrowhead
    d.polygon([
        (cx - aw//2, cy + 2),
        (cx + aw//2, cy + 2),
        (cx, cy + ah//2 + 2),
    ], fill=col)
    # Tray base line
    d.rectangle([cx - aw//2, cy + ah//2 + 6, cx + aw//2, cy + ah//2 + 10], fill=col)

    return img


# ─────────────────────────────────────────────
# DROP ZONE WINDOW
# ─────────────────────────────────────────────

class IntakeWindow:
    MAX_LOG = 40

    def __init__(self, root, on_close_to_tray=None):
        self.root = root
        self.on_close_to_tray = on_close_to_tray
        self.log_entries: list[tuple[str, str]] = []  # (text, color)
        self._build()

    def _build(self):
        r = self.root
        r.title("Intake — Productivity OS")
        r.configure(bg=BG)
        r.resizable(False, False)
        r.geometry("420x540")

        # Close → hide to tray (not quit)
        if self.on_close_to_tray:
            r.protocol("WM_DELETE_WINDOW", self.on_close_to_tray)

        self._build_header()
        self._build_drop_zone()
        self._build_log()
        self._build_footer()

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=BG, pady=0)
        hdr.pack(fill='x', padx=20, pady=(18, 0))

        tk.Label(hdr, text="⬇  INTAKE", bg=BG, fg=ACCENT,
                 font=("Courier New", 13, "bold")).pack(side='left')

        intake_path = str(get_intake_folder())
        short = "…" + intake_path[-28:] if len(intake_path) > 30 else intake_path
        tk.Label(hdr, text=short, bg=BG, fg=TEXT_DIM,
                 font=("Courier New", 8)).pack(side='right', pady=(4, 0))

    def _build_drop_zone(self):
        outer = tk.Frame(self.root, bg=BG, padx=20, pady=12)
        outer.pack(fill='x')

        self.drop_frame = tk.Frame(
            outer, bg=BG_DROP,
            highlightbackground=BORDER, highlightthickness=1,
            relief='flat', cursor="hand2"
        )
        self.drop_frame.pack(fill='x', ipady=28)

        # Center content
        inner = tk.Frame(self.drop_frame, bg=BG_DROP)
        inner.pack(expand=True)

        self.drop_icon = tk.Label(inner, text="⬇", bg=BG_DROP, fg=ACCENT,
                                  font=("Courier New", 32))
        self.drop_icon.pack(pady=(10, 4))

        self.drop_label = tk.Label(
            inner, bg=BG_DROP, fg=TEXT,
            font=("Courier New", 10, "bold"),
            text="drop files here" if DND_AVAILABLE else "click to select files"
        )
        self.drop_label.pack()

        self.drop_sub = tk.Label(
            inner,
            text="audio · pdf · url · markdown",
            bg=BG_DROP, fg=TEXT_DIM,
            font=("Courier New", 8)
        )
        self.drop_sub.pack(pady=(2, 10))

        # Bind drag-and-drop if available
        if DND_AVAILABLE:
            for widget in (self.drop_frame, inner,
                           self.drop_icon, self.drop_label, self.drop_sub):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind('<<Drop>>', self._on_drop)
                widget.dnd_bind('<<DragEnter>>', self._on_drag_enter)
                widget.dnd_bind('<<DragLeave>>', self._on_drag_leave)

        # Fallback: click to browse
        for widget in (self.drop_frame, inner,
                       self.drop_icon, self.drop_label, self.drop_sub):
            widget.bind("<Button-1>", self._on_click_browse)

    def _build_log(self):
        log_outer = tk.Frame(self.root, bg=BG, padx=20)
        log_outer.pack(fill='both', expand=True)

        tk.Label(log_outer, text="ACTIVITY", bg=BG, fg=TEXT_MUTED,
                 font=("Courier New", 7, "bold")).pack(anchor='w', pady=(0, 4))

        panel = tk.Frame(log_outer, bg=BG_PANEL,
                         highlightbackground=BORDER, highlightthickness=1)
        panel.pack(fill='both', expand=True)

        self.log_text = tk.Text(
            panel, bg=BG_PANEL, fg=TEXT_DIM,
            font=("Courier New", 8),
            relief='flat', bd=0,
            state='disabled',
            wrap='word',
            cursor='arrow',
            height=12,
            padx=10, pady=8,
            selectbackground=ACCENT_DIM,
        )
        self.log_text.pack(fill='both', expand=True)

        # Tag styles
        self.log_text.tag_config('ok',      foreground=ACCENT)
        self.log_text.tag_config('fail',    foreground=FAIL)
        self.log_text.tag_config('dim',     foreground=TEXT_DIM)
        self.log_text.tag_config('ts',      foreground=TEXT_MUTED)
        self.log_text.tag_config('route',   foreground="#888888")

        self._log("ready. watching intake folder.", 'dim')

    def _build_footer(self):
        foot = tk.Frame(self.root, bg=BG, pady=10)
        foot.pack(fill='x', padx=20)

        btn_style = dict(
            bg=BG_PANEL, fg=TEXT_DIM,
            font=("Courier New", 8),
            relief='flat', bd=0,
            padx=10, pady=4,
            cursor='hand2',
            activebackground=ACCENT_DIM,
            activeforeground=ACCENT,
        )

        tk.Button(foot, text="open folder", command=self._open_intake_folder,
                  **btn_style).pack(side='left')
        tk.Button(foot, text="clear log", command=self._clear_log,
                  **btn_style).pack(side='left', padx=(6, 0))

        self.status_dot = tk.Label(foot, text="● watching", bg=BG, fg=ACCENT,
                                   font=("Courier New", 8))
        self.status_dot.pack(side='right')

    # ── Drag-and-drop events ──────────────────

    def _on_drag_enter(self, event):
        self.drop_frame.config(highlightbackground=BORDER_HOV, bg=BG_DROP_HOV)
        self.drop_icon.config(bg=BG_DROP_HOV)
        self.drop_label.config(bg=BG_DROP_HOV)
        self.drop_sub.config(bg=BG_DROP_HOV)

    def _on_drag_leave(self, event):
        self.drop_frame.config(highlightbackground=BORDER, bg=BG_DROP)
        self.drop_icon.config(bg=BG_DROP)
        self.drop_label.config(bg=BG_DROP)
        self.drop_sub.config(bg=BG_DROP)

    def _on_drop(self, event):
        self._on_drag_leave(event)
        # tkinterdnd2 returns a space-separated list; braces wrap paths with spaces
        raw = event.data.strip()
        paths = self.root.tk.splitlist(raw)
        for p in paths:
            self._handle_file(Path(p))

    def _on_click_browse(self, event=None):
        from tkinter import filedialog
        files = filedialog.askopenfilenames(
            title="Select files for intake",
            parent=self.root,
        )
        for f in files:
            self._handle_file(Path(f))

    # ── File handling ─────────────────────────

    def _handle_file(self, path: Path):
        if not path.exists():
            self._log(f"✗ not found: {path.name}", 'fail')
            return

        label = route_label(path)
        ts = datetime.now().strftime('%H:%M:%S')
        self._log_entry(ts, path.name, label)

        def _copy():
            ok = copy_to_intake(path)
            tag = 'ok' if ok else 'fail'
            symbol = '✓' if ok else '✗'
            self.root.after(0, lambda: self._log(
                f"  {symbol} queued: {path.name}", tag
            ))

        threading.Thread(target=_copy, daemon=True).start()

    def _log_entry(self, ts: str, name: str, label: str):
        self.log_text.config(state='normal')
        self.log_text.insert('end', f"{ts}  ", 'ts')
        self.log_text.insert('end', f"{name}\n", 'dim')
        self.log_text.insert('end', f"         → {label}\n", 'route')
        self.log_text.see('end')
        self.log_text.config(state='disabled')

    def _log(self, text: str, tag: str = 'dim'):
        self.log_text.config(state='normal')
        self.log_text.insert('end', f"{text}\n", tag)
        self.log_text.see('end')
        self.log_text.config(state='disabled')

    def _clear_log(self):
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.config(state='disabled')
        self._log("log cleared.", 'dim')

    def _open_intake_folder(self):
        import subprocess
        folder = get_intake_folder()
        subprocess.Popen(f'explorer "{folder}"')

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self):
        self.root.withdraw()


# ─────────────────────────────────────────────
# TRAY ICON CONTROLLER
# ─────────────────────────────────────────────

class TrayController:
    def __init__(self, window: IntakeWindow, icon_img):
        self.window = window
        self.icon = pystray.Icon(
            name="intake",
            icon=icon_img,
            title="Intake — Productivity OS",
            menu=pystray.Menu(
                pystray.MenuItem("Open Intake", self._show, default=True),
                pystray.MenuItem("Open Folder", self._open_folder),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            )
        )

    def _show(self, icon=None, item=None):
        self.window.root.after(0, self.window.show)

    def _open_folder(self, icon=None, item=None):
        import subprocess
        folder = get_intake_folder()
        subprocess.Popen(f'explorer "{folder}"')

    def _quit(self, icon=None, item=None):
        self.icon.stop()
        self.window.root.after(0, self.window.root.destroy)

    def run(self):
        threading.Thread(target=self.icon.run, daemon=True).start()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Intake Tray — Productivity OS")
    parser.add_argument("--minimized", action="store_true",
                        help="Start minimized to tray")
    args = parser.parse_args()

    # Build root window
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    root.withdraw()  # hide until ready

    # Build tray controller if available
    tray = None
    if TRAY_AVAILABLE:
        icon_img = make_icon(64)
        win = IntakeWindow(root, on_close_to_tray=lambda: win.hide())
        tray = TrayController(win, icon_img)
        tray.run()
    else:
        win = IntakeWindow(root, on_close_to_tray=root.destroy)

    # Show window at launch unless --minimized
    if not args.minimized:
        win.show()
    elif not TRAY_AVAILABLE:
        # No tray and minimized requested — just show anyway
        win.show()

    root.mainloop()


if __name__ == "__main__":
    main()
