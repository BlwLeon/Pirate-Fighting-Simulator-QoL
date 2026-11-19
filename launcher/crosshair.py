"""
Crosshair model shared by the launcher's editor and the mod.

- default crosshair + value ranges
- import / export of VALORANT crosshair profile codes
- reading / writing the CROSSHAIR block in the mod's config.lua
- geometry (list of rectangles) – the mod's main.lua uses the same maths

VALORANT code format (not officially documented, reverse-engineered by the
community): "0;P;c;5;h;0;0l;4;0o;2;0a;1;0f;0;1b;0"
  - "0" version, then optional general keys, then section "P" (primary).
  - After "P": key;value pairs until the next section marker ("A" = ADS,
    "S" = sniper). Keys that are not in the code keep VALORANT's defaults.
  - c  colour preset (0 white, 1 green, 2 yellow-green, 3 green-yellow,
       4 yellow, 5 cyan, 6 pink, 7 red, 8 custom -> u = RRGGBBAA)
  - h  outlines on/off,  t outline thickness,  o outline opacity
  - d  centre dot on/off, z dot thickness,     a dot opacity
  - 0x / 1x  inner / outer lines:
       b show, t thickness, l length, v vertical length, g "vertical length
       not linked", o offset, a opacity, m/f/s/e movement & firing error
       (dynamic – not used here)
"""
from __future__ import annotations

import copy
import re

PRESET_COLORS = ["FFFFFF", "00FF00", "7FFF00", "DFFF00", "FFFF00", "00FFFF", "FF00FF", "FF0000"]
PRESET_NAMES = ["White", "Green", "Yellow Green", "Green Yellow", "Yellow", "Cyan", "Pink", "Red"]

DEFAULT = {
    "COLOR": "FFFFFFFF",
    "OUTLINE": True, "OUTLINE_THICKNESS": 1, "OUTLINE_OPACITY": 0.5,
    "DOT": False, "DOT_THICKNESS": 2, "DOT_OPACITY": 1.0,
    "INNER": {"SHOW": True, "LENGTH": 4, "VLENGTH": 4, "THICKNESS": 2, "OFFSET": 2, "OPACITY": 1.0},
    "OUTER": {"SHOW": False, "LENGTH": 2, "VLENGTH": 2, "THICKNESS": 2, "OFFSET": 10, "OPACITY": 0.35},
    "SCALE": 1.0,
}

# VALORANT's own defaults (used for keys that a code leaves out)
VALORANT_DEFAULT = {
    "COLOR": "FFFFFFFF",
    "OUTLINE": True, "OUTLINE_THICKNESS": 1, "OUTLINE_OPACITY": 0.5,
    "DOT": False, "DOT_THICKNESS": 2, "DOT_OPACITY": 1.0,
    "INNER": {"SHOW": True, "LENGTH": 6, "VLENGTH": 6, "THICKNESS": 2, "OFFSET": 3, "OPACITY": 0.8},
    "OUTER": {"SHOW": True, "LENGTH": 2, "VLENGTH": 2, "THICKNESS": 2, "OFFSET": 10, "OPACITY": 0.35},
    "SCALE": 1.0,
}

# (min, max, step) for the editor
RANGES = {
    "OUTLINE_THICKNESS": (1, 6, 1), "OUTLINE_OPACITY": (0.0, 1.0, 0.05),
    "DOT_THICKNESS": (1, 6, 1), "DOT_OPACITY": (0.0, 1.0, 0.05),
    "LENGTH": (0, 20, 1), "VLENGTH": (0, 20, 1), "THICKNESS": (0, 10, 1),
    "OFFSET": (0, 40, 1), "OPACITY": (0.0, 1.0, 0.05),
    "SCALE": (0.5, 3.0, 0.25),
}


class CrosshairCodeError(ValueError):
    pass


def default() -> dict:
    return copy.deepcopy(DEFAULT)


def _num(v: str) -> float:
    try:
        return float(v)
    except ValueError:
        raise CrosshairCodeError(f"'{v}' is not a number") from None


def _int(v: str) -> int:
    return int(round(_num(v)))


def _clamp(key: str, v):
    lo, hi, _ = RANGES[key]
    v = max(lo, min(hi, v))
    return v


def _hex(s: str) -> str:
    s = s.strip().lstrip("#").upper()
    if not re.fullmatch(r"[0-9A-F]{6}([0-9A-F]{2})?", s):
        raise CrosshairCodeError(f"'{s}' is not a colour")
    return s if len(s) == 8 else s + "FF"


