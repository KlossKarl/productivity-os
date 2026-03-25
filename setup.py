"""
Productivity OS — Setup
Run this once to configure everything.

    python setup.py

Detects your paths, finds Obsidian + browser, checks Ollama,
pulls required models, and writes a populated config.yaml.
"""

import os
import sys
import subprocess
import shutil
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[ERROR] pyyaml not installed. Run: pip install pyyaml")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("[ERROR] requests not installed. Run: pip install requests")
    sys.exit(1)

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

REPO_ROOT  = Path(__file__).parent
CONFIG_OUT = REPO_ROOT / "config.yaml"

OLLAMA_URL     = "http://localhost:11434"
REQUIRED_MODELS = ["llama3:8b", "deepseek-r1:14b", "mxbai-embed-large"]

BRAVE_HISTORY_PATH = (
    Path.home()
    / "AppData/Local/BraveSoftware/Brave-Browser/User Data/Default/History"
)
CHROME_HISTORY_PATH = (
    Path.home()
    / "AppData/Local/Google/Chrome/User Data/Default/History"
)

OBSIDIAN_SEARCH_DIRS = [
    Path.home() / "Documents",
    Path.home() / "Desktop",
    Path.home(),
]

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def banner(text: str):
    width = 60
    print("\n" + "═" * width)
    print(f"  {text}")
    print("═" * width)

def step(n: int, text: str):
    print(f"\n[{n}] {text}")

def ok(text: str):
    print(f"    ✓ {text}")

def warn(text: str):
    print(f"    ⚠  {text}")

def ask(prompt: str, default: str = "") -> str:
    if default:
        result = input(f"    {prompt} [{default}]: ").strip()
        return result if result else default
    return input(f"    {prompt}: ").strip()

