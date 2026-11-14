"""
Core logic of the PFS QoL Launcher (no GUI code here, so it can be tested
on any OS).

- finds Pirate Fighting Simulator through Steam (registry + libraryfolders.vdf)
- installs / updates / removes UE4SS and the PFS_QoL mod
- switches between Vanilla and QoL by enabling/disabling UE4SS' proxy DLL
- reads and writes the launcher-managed lines of the mod's config.lua
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

APP_ID = "2186400"
GAME_DIR_NAME = "Pirate Fighting Simulator"
EXE_NAME = "PirateFS-Win64-Shipping.exe"

UE4SS_VERSION = "3.0.1"
UE4SS_URL = (
    "https://github.com/UE4SS-RE/RE-UE4SS/releases/download/"
    f"v{UE4SS_VERSION}/UE4SS_v{UE4SS_VERSION}.zip"
)

PROXY_DLL = "dwmapi.dll"
PROXY_DLL_OFF = "dwmapi.dll.qol-disabled"
MANIFEST = "pfs_qol_install.json"
MOD_NAME = "PFS_QoL"

# UE4SS ships some example mods that unlock the developer console and the
# cheat manager. They have nothing to do with QoL and would be a real unfair
# advantage, so the installer turns them off.
DISABLED_UE4SS_MODS = ("CheatManagerEnablerMod", "ConsoleEnablerMod", "ConsoleCommandsMod")

# Keys the launcher offers. Values are UE4SS `Key.<NAME>` names.
KEY_CHOICES = (
    [f"F{i}" for i in range(1, 13)]
    + ["INS", "DEL", "HOME", "END", "PAGE_UP", "PAGE_DOWN", "PAUSE", "SCROLL_LOCK"]
    + [f"NUM_{w}" for w in ("ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE")]
    + ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"]
    + [chr(c) for c in range(ord("A"), ord("Z") + 1)]
)
# Keys the game itself uses (from its input bindings) -> warn the user.
GAME_KEYS = {"F8", "V", "W", "A", "S", "D", "E", "R", "Q", "F", "G", "X", "C",
             "ONE", "TWO", "THREE", "FOUR", "FIVE"}

_DIGITS = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"]
_TK_SPECIAL = {
    "Insert": "INS", "Delete": "DEL", "Home": "HOME", "End": "END",
    "Prior": "PAGE_UP", "Next": "PAGE_DOWN", "Pause": "PAUSE", "Scroll_Lock": "SCROLL_LOCK",
}


def key_from_tk(keysym: str) -> str | None:
    """Translate a Tk keysym into a UE4SS key name (or None if unsupported)."""
    if re.fullmatch(r"F([1-9]|1[0-2])", keysym):
        return keysym
    if len(keysym) == 1 and keysym.isalpha():
        return keysym.upper()
    if len(keysym) == 1 and keysym.isdigit():
        return _DIGITS[int(keysym)]
    m = re.fullmatch(r"KP_(\d)", keysym)
    if m:
        return "NUM_" + _DIGITS[int(m.group(1))]
    return _TK_SPECIAL.get(keysym)


def key_label(name: str) -> str:
    """Human readable label for a UE4SS key name."""
    if name in _DIGITS:
        return str(_DIGITS.index(name))
    if name.startswith("NUM_") and name[4:] in _DIGITS:
        return "Num " + str(_DIGITS.index(name[4:]))
    return {"INS": "Insert", "DEL": "Delete", "PAGE_UP": "Page Up", "PAGE_DOWN": "Page Down",
            "SCROLL_LOCK": "Scroll Lock", "HOME": "Home", "END": "End", "PAUSE": "Pause"}.get(name, name)


# ---------------------------------------------------------------------------
#  Finding the game
# ---------------------------------------------------------------------------
def steam_roots() -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg
            for hive, key, value in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
            ):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        roots.append(Path(winreg.QueryValueEx(k, value)[0]))
                except OSError:
                    pass
        except ImportError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                roots.append(Path(os.environ[env]) / "Steam")
    else:  # Linux/Proton – mostly useful for testing
        home = Path.home()
        roots += [home / ".steam/steam", home / ".local/share/Steam"]
    out, seen = [], set()
    for r in roots:
        key = str(r).lower().replace("\\", "/")
        if key not in seen and r.exists():
            seen.add(key)
            out.append(r)
    return out


def library_folders(steam_root: Path) -> list[Path]:
    libs = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        text = vdf.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'"path"\s+"((?:[^"\\]|\\.)*)"', text):
            libs.append(Path(m.group(1).replace("\\\\", "\\")))
    return libs


def game_dir_in_library(lib: Path) -> Path | None:
    acf = lib / "steamapps" / f"appmanifest_{APP_ID}.acf"
    names = []
    if acf.exists():
        m = re.search(r'"installdir"\s+"([^"]+)"', acf.read_text(encoding="utf-8", errors="replace"))
        if m:
            names.append(m.group(1))
    names.append(GAME_DIR_NAME)
    for n in names:
        d = lib / "steamapps" / "common" / n
        if is_game_dir(d):
            return d
    return None


def is_game_dir(d: Path) -> bool:
    return (d / "PirateFS" / "Binaries" / "Win64" / EXE_NAME).exists()


def find_game() -> Path | None:
    for root in steam_roots():
        for lib in library_folders(root):
            d = game_dir_in_library(lib)
            if d:
                return d
    return None


def normalize_game_dir(p: Path) -> Path | None:
    """Accept the game folder, the Win64 folder or the exe the user picked."""
    p = Path(p)
    if p.is_file():
        p = p.parent
    for cand in (p, *p.parents):
        if is_game_dir(cand):
            return cand
    return None


def win64_dir(game_dir: Path) -> Path:
    return game_dir / "PirateFS" / "Binaries" / "Win64"


# ---------------------------------------------------------------------------
#  Status
# ---------------------------------------------------------------------------
@dataclass
class Status:
    game_dir: Path | None
    ue4ss: bool = False
    mod: bool = False
    mod_version: str | None = None
    mode: str = "vanilla"           # "qol" | "vanilla"
    managed: bool = False           # installed by this launcher?
    extra: dict = field(default_factory=dict)


def read_mod_version(win64: Path) -> str | None:
    main = win64 / "Mods" / MOD_NAME / "Scripts" / "main.lua"
    if not main.exists():
        return None
    m = re.search(r'local VERSION = "([^"]+)"', main.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else "?"


def get_status(game_dir: Path | None) -> Status:
    if not game_dir or not is_game_dir(game_dir):
        return Status(None)
    w = win64_dir(game_dir)
    ue4ss = (w / "UE4SS.dll").exists() and ((w / PROXY_DLL).exists() or (w / PROXY_DLL_OFF).exists())
    ver = read_mod_version(w)
    return Status(
        game_dir=game_dir,
        ue4ss=ue4ss,
        mod=ver is not None,
        mod_version=ver,
        mode="qol" if (w / PROXY_DLL).exists() else "vanilla",
        managed=(w / MANIFEST).exists(),
    )


# ---------------------------------------------------------------------------
#  Install / update / uninstall
# ---------------------------------------------------------------------------
def bundled_mod_dir() -> Path:
    """The PFS_QoL folder shipped with the launcher (PyInstaller or repo)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for cand in (base / MOD_NAME, base.parent / "mod" / MOD_NAME, base / "mod" / MOD_NAME):
        if (cand / "Scripts" / "main.lua").exists():
            return cand
    raise FileNotFoundError("Bundled PFS_QoL mod not found")