# ---------------------------------------------------------------------------
#  VALORANT import / export
# ---------------------------------------------------------------------------
def from_valorant(code: str) -> dict:
    code = code.strip().strip('"').strip()
    tokens = code.split(";")
    if not tokens or tokens[0] != "0" or "P" not in tokens:
        raise CrosshairCodeError("This doesn't look like a VALORANT crosshair code (it should start with 0;P;…)")
    i = tokens.index("P") + 1
    kv: dict[str, str] = {}
    while i < len(tokens):
        key = tokens[i]
        if key in ("A", "S") or key == "":
            break
        if i + 1 >= len(tokens):
            break
        kv[key] = tokens[i + 1]
        i += 2

    xh = copy.deepcopy(VALORANT_DEFAULT)
    color_idx = _int(kv["c"]) if "c" in kv else 0
    if color_idx == 8 and "u" in kv:
        xh["COLOR"] = _hex(kv["u"])
    elif 0 <= color_idx < len(PRESET_COLORS):
        xh["COLOR"] = PRESET_COLORS[color_idx] + "FF"
    if "h" in kv: xh["OUTLINE"] = kv["h"] != "0"
    if "t" in kv: xh["OUTLINE_THICKNESS"] = _clamp("OUTLINE_THICKNESS", _int(kv["t"]))
    if "o" in kv: xh["OUTLINE_OPACITY"] = _clamp("OUTLINE_OPACITY", _num(kv["o"]))
    if "d" in kv: xh["DOT"] = kv["d"] != "0"
    if "z" in kv: xh["DOT_THICKNESS"] = _clamp("DOT_THICKNESS", _int(kv["z"]))
    if "a" in kv: xh["DOT_OPACITY"] = _clamp("DOT_OPACITY", _num(kv["a"]))

    for prefix, name in (("0", "INNER"), ("1", "OUTER")):
        line = xh[name]
        g = lambda k: kv.get(prefix + k)  # noqa: E731
        if g("b") is not None: line["SHOW"] = g("b") != "0"
        if g("t") is not None: line["THICKNESS"] = _clamp("THICKNESS", _int(g("t")))
        if g("l") is not None: line["LENGTH"] = _clamp("LENGTH", _int(g("l")))
        if g("o") is not None: line["OFFSET"] = _clamp("OFFSET", _int(g("o")))
        if g("a") is not None: line["OPACITY"] = _clamp("OPACITY", _num(g("a")))
        separate = g("g") is not None and g("g") != "0"
        if separate and g("v") is not None:
            line["VLENGTH"] = _clamp("VLENGTH", _int(g("v")))
        elif not separate:
            line["VLENGTH"] = line["LENGTH"]
    return xh


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.3f}".rstrip("0").rstrip(".")


def to_valorant(xh: dict) -> str:
    """Full VALORANT code for the crosshair (firing/movement error off)."""
    col = xh["COLOR"].upper()
    parts = ["0", "P"]
    if col[:6] in PRESET_COLORS and col[6:] in ("", "FF"):
        parts += ["c", str(PRESET_COLORS.index(col[:6]))]
    else:
        parts += ["c", "8", "u", col if len(col) == 8 else col + "FF"]
    parts += ["h", "1" if xh["OUTLINE"] else "0", "t", _fmt(xh["OUTLINE_THICKNESS"]),
              "o", _fmt(xh["OUTLINE_OPACITY"]),
              "d", "1" if xh["DOT"] else "0", "z", _fmt(xh["DOT_THICKNESS"]), "a", _fmt(xh["DOT_OPACITY"]),
              "f", "0", "m", "0"]
    for prefix, name in (("0", "INNER"), ("1", "OUTER")):
        L = xh[name]
        linked = L["VLENGTH"] == L["LENGTH"]
        parts += [prefix + "b", "1" if L["SHOW"] else "0", prefix + "t", _fmt(L["THICKNESS"]),
                  prefix + "l", _fmt(L["LENGTH"])]
        if not linked:
            parts += [prefix + "v", _fmt(L["VLENGTH"]), prefix + "g", "1"]
        parts += [prefix + "o", _fmt(L["OFFSET"]), prefix + "a", _fmt(L["OPACITY"]),
                  prefix + "m", "0", prefix + "f", "0"]
    return ";".join(parts)


# ---------------------------------------------------------------------------
#  config.lua block
# ---------------------------------------------------------------------------
BEGIN = "-- [crosshair-begin]"
END = "-- [crosshair-end]"