def ask_pick(prompt: str, options: list) -> str:
    print(f"    {prompt}")
    for i, opt in enumerate(options, 1):
        print(f"      {i}. {opt}")
    while True:
        choice = input(f"    Enter number (1-{len(options)}): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1]
        print(f"    Invalid choice, try again.")

# ─────────────────────────────────────────────
# STEP 1 — USER INFO
# ─────────────────────────────────────────────

def get_user_info() -> dict:
    step(1, "User info")
    windows_username = os.environ.get("USERNAME", Path.home().name)
    ok(f"Windows username detected: {windows_username}")

    name = ask("Your first name (used in LLM prompts)")
    while not name:
        name = ask("First name can't be empty")

    return {"name": name, "windows_username": windows_username}

# ─────────────────────────────────────────────
# STEP 2 — OBSIDIAN VAULT
# ─────────────────────────────────────────────

def find_obsidian_vaults() -> list:
    """Search common locations for Obsidian vaults (.obsidian folder = vault root)."""
    found = []
    for search_dir in OBSIDIAN_SEARCH_DIRS:
        if not search_dir.exists():
            continue
        # Look for .obsidian marker up to 2 levels deep
        for candidate in search_dir.iterdir():
            if candidate.is_dir() and (candidate / ".obsidian").exists():
                found.append(candidate)
        # Also check one level deeper (e.g. Documents/Notes/MyVault)
        for sub in search_dir.iterdir():
            if sub.is_dir():
                try:
                    for candidate in sub.iterdir():
                        if candidate.is_dir() and (candidate / ".obsidian").exists():
                            found.append(candidate)
                except PermissionError:
                    pass
    return list(dict.fromkeys(found))  # dedupe, preserve order

def get_obsidian_vault() -> str:
    step(2, "Finding Obsidian vault")
    vaults = find_obsidian_vaults()

    if len(vaults) == 1:
        ok(f"Found: {vaults[0]}")
        confirm = ask("Use this vault? (y/n)", "y")
        if confirm.lower() == "y":
            return str(vaults[0])

    elif len(vaults) > 1:
        ok(f"Found {len(vaults)} vaults:")
        vault = ask_pick("Which vault should Productivity OS use?", [str(v) for v in vaults])
        return vault

    warn("No Obsidian vault found automatically.")
    path = ask("Enter the full path to your Obsidian vault")
    while not Path(path).exists():
        warn(f"Path not found: {path}")
        path = ask("Enter the full path to your Obsidian vault")
    return path

# ─────────────────────────────────────────────
# STEP 3 — BROWSER HISTORY
# ─────────────────────────────────────────────

def get_browser_history() -> tuple[str, str]:
    """Returns (history_path, browser_type)."""
    step(3, "Finding browser history")

    if BRAVE_HISTORY_PATH.exists():
        ok(f"Found Brave history: {BRAVE_HISTORY_PATH}")
        return str(BRAVE_HISTORY_PATH), "brave"

    if CHROME_HISTORY_PATH.exists():
        ok(f"Found Chrome history: {CHROME_HISTORY_PATH}")
        return str(CHROME_HISTORY_PATH), "chrome"

    warn("Could not auto-detect Brave or Chrome history.")
    print("    Common locations:")
    print(r"      Brave:  %LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\Default\History")
    print(r"      Chrome: %LOCALAPPDATA%\Google\Chrome\User Data\Default\History")
    path = ask("Enter the full path to your browser History file")
    while not Path(path).exists():
        warn(f"File not found: {path}")
        path = ask("Enter the full path to your browser History file")

    browser_type = "brave" if "brave" in path.lower() else "chrome"
    return path, browser_type

# ─────────────────────────────────────────────
# STEP 4 — STANDARD PATHS
# ─────────────────────────────────────────────

def get_paths(obsidian_vault: str) -> dict:
    step(4, "Setting up paths")

    downloads_dir = Path.home() / "Downloads"
    output_dir    = REPO_ROOT / "output"
    chroma_dir    = Path.home() / "Documents" / "second_brain_db"
    shared_db     = Path.home() / "Documents" / "productivity_os.db"

    ok(f"Downloads:   {downloads_dir}")
    ok(f"Output dir:  {output_dir}")
    ok(f"ChromaDB:    {chroma_dir}")
    ok(f"Shared DB:   {shared_db}")

    # Create output dir now so scripts don't have to worry about it
    output_dir.mkdir(parents=True, exist_ok=True)

    return {
        "obsidian_vault": obsidian_vault,
        "downloads_dir":  str(downloads_dir),
        "output_dir":     str(output_dir),
        "chroma_dir":     str(chroma_dir),
        "shared_db":      str(shared_db),
    }

# ─────────────────────────────────────────────
# STEP 5 — OLLAMA CHECK
# ─────────────────────────────────────────────

def check_ollama() -> bool:
    step(5, "Checking Ollama")
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        ok("Ollama is running")
        return True
    except Exception:
        warn("Ollama is not running or not installed.")
        print()
        print("    To install Ollama:")
        print("      https://ollama.com/download")
        print()
        print("    To start Ollama:")
        print("      ollama serve")
        print()
        skip = ask("Skip model pulls and continue? (y/n)", "y")
        return False

# ─────────────────────────────────────────────
# STEP 6 — MODEL PULLS
# ─────────────────────────────────────────────

def pull_models():
    step(6, "Pulling required Ollama models")
    print(f"    Models needed: {', '.join(REQUIRED_MODELS)}")
    print()

    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        installed = {m["name"].split(":")[0] + ":" + m["name"].split(":")[-1]
                     for m in resp.json().get("models", [])}
    except Exception:
        installed = set()

    for model in REQUIRED_MODELS:
        if model in installed:
            ok(f"{model} — already installed")
            continue

        print(f"    Pulling {model}...")
        try:
            result = subprocess.run(
                ["ollama", "pull", model],
                capture_output=False,
                text=True,
            )
            if result.returncode == 0:
                ok(f"{model} — pulled successfully")
            else:
                warn(f"{model} — pull failed (you can run: ollama pull {model})")
        except FileNotFoundError:
            warn(f"ollama command not found — run manually: ollama pull {model}")
            break

# ─────────────────────────────────────────────
# STEP 7 — WRITE CONFIG
# ─────────────────────────────────────────────

def write_config(user: dict, paths: dict, browser: dict):
    step(7, "Writing config.yaml")

    config = {
        "user": {
            "name": user["name"],
            "windows_username": user["windows_username"],
        },
        "paths": paths,
        "browser": {
            "history_path": browser["history_path"],
            "browser_type": browser["browser_type"],
        },
        "second_brain": {
            "vaults": [paths["obsidian_vault"]],
            "codebases": [],
            "code_extensions": [".py", ".js", ".ts", ".jsx", ".tsx", ".md", ".sql", ".yaml", ".toml"],
            "skip_folders": [
                "node_modules", ".git", "__pycache__", ".venv", "venv",
                "dist", "build", ".next", ".obsidian", ".trash"
            ],
            "embed_model": "mxbai-embed-large",
            "chat_model": "deepseek-r1:14b",
            "top_k": 6,
            "chunk_size": 800,
            "chunk_overlap": 150,
        },
        "models": {
            "default": "llama3:8b",
            "reasoning": "deepseek-r1:14b",
            "vision": "llava:7b",
            "embedding": "mxbai-embed-large",
        },
        "ollama": {
            "url": OLLAMA_URL,
            "default_model": "llama3:8b",
            "reasoning_model": "deepseek-r1:14b",
            "embedding_model": "mxbai-embed-large",
        },
        "whisper": {
            "model": "medium",
        },
    }

    # Back up existing config if present
    if CONFIG_OUT.exists():
        backup = CONFIG_OUT.with_suffix(".yaml.bak")
        shutil.copy2(CONFIG_OUT, backup)
        warn(f"Existing config backed up to: {backup.name}")

    with open(CONFIG_OUT, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    ok(f"Written: {CONFIG_OUT}")

# ─────────────────────────────────────────────
# STEP 8 — SUMMARY
# ─────────────────────────────────────────────

def print_summary(user: dict, paths: dict, browser: dict):
    banner("Setup Complete")
    print(f"""
  User:         {user['name']} ({user['windows_username']})
  Obsidian:     {paths['obsidian_vault']}
  Downloads:    {paths['downloads_dir']}
  Output:       {paths['output_dir']}
  ChromaDB:     {paths['chroma_dir']}
  Browser:      {browser['browser_type']} → {browser['history_path']}
  Config:       {CONFIG_OUT}

  Next steps:
    python second_brain.py --index       # index your vault
    python second_brain.py --chat        # chat with your notes
    python browser_analysis.py           # run browser report
    python transcribe.py <file>          # transcribe audio/video

  To add codebases to Second Brain, edit config.yaml:
    second_brain:
      codebases:
        - C:\\path\\to\\your\\repo
""")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    banner("Productivity OS — Setup")
    print("  This will configure all scripts for your machine.")
    print("  Takes about 2 minutes (+ model download time).")

    user          = get_user_info()
    obsidian_path = get_obsidian_vault()
    history_path, browser_type = get_browser_history()
    paths         = get_paths(obsidian_path)
    ollama_ok     = check_ollama()

    if ollama_ok:
        pull = ask("\n  Pull required Ollama models now? (y/n)", "y")
        if pull.lower() == "y":
            pull_models()
        else:
            print(f"    Skipped. Run manually: ollama pull {' && ollama pull '.join(REQUIRED_MODELS)}")

    write_config(
        user=user,
        paths=paths,
        browser={"history_path": history_path, "browser_type": browser_type},
    )

    print_summary(user, paths, {"history_path": history_path, "browser_type": browser_type})

if __name__ == "__main__":
    main()