def bundled_mod_version() -> str:
    m = re.search(r'local VERSION = "([^"]+)"',
                  (bundled_mod_dir() / "Scripts" / "main.lua").read_text(encoding="utf-8"))
    return m.group(1) if m else "?"


def download_ue4ss(progress=None) -> Path:
    tmp = Path(tempfile.gettempdir()) / f"UE4SS_v{UE4SS_VERSION}.zip"
    req = urllib.request.Request(UE4SS_URL, headers={"User-Agent": "PFS-QoL-Launcher"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    return tmp


def _read_manifest(w: Path) -> dict:
    try:
        return json.loads((w / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"files": []}


def install_ue4ss(w: Path, zip_path: Path) -> list[str]:
    """Extract UE4SS into Win64 and remember which files belong to it."""
    files = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/") or name.startswith("/") or ".." in name.split("/"):
                continue
            target = w / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            files.append(name)
    # a previous "Vanilla" switch may have left the disabled DLL behind
    if (w / PROXY_DLL_OFF).exists():
        (w / PROXY_DLL_OFF).unlink()
    disable_cheat_mods(w)
    return files


def disable_cheat_mods(w: Path) -> None:
    mods_txt = w / "Mods" / "mods.txt"
    if not mods_txt.exists():
        return
    text = mods_txt.read_text(encoding="utf-8-sig", errors="replace")
    for mod in DISABLED_UE4SS_MODS:
        text = re.sub(rf"^(\s*{mod}\s*:\s*)1\s*$", r"\g<1>0", text, flags=re.M)
    mods_txt.write_text(text, encoding="utf-8")


def install_mod(w: Path) -> None:
    """Copy the bundled mod, keeping the user's launcher settings."""
    target = w / "Mods" / MOD_NAME
    old = read_settings(w) if (target / "Scripts" / "config.lua").exists() else None
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(bundled_mod_dir(), target)
    (target / "enabled.txt").write_text("", encoding="utf-8")
    if old:
        write_settings(w, old)


def install(game_dir: Path, ue4ss_zip: Path | None = None, progress=None) -> None:
    w = win64_dir(game_dir)
    manifest = _read_manifest(w)
    if not (w / "UE4SS.dll").exists() or ue4ss_zip is not None:
        zip_path = ue4ss_zip or download_ue4ss(progress)
        manifest["files"] = sorted(set(manifest.get("files", [])) | set(install_ue4ss(w, zip_path)))
        manifest["ue4ss"] = UE4SS_VERSION
    else:
        disable_cheat_mods(w)
    install_mod(w)
    manifest["mod"] = bundled_mod_version()
    (w / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    set_mode(game_dir, "qol")


def uninstall(game_dir: Path) -> None:
    w = win64_dir(game_dir)
    manifest = _read_manifest(w)
    shutil.rmtree(w / "Mods" / MOD_NAME, ignore_errors=True)
    for name in manifest.get("files", []):
        p = w / name
        if p.is_file():
            p.unlink()
    for name in (PROXY_DLL, PROXY_DLL_OFF, "UE4SS.dll", "UE4SS-settings.ini", "UE4SS.log", MANIFEST):
        if (w / name).exists():
            (w / name).unlink()
    # remove now-empty folders left by UE4SS (Mods/..., etc.)
    dirs = set()
    for n in manifest.get("files", []):
        for parent in (w / n).parents:
            if parent == w or w not in parent.parents:
                break
            dirs.add(parent)
    for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        try:
            if d != w and d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------------------
#  Vanilla / QoL switch and game start
# ---------------------------------------------------------------------------
def set_mode(game_dir: Path, mode: str) -> None:
    w = win64_dir(game_dir)
    on, off = w / PROXY_DLL, w / PROXY_DLL_OFF
    if mode == "qol":
        if not on.exists() and off.exists():
            off.rename(on)
        if not on.exists():
            raise FileNotFoundError("UE4SS is not installed")
    else:
        if on.exists():
            if off.exists():
                off.unlink()
            on.rename(off)


def launch_game() -> None:
    url = f"steam://rungameid/{APP_ID}"
    if sys.platform == "win32":
        os.startfile(url)  # type: ignore[attr-defined]
    else:
        import subprocess
        subprocess.Popen(["xdg-open", url])


# ---------------------------------------------------------------------------
#  Settings (stored directly in the mod's config.lua)
# ---------------------------------------------------------------------------
DEFAULT_SETTINGS = {"require_all": True, "toggle_key": "F6", "dump_key": "F7", "language": "de"}

_PATTERNS = {
    "require_all": (r"(REQUIRE_ALL_PLAYERS\s*=\s*)(true|false)", lambda v: "true" if v else "false"),
    "toggle_key": (r"(KEY_TOGGLE\s*=\s*Key\.)([A-Z0-9_]+)", str),
    "dump_key": (r"(KEY_DUMP\s*=\s*Key\.)([A-Z0-9_]+)", str),
    "language": (r'(LANGUAGE\s*=\s*")([a-z]+)(")', str),
}


def config_path(w: Path) -> Path:
    return w / "Mods" / MOD_NAME / "Scripts" / "config.lua"


def read_settings(w: Path) -> dict:
    s = dict(DEFAULT_SETTINGS)
    p = config_path(w)
    if not p.exists():
        return s
    text = p.read_text(encoding="utf-8", errors="replace")
    for key, (pat, _) in _PATTERNS.items():
        m = re.search(pat, text)
        if m:
            s[key] = (m.group(2) == "true") if key == "require_all" else m.group(2)
    return s


def write_settings(w: Path, settings: dict) -> None:
    p = config_path(w)
    text = p.read_text(encoding="utf-8", errors="replace")
    for key, (pat, fmt) in _PATTERNS.items():
        if key not in settings:
            continue
        val = fmt(settings[key])
        if re.search(pat, text):
            if key == "language":
                text = re.sub(pat, lambda m: m.group(1) + val + m.group(3), text, count=1)
            else:
                text = re.sub(pat, lambda m: m.group(1) + val, text, count=1)
        elif key == "language":  # older config without LANGUAGE line
            text = text.replace("return {", f'return {{\n    LANGUAGE = "{val}",', 1)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
#  Launcher preferences (remembered game folder)
# ---------------------------------------------------------------------------
def prefs_path() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return base / "PFS-QoL-Launcher" / "prefs.json"


def load_prefs() -> dict:
    try:
        return json.loads(prefs_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_prefs(prefs: dict) -> None:
    p = prefs_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