def _lua(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f'"{v}"'
    return _fmt(v)


def to_lua_block(xh: dict) -> str:
    def line_tbl(L):
        return "{ " + ", ".join(f"{k} = {_lua(L[k])}" for k in
                                ("SHOW", "LENGTH", "VLENGTH", "THICKNESS", "OFFSET", "OPACITY")) + " }"
    return (
        f"    {BEGIN} (written by the launcher's crosshair editor)\n"
        "    CROSSHAIR = {\n"
        f"        COLOR = {_lua(xh['COLOR'])},\n"
        f"        OUTLINE = {_lua(xh['OUTLINE'])}, OUTLINE_THICKNESS = {_lua(xh['OUTLINE_THICKNESS'])}, "
        f"OUTLINE_OPACITY = {_lua(xh['OUTLINE_OPACITY'])},\n"
        f"        DOT = {_lua(xh['DOT'])}, DOT_THICKNESS = {_lua(xh['DOT_THICKNESS'])}, "
        f"DOT_OPACITY = {_lua(xh['DOT_OPACITY'])},\n"
        f"        INNER = {line_tbl(xh['INNER'])},\n"
        f"        OUTER = {line_tbl(xh['OUTER'])},\n"
        f"        SCALE = {_lua(xh['SCALE'])},\n"
        "    },\n"
        f"    {END}\n"
    )


_VAL = r'("[^"]*"|true|false|-?[\d.]+)'


def _parse_pairs(text: str) -> dict:
    out = {}
    for k, v in re.findall(r"(\w+)\s*=\s*" + _VAL, text):
        if v.startswith('"'):
            out[k] = v.strip('"')
        elif v in ("true", "false"):
            out[k] = v == "true"
        else:
            out[k] = float(v) if "." in v else int(v)
    return out


def from_lua_block(config_text: str) -> dict | None:
    m = re.search(re.escape(BEGIN) + r"(.*?)" + re.escape(END), config_text, re.S)
    if not m:
        return None
    body = m.group(1)
    xh = default()
    for name in ("INNER", "OUTER"):
        sm = re.search(name + r"\s*=\s*\{([^}]*)\}", body)
        if sm:
            xh[name].update({k: v for k, v in _parse_pairs(sm.group(1)).items() if k in xh[name]})
            body = body.replace(sm.group(0), "")
    top = _parse_pairs(body)
    for k in xh:
        if k in top and not isinstance(xh[k], dict):
            xh[k] = top[k]
    return xh


def replace_block(config_text: str, xh: dict) -> str:
    block = to_lua_block(xh)
    pat = re.compile(r"[ \t]*" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"[^\n]*\n", re.S)
    if pat.search(config_text):
        return pat.sub(lambda m: block, config_text, count=1)
    # older config without block -> insert right after "return {"
    return config_text.replace("return {\n", "return {\n" + block, 1)


# ---------------------------------------------------------------------------
#  Geometry (keep in sync with crosshairRects() in mod/PFS_QoL/Scripts/main.lua)
# ---------------------------------------------------------------------------
def color_rgba(xh: dict) -> tuple[int, int, int, int]:
    h = _hex(xh["COLOR"])
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6))  # type: ignore[return-value]


def rects(xh: dict) -> list[tuple[float, float, float, float, tuple[int, int, int], float]]:
    """Rectangles relative to the screen centre:
    (left, top, width, height, rgb, alpha). Outlines first, then fills."""
    r, g, b, a = color_rgba(xh)
    base_a = a / 255
    s = float(xh.get("SCALE", 1))
    ot = xh["OUTLINE_THICKNESS"] if xh["OUTLINE"] else 0
    outlines, fills = [], []

    def add(cx, cy, w, h, alpha):
        if w <= 0 or h <= 0 or alpha <= 0:
            return
        fills.append(((cx - w / 2) * s, (cy - h / 2) * s, w * s, h * s, (r, g, b), alpha * base_a))
        if ot > 0 and xh["OUTLINE_OPACITY"] > 0:
            ow, oh = w + 2 * ot, h + 2 * ot
            outlines.append(((cx - ow / 2) * s, (cy - oh / 2) * s, ow * s, oh * s, (0, 0, 0),
                             xh["OUTLINE_OPACITY"]))

    if xh["DOT"]:
        add(0, 0, xh["DOT_THICKNESS"], xh["DOT_THICKNESS"], xh["DOT_OPACITY"])
    for name in ("INNER", "OUTER"):
        L = xh[name]
        if not L["SHOW"]:
            continue
        t, l, v, o, op = L["THICKNESS"], L["LENGTH"], L["VLENGTH"], L["OFFSET"], L["OPACITY"]
        add(o + l / 2, 0, l, t, op)
        add(-(o + l / 2), 0, l, t, op)
        add(0, o + v / 2, t, v, op)
        add(0, -(o + v / 2), t, v, op)
    return outlines + fills
