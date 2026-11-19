"""
PFS QoL Launcher – install the QoL mod and start Pirate Fighting Simulator
either with QoL or completely vanilla.

Run:  python pfs_qol_launcher.py          (needs: pip install pillow)
Dev:  python pfs_qol_launcher.py --screenshot out.png [--screen options]
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog

from PIL import ImageTk

import core
import crosshair as X
import theme

LAUNCHER_VERSION = "1.0.1"
W, H = 960, 600
BTN_W, BTN_H = 300, 40


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Restart this program elevated (UAC prompt). Returns True if started."""
    if sys.platform != "win32":
        return False
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        exe, params = sys.executable, " ".join(f'"{a}"' for a in [os.path.abspath(sys.argv[0]), *sys.argv[1:]])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)  # type: ignore[attr-defined]
    return rc > 32


def folder_writable(p: Path) -> bool:
    test = p / ".pfs_qol_write_test"
    try:
        test.write_text("x")
        test.unlink()
        return True
    except OSError:
        return False


class Launcher:
    def __init__(self, root: tk.Tk, screen: str = "main"):
        self.root = root
        root.title("PFS QoL Launcher")
        root.resizable(False, False)
        root.geometry(f"{W}x{H}")
        self.canvas = tk.Canvas(root, width=W, height=H, highlightthickness=0, bd=0, bg="#2e1a0e")
        self.canvas.pack()
        self.images: dict[str, list] = {}       # keep Tk image references alive
        self.busy = False
        self.key_capture = None
        self.entry = None

        families = set(tkfont.families())
        fam = next((f for f in ("Palatino Linotype", "Georgia", "Book Antiqua", "DejaVu Serif", "Times New Roman")
                    if f in families), "TkDefaultFont")
        self.f_text = (fam, 13)
        self.f_small = (fam, 11)
        self.f_bold = (fam, 13, "bold")

        self.bg = ImageTk.PhotoImage(theme.background(W, H))
        self.canvas.create_image(0, 0, image=self.bg, anchor="nw")
        try:
            self.icon = ImageTk.PhotoImage(theme.icon(64))
            root.iconphoto(True, self.icon)
        except Exception:
            pass

        self.prefs = core.load_prefs()
        self.game_dir = self._detect_game()
        self.settings = self._load_settings()
        root.bind("<Key>", self._on_key)

        if screen == "options":
            self.show_options()
        elif screen == "crosshair":
            self.show_crosshair()
        else:
            self.show_main()
        self.root.after(300, self._check_permissions)

    # ------------------------------------------------------------------ helpers
    def _detect_game(self) -> Path | None:
        saved = self.prefs.get("game_dir")
        if saved and core.is_game_dir(Path(saved)):
            return Path(saved)
        found = core.find_game()
        if found:
            self.prefs["game_dir"] = str(found)
            core.save_prefs(self.prefs)
        return found

    def _load_settings(self) -> dict:
        if self.game_dir and core.config_path(core.win64_dir(self.game_dir)).exists():
            return core.read_settings(core.win64_dir(self.game_dir))
        return dict(core.DEFAULT_SETTINGS, crosshair=X.default())

    def status(self) -> core.Status:
        return core.get_status(self.game_dir)

    def keep(self, group: str, img):
        self.images.setdefault(group, []).append(img)
        return img

    def clear(self, group: str = "ui"):
        self.canvas.delete(group)
        self.images.pop(group, None)
        if group == "dialog" and self.entry is not None:
            self.entry.destroy()
            self.entry = None

    def text(self, x, y, s, group="ui", font=None, fill="#f4ecd6", anchor="nw", width=None):
        return self.canvas.create_text(x, y, text=s, font=font or self.f_text, fill=fill, anchor=anchor,
                                       width=width, tags=(group,))

    def image(self, x, y, pil, group="ui", anchor="nw"):
        img = self.keep(group, ImageTk.PhotoImage(pil))
        return self.canvas.create_image(x, y, image=img, anchor=anchor, tags=(group,))

    def button(self, x, y, label, command, w=BTN_W, h=BTN_H, group="ui", style="normal", size=22):
        if style == "disabled":
            self.image(x, y, theme.button(w, h, label, "disabled", size), group)
            return
        normal = self.keep(group, ImageTk.PhotoImage(theme.button(w, h, label, style, size)))
        hover = self.keep(group, ImageTk.PhotoImage(theme.button(w, h, label, "hover", size)))
        item = self.canvas.create_image(x, y, image=normal, anchor="nw", tags=(group,))
        self.canvas.tag_bind(item, "<Enter>", lambda e: (self.canvas.itemconfigure(item, image=hover),
                                                         self.canvas.configure(cursor="hand2")))
        self.canvas.tag_bind(item, "<Leave>", lambda e: (self.canvas.itemconfigure(item, image=normal),
                                                         self.canvas.configure(cursor="")))
        self.canvas.tag_bind(item, "<Button-1>", lambda e: None if self.busy else command())

    def toast(self, msg: str, color: str = "#f4ecd6", ms: int = 5000):
        self.clear("toast")
        self.canvas.create_rectangle(W // 2 - 330, H - 46, W // 2 + 330, H - 14, fill="#1c0f07",
                                     outline="#966834", width=2, tags=("toast",))
        self.text(W // 2, H - 30, msg, group="toast", fill=color, anchor="center", font=self.f_text)
        if ms:
            tid = getattr(self, "_toast_id", None)
            if tid:
                self.root.after_cancel(tid)
            self._toast_id = self.root.after(ms, lambda: self.clear("toast"))

    def run_task(self, label: str, fn, done):
        """Run fn in a thread; done(error_or_None) is called in the UI thread."""
        self.busy = True
        self.toast(label, ms=0)

        def worker():
            err = None
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                err = e
            self.root.after(0, lambda: (setattr(self, "busy", False), done(err)))

        threading.Thread(target=worker, daemon=True).start()

    def _check_permissions(self):
        if not self.game_dir or sys.platform != "win32" or is_admin():
            return
        if not folder_writable(core.win64_dir(self.game_dir)):
            self.dialog(
                "Administrator rights needed",
                "The game is installed in a protected folder (e.g. Program Files). "
                "To install the mod or switch between Vanilla and QoL, the launcher "
                "has to run as administrator.",
                [("Restart as admin", "normal", self._restart_admin), ("Not now", "normal", None)],
            )

    def _restart_admin(self):
        if relaunch_as_admin():
            self.root.destroy()
        else:
            self.toast("Could not restart as administrator.", "#e26050")

    # ------------------------------------------------------------------ dialog
    def dialog(self, title: str, body: str, buttons: list, danger: bool = False):
        """Modal in-window dialog. buttons = [(label, style, callback_or_None), ...]"""
        g = "dialog"
        self.clear(g)
        self.image(0, 0, theme.dim(W, H), g)
        pw, ph = 600, 290
        px, py = (W - pw) // 2, (H - ph) // 2
        self.image(px, py, theme.panel(pw, ph), g)
        self.text(W // 2, py + 34, title, group=g, anchor="center",
                  font=(self.f_bold[0], 17, "bold"), fill="#e26050" if danger else "#e2aa54")
        self.text(px + 40, py + 70, body, group=g, width=pw - 80, font=self.f_text)
        bw = 220 if len(buttons) > 1 else 180
        total = len(buttons) * bw + (len(buttons) - 1) * 20
        bx = (W - total) // 2
        for label, style, cb in buttons:
            def click(cb=cb):
                self.clear(g)
                if cb:
                    cb()
            self.button(bx, py + ph - 70, label, click, w=bw, h=40, group=g, style=style, size=19)
            bx += bw + 20

    # ------------------------------------------------------------------ main menu
    def show_main(self):
        self.clear("ui")
        st = self.status()
        t = theme.title()
        self.image((W - t.width) // 2, 34, t)

        x, y, step = (W - BTN_W) // 2, 248, 46
        if not st.game_dir:
            buttons = [("Locate Game", self.browse_game, "normal"),
                       ("Exit", self.root.destroy, "normal")]
        else:
            installed = st.ue4ss and st.mod
            bundled = core.bundled_mod_version()
            if not installed:
                inst_label = "Install QoL"
            elif st.mod_version != bundled:
                inst_label = f"Update QoL ({bundled})"
            else:
                inst_label = "Repair / Reinstall"
            buttons = [
                ("Play with QoL", lambda: self.play("qol"), "normal" if installed else "disabled"),
                ("Play Vanilla", lambda: self.play("vanilla"), "normal"),
                (inst_label, self.install, "normal"),
                ("Options", self.show_options, "normal"),
                ("Uninstall", self.ask_uninstall, "normal" if st.ue4ss or st.mod else "disabled"),
                ("Exit", self.root.destroy, "normal"),
            ]
        for i, (label, cmd, style) in enumerate(buttons):
            self.button(x, y + i * step, label, cmd, style=style)

        # status board (bottom right)
        self.image(W - 280, H - 124, theme.panel(266, 110))
        rows = [
            ("Game", "found" if st.game_dir else "not found", "#f4ecd6" if st.game_dir else "#e26050"),
            ("UE4SS", core.UE4SS_VERSION if st.ue4ss else "not installed", "#f4ecd6"),
            ("QoL mod", st.mod_version or "not installed", "#f4ecd6"),
            ("Mode", "QoL" if st.mode == "qol" and st.ue4ss else "Vanilla", "#e2aa54"),
        ]
        for i, (k, v, c) in enumerate(rows):
            self.text(W - 262, H - 114 + i * 22, k, font=self.f_small, fill="#c8b496")
            self.text(W - 170, H - 114 + i * 22, v, font=self.f_small, fill=c)
        self.text(16, H - 34, f"Launcher {LAUNCHER_VERSION}", font=self.f_bold, fill="#f4ecd6")

    # ------------------------------------------------------------------ actions
    def play(self, mode: str):
        try:
            if self.status().ue4ss:
                core.set_mode(self.game_dir, mode)
            core.launch_game()
        except PermissionError:
            self.toast("No permission – close the game or restart the launcher as admin.", "#e26050")
            return
        except FileNotFoundError:
            self.toast("QoL is not installed yet.", "#e26050")
            return
        self.show_main()
        self.toast(f"Starting Pirate Fighting Simulator ({'QoL' if mode == 'qol' else 'Vanilla'}) …")

    def install(self):
        def progress(p):
            self.root.after(0, lambda: self.toast(f"Downloading UE4SS {core.UE4SS_VERSION} … {int(p * 100)} %", ms=0))

        def done(err):
            if err:
                msg = "No permission – restart the launcher as administrator." if isinstance(err, PermissionError) \
                    else f"Install failed: {err}"
                self.toast(msg, "#e26050", ms=9000)
            else:
                self.settings = self._load_settings()
                self.toast("QoL installed. Have fun!", "#9ad0a8")
            self.show_main()

        self.run_task("Installing …", lambda: core.install(self.game_dir, progress=progress), done)

    def ask_uninstall(self):
        self.dialog("Uninstall QoL?",
                    "This removes the QoL mod and UE4SS from the game folder. "
                    "The game itself stays untouched.",
                    [("Uninstall", "danger", self.uninstall), ("Cancel", "normal", None)], danger=True)

    def uninstall(self):
        def done(err):
            self.toast(f"Uninstall failed: {err}" if err else "QoL removed – the game is vanilla again.",
                       "#e26050" if err else "#9ad0a8")
            self.show_main()

        self.run_task("Removing …", lambda: core.uninstall(self.game_dir), done)

    def browse_game(self):
        p = filedialog.askdirectory(title="Select the 'Pirate Fighting Simulator' folder")
        if not p:
            return
        d = core.normalize_game_dir(Path(p))
        if not d:
            self.toast("That folder does not contain Pirate Fighting Simulator.", "#e26050")
            return
        self.game_dir = d
        self.prefs["game_dir"] = str(d)
        core.save_prefs(self.prefs)
        self.settings = self._load_settings()
        self.toast("Game folder set.", "#9ad0a8")
        self.show_main()
        self._check_permissions()

    # ------------------------------------------------------------------ options
    def show_options(self):
        self.clear("ui")
        s = self.settings
        tw = theme.smallcaps_size("Options", 36)[0]
        from PIL import Image, ImageDraw
        title = Image.new("RGBA", (tw + 10, 50), (0, 0, 0, 0))
        theme.draw_smallcaps(ImageDraw.Draw(title), (0, 0), "Options", 36, theme.GOLD)
        self.image((W - tw) // 2, 52, title)

        pw, ph = 700, 450
        px, py = (W - pw) // 2, 100
        self.image(px, py, theme.panel(pw, ph))

        rows = [
            ("Crosshair", "Shape, colour, outline – or import your VALORANT crosshair.",
             "Edit", self.show_crosshair),
            ("Toggle overlay key", "Shows / hides the QoL overlay in game.",
             core.key_label(s["toggle_key"]), lambda: self.capture_key("toggle_key", "Toggle overlay")),
            ("Debug dump key", "Writes debug info into UE4SS.log.",
             core.key_label(s["dump_key"]), lambda: self.capture_key("dump_key", "Debug dump")),
            ("In-game language", "Language of the overlay texts.",
             "Deutsch" if s["language"] == "de" else "English", self.toggle_language),
            ("Fair-play lock", "QoL only works if every player in the lobby has it.",
             "On" if s["require_all"] else "Off", self.toggle_fairplay),
        ]
        y = py + 32
        for label, hint, value, cmd in rows:
            self.text(px + 40, y, label, font=(self.f_bold[0], 15, "bold"))
            self.text(px + 40, y + 24, hint, font=self.f_small, fill="#c8b496")
            style = "danger" if (label == "Fair-play lock" and not s["require_all"]) else "normal"
            self.button(px + pw - 240, y + 2, value, cmd, w=190, h=42, style=style, size=20)
            y += 58

        game = str(self.game_dir) if self.game_dir else "not found"
        self.text(px + 40, y + 2, "Game folder", font=(self.f_bold[0], 15, "bold"))
        self.text(px + 40, y + 26, game, font=self.f_small, fill="#c8b496", width=pw - 300)
        self.button(px + pw - 240, y + 2, "Browse", self.browse_game, w=190, h=42, size=20)

        editable = bool(self.game_dir and self.status().mod)
        self.button(W // 2 - 170, py + ph - 72, "Back", self.show_main, w=160, h=42)
        self.button(W // 2 + 10, py + ph - 72, "Save", self.save_options, w=160, h=42,
                    style="normal" if editable else "disabled")
        if not editable:
            self.text(W // 2, py + ph - 16, "Install QoL first to change these settings.",
                      font=self.f_small, fill="#e26050", anchor="center")

    def toggle_language(self):
        self.settings["language"] = "en" if self.settings["language"] == "de" else "de"
        self.show_options()

    def toggle_fairplay(self):
        if not self.settings["require_all"]:
            self.settings["require_all"] = True
            self.show_options()
            return

        def disable():
            self.settings["require_all"] = False
            self.show_options()
            self.toast("Fair-play lock is OFF – remember to save.", "#e26050")

        self.dialog(
            "Warning: unfair advantage",
            "With the fair-play lock turned off, QoL also works in lobbies where other players "
            "do NOT have it. Crosshair, exact HP and kill info would then give you an unfair "
            "advantage over them – especially in competitive matches.\n\n"
            "Only turn this off for testing or if everybody agrees.",
            [("Turn off anyway", "danger", disable), ("Keep it on", "normal", None)],
            danger=True,
        )

    def capture_key(self, setting: str, label: str):
        g = "dialog"
        self.clear(g)
        self.image(0, 0, theme.dim(W, H), g)
        pw, ph = 520, 200
        px, py = (W - pw) // 2, (H - ph) // 2
        self.image(px, py, theme.panel(pw, ph), g)
        self.text(W // 2, py + 50, f"Press a key for “{label}”", group=g, anchor="center",
                  font=(self.f_bold[0], 17, "bold"), fill="#e2aa54")
        self.text(W // 2, py + 92, "F1–F12, letters, numbers, numpad, Insert, Delete, Home, End, Page Up/Down",
                  group=g, anchor="center", font=self.f_small, fill="#c8b496")
        self.text(W // 2, py + 140, "Esc = cancel", group=g, anchor="center", font=self.f_small)
        self.key_capture = setting

    def _on_key(self, event):
        if not self.key_capture:
            return
        setting = self.key_capture
        if event.keysym == "Escape":
            self.key_capture = None
            self.clear("dialog")
            return
        name = core.key_from_tk(event.keysym)
        if not name:
            self.toast(f"“{event.keysym}” can't be used – try another key.", "#e26050")
            return
        other = "dump_key" if setting == "toggle_key" else "toggle_key"
        if name == self.settings[other]:
            self.toast("That key is already used for the other hotkey.", "#e26050")
            return
        self.key_capture = None
        self.clear("dialog")
        self.settings[setting] = name
        self.show_options()
        if name in core.GAME_KEYS:
            self.toast(f"Careful: the game itself uses {core.key_label(name)}.", "#e2aa54", ms=7000)


    # ------------------------------------------------------------------ crosshair editor
    def show_crosshair(self, keep_backup: bool = False):
        if not keep_backup:
            self._xh_backup = X.copy.deepcopy(self.settings["crosshair"])
        self.clear("ui")
        xh = self.settings["crosshair"]
        from PIL import Image, ImageDraw
        tw = theme.smallcaps_size("Crosshair", 34)[0]
        title = Image.new("RGBA", (tw + 10, 48), (0, 0, 0, 0))
        theme.draw_smallcaps(ImageDraw.Draw(title), (0, 0), "Crosshair", 34, theme.GOLD)
        self.image((W - tw) // 2, 14, title)

        # ---- left: previews
        lx, ly = 20, 64
        self.image(lx, ly, theme.panel(364, 404))
        self.image(lx + 20, ly + 20, theme.crosshair_preview(xh, 320, 236, 4))
        self.text(lx + 26, ly + 24, "Zoom ×4", font=self.f_small, fill="#2a1a0c")
        self.image(lx + 20, ly + 264, theme.crosshair_preview(xh, 320, 96, 1))
        self.text(lx + 26, ly + 268, "Actual size (1080p)", font=self.f_small, fill="#2a1a0c")
        self.button(lx, 478, "Import Valorant", self.import_valorant, w=178, h=38, size=16)
        self.button(lx + 182, 478, "Copy as Code", self.copy_valorant, w=178, h=38, size=16)
        self.button(lx, 524, "Reset", self.reset_crosshair, w=178, h=38, size=16)

        # ---- right: settings
        rx, ry = 396, 64
        self.image(rx, ry, theme.panel(548, 452))
        hx, tx, ax, bx = rx + 20, rx + 112, rx + 184, rx + 354
        y = ry + 22
        bold = (self.f_bold[0], 13, "bold")

        # colour swatches
        self.text(hx, y + 4, "Colour", font=bold)
        cur = xh["COLOR"].upper()[:6]
        for i, col in enumerate(X.PRESET_COLORS):
            sx = tx + i * 30
            item = self.canvas.create_rectangle(sx, y + 2, sx + 22, y + 24, fill="#" + col,
                                                outline="#e2aa54" if col == cur else "#1c0f07",
                                                width=3 if col == cur else 1, tags=("ui",))
            self.canvas.tag_bind(item, "<Button-1>", lambda e, c=col: self._xh_set("COLOR", c + "FF"))
        custom = cur not in X.PRESET_COLORS
        self.canvas.create_rectangle(tx + 244, y + 2, tx + 266, y + 24, fill="#" + cur,
                                     outline="#e2aa54" if custom else "#1c0f07", width=3 if custom else 1, tags=("ui",))
        self.button(tx + 274, y, "Custom", self.custom_color, w=84, h=28, size=14)
        y += 40

        self.text(hx, y + 4, "Size", font=bold)
        self._stepper(ax, y, "Scale", xh, "SCALE")
        y += 40

        def group(title, on_key, a, b, sub=None):
            nonlocal y
            self.text(hx, y + 4, title, font=bold)
            target = xh[sub] if sub else xh
            on = target[on_key]
            self.button(tx, y, "On" if on else "Off",
                        lambda: self._xh_toggle(sub, on_key), w=64, h=28,
                        style="normal" if on else "danger", size=14)
            if a: self._stepper(ax, y, a[0], target, a[1], sub)
            if b: self._stepper(bx, y, b[0], target, b[1], sub)
            y += 40

        group("Outline", "OUTLINE", ("Thick", "OUTLINE_THICKNESS"), ("Opacity", "OUTLINE_OPACITY"))
        group("Center dot", "DOT", ("Thick", "DOT_THICKNESS"), ("Opacity", "DOT_OPACITY"))
        for title, sub in (("Inner lines", "INNER"), ("Outer lines", "OUTER")):
            group(title, "SHOW", ("Opacity", "OPACITY"), None, sub)
            self._stepper(ax, y, "Length", xh[sub], "LENGTH", sub)
            self._stepper(bx, y, "V-Length", xh[sub], "VLENGTH", sub)
            y += 36
            self._stepper(ax, y, "Thick", xh[sub], "THICKNESS", sub)
            self._stepper(bx, y, "Offset", xh[sub], "OFFSET", sub)
            y += 42

        self.button(rx + 110, 528, "Cancel", self.cancel_crosshair, w=150, h=40)
        self.button(rx + 280, 528, "Save", self.save_crosshair, w=150, h=40)

    def _fmt_val(self, key, v):
        if key == "SCALE":
            return f"{v:g}×"
        if "OPACITY" in key:
            return f"{v:.2f}"
        return str(int(v))

    def _stepper(self, x, y, label, target, key, sub=None):
        lo, hi, step = X.RANGES[key]
        self.text(x, y + 6, label, font=self.f_small, fill="#c8b496")

        def change(d):
            v = round(min(hi, max(lo, target[key] + d * step)), 3)
            if isinstance(lo, int) and isinstance(step, int):
                v = int(v)
            if key == "LENGTH" and sub and target["VLENGTH"] == target["LENGTH"]:
                target["VLENGTH"] = v          # keep vertical length linked
            target[key] = v
            self.show_crosshair(keep_backup=True)

        lw = 66   # label column
        self.button(x + lw, y + 2, "-", lambda: change(-1), w=26, h=26, size=16)
        self.text(x + lw + 26 + 22, y + 15, self._fmt_val(key, target[key]), anchor="center", font=self.f_text)
        self.button(x + lw + 26 + 44, y + 2, "+", lambda: change(1), w=26, h=26, size=16)

    def _xh_set(self, key, value):
        self.settings["crosshair"][key] = value
        self.show_crosshair(keep_backup=True)

    def _xh_toggle(self, sub, key):
        t = self.settings["crosshair"][sub] if sub else self.settings["crosshair"]
        t[key] = not t[key]
        self.show_crosshair(keep_backup=True)

    def reset_crosshair(self):
        self.settings["crosshair"] = X.default()
        self.show_crosshair(keep_backup=True)

    def cancel_crosshair(self):
        self.settings["crosshair"] = getattr(self, "_xh_backup", None) or X.default()
        self.show_options()

    def save_crosshair(self):
        if self.game_dir and self.status().mod:
            try:
                core.write_settings(core.win64_dir(self.game_dir), {"crosshair": self.settings["crosshair"]})
            except OSError as e:
                self.toast(f"Could not save: {e}", "#e26050")
                return
            self.toast("Crosshair saved. Restart the game if it is running.", "#9ad0a8")
        else:
            self.toast("Install QoL first – the crosshair will be used after installing.", "#e2aa54")
        self.show_options()

    def input_dialog(self, title: str, hint: str, initial: str, on_ok, ok_label: str = "OK"):
        g = "dialog"
        self.clear(g)
        self.image(0, 0, theme.dim(W, H), g)
        pw, ph = 640, 230
        px, py = (W - pw) // 2, (H - ph) // 2
        self.image(px, py, theme.panel(pw, ph), g)
        self.text(W // 2, py + 34, title, group=g, anchor="center", font=(self.f_bold[0], 17, "bold"), fill="#e2aa54")
        self.text(W // 2, py + 64, hint, group=g, anchor="center", font=self.f_small, fill="#c8b496", width=pw - 60)
        self.entry = tk.Entry(self.root, font=self.f_text, bg="#1c0f07", fg="#f4ecd6", insertbackground="#f4ecd6",
                              relief="flat", highlightthickness=2, highlightbackground="#966834",
                              highlightcolor="#e2aa54")
        self.entry.insert(0, initial)
        self.canvas.create_window(W // 2, py + 108, window=self.entry, width=pw - 80, height=34, tags=(g,))
        self.entry.focus_set()
        self.entry.select_range(0, "end")

        def ok(_e=None):
            value = self.entry.get().strip() if self.entry else ""
            self.clear(g)
            on_ok(value)

        self.entry.bind("<Return>", ok)
        self.entry.bind("<Escape>", lambda e: self.clear(g))
        self.button(W // 2 - 190, py + ph - 66, ok_label, ok, w=180, h=40, group=g, size=19)
        self.button(W // 2 + 10, py + ph - 66, "Cancel", lambda: self.clear(g), w=180, h=40, group=g, size=19)

    def import_valorant(self):
        try:
            clip = self.root.clipboard_get().strip()
        except Exception:
            clip = ""
        initial = clip if clip.startswith("0;") else ""

        def apply(code):
            if not code:
                return
            try:
                self.settings["crosshair"] = X.from_valorant(code)
            except X.CrosshairCodeError as e:
                self.toast(str(e), "#e26050", ms=8000)
                return
            self.show_crosshair(keep_backup=True)
            self.toast("VALORANT crosshair imported – press Save to use it.", "#9ad0a8")

        self.input_dialog("Import VALORANT crosshair",
                          "In VALORANT: Settings › Crosshair › Primary › Export Profile Code, then paste it here.",
                          initial, apply, ok_label="Import")

    def copy_valorant(self):
        code = X.to_valorant(self.settings["crosshair"])
        self.root.clipboard_clear()
        self.root.clipboard_append(code)
        self.toast("Copied – paste it in VALORANT via “Import Profile Code”.", "#9ad0a8")

    def custom_color(self):
        def apply(value):
            if not value:
                return
            try:
                self.settings["crosshair"]["COLOR"] = X._hex(value)
            except X.CrosshairCodeError as e:
                self.toast(str(e), "#e26050")
                return
            self.show_crosshair(keep_backup=True)

        self.input_dialog("Custom colour", "Hex colour like FF8800 (or FF8800CC with transparency).",
                          self.settings["crosshair"]["COLOR"][:6], apply)

    def save_options(self):
        try:
            core.write_settings(core.win64_dir(self.game_dir), self.settings)
        except PermissionError:
            self.toast("No permission – restart the launcher as administrator.", "#e26050")
            return
        except OSError as e:
            self.toast(f"Could not save: {e}", "#e26050")
            return
        self.toast("Saved. Restart the game if it is running.", "#9ad0a8")
        self.show_main()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screenshot", help="render a screen, save it as PNG and exit (for CI)")
    ap.add_argument("--screen", default="main", choices=["main", "options", "crosshair"])
    ap.add_argument("--xh-code", help="VALORANT code to show in the crosshair editor (for CI screenshots)")
    args = ap.parse_args()

    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
        except Exception:
            pass

    root = tk.Tk()
    app = Launcher(root, "main" if args.xh_code else args.screen)
    if args.xh_code:
        app.settings["crosshair"] = X.from_valorant(args.xh_code)
        app.show_crosshair()

    if args.screenshot:
        def shot():
            from PIL import ImageGrab
            root.update()
            x, y = root.winfo_rootx(), root.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + W, y + H)).save(args.screenshot)
            root.destroy()
        root.after(2500, shot)

    root.mainloop()


if __name__ == "__main__":
    main()
