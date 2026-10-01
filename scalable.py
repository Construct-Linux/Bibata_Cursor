#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Write GNOME Shell's scalable cursors (cursors_scalable/) for Bibata themes.

GNOME Shell 51 draws the cursor from SVGs and reads only
icons/<theme>/cursors_scalable/<css-name>/metadata.json; a theme without it
falls back to the shell's built-in Adwaita. This script builds that tree from
the same sources the Xcursor themes are built from: render.json (SVG directory
and colours per theme) and configs/*/x.build.toml (hotspots, delays and the
X11 names each SVG serves).

Requires Python 3.11 or newer and nothing else.
"""

import argparse
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# The names mutter 51 asks for (clutter_cursor_type_to_name).
CSS_NAMES = [
    "default", "context-menu", "help", "pointer", "progress", "wait", "cell",
    "crosshair", "text", "vertical-text", "alias", "copy", "move", "no-drop",
    "not-allowed", "grab", "grabbing", "e-resize", "n-resize", "ne-resize",
    "nw-resize", "s-resize", "se-resize", "sw-resize", "w-resize",
    "ew-resize", "ns-resize", "nesw-resize", "nwse-resize", "col-resize",
    "row-resize", "all-scroll", "zoom-in", "zoom-out", "dnd-ask", "all-resize",
]

# CSS names no Bibata cursor serves under X11: the X11 name to use instead.
FALLBACKS = {
    "all-resize": "move",
}

# The Xcursor build scales the whole 256px canvas to the cursor size, so the
# canvas is drawn at the nominal size here too and a Bibata cursor keeps the
# size it has under X11.
CANVAS = 256
NOMINAL_SIZE = 24

SVG_SIZE = re.compile(r'(<svg\b[^>]*?)\swidth="256"\sheight="256"')


def x11_config(theme):
    side = "right" if "Right" in theme else "normal"
    with open(ROOT / "configs" / side / "x.build.toml", "rb") as f:
        return tomllib.load(f)["cursors"]


def by_x11_name(cursors):
    """Map every X11 name and symlink to its cursor entry."""
    names = {}
    for key, cur in cursors.items():
        if key == "fallback_settings":
            continue
        names[cur["x11_name"]] = cur
        for link in cur.get("x11_symlinks", []):
            names[link] = cur
    return names


def colorize(svg, colors):
    # Same as cbmp: each match in order, case-insensitive, every occurrence.
    for c in colors:
        svg = re.sub(re.escape(c["match"]), c["replace"], svg, flags=re.I)
    svg, n = SVG_SIZE.subn(
        rf'\1 width="{NOMINAL_SIZE}" height="{NOMINAL_SIZE}"', svg, count=1
    )
    if n != 1:
        raise ValueError("SVG root is not 256x256")
    return svg


def frames_of(svg_dir, cur):
    png = cur["png"]
    stem = png[: -len(".png")]
    if "*" in stem:
        # Animated: svg/<variant>/<name>/<name>-NN.svg, as cbmp renders them.
        return sorted((svg_dir / stem.split("-*")[0]).glob(stem + ".svg"))
    return [svg_dir / (stem + ".svg")]


def write_cursor(out, css, cur, defaults, svg_dir, colors):
    frames = frames_of(svg_dir, cur)
    if not frames or not all(f.is_file() for f in frames):
        raise FileNotFoundError(f"{css}: no SVG for {cur['png']}")

    scale = NOMINAL_SIZE / CANVAS
    hx = round(cur.get("x_hotspot", defaults["x_hotspot"]) * scale, 2)
    hy = round(cur.get("y_hotspot", defaults["y_hotspot"]) * scale, 2)
    animated = len(frames) > 1
    delay = cur.get("x11_delay", defaults["x11_delay"])

    dst = out / css
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    meta = []
    for f in frames:
        (dst / f.name).write_text(colorize(f.read_text(), colors))
        frame = {"filename": f.name}
        if animated:
            frame["delay"] = delay
        frame.update(hotspot_x=hx, hotspot_y=hy, nominal_size=NOMINAL_SIZE)
        meta.append(frame)

    with open(dst / "metadata.json", "w") as f:
        json.dump(meta, f, indent=4)
        f.write("\n")


def build(theme, render, out_dir):
    cfg = render[theme]
    cursors = x11_config(theme)
    defaults = cursors["fallback_settings"]
    names = by_x11_name(cursors)
    svg_dir = ROOT / cfg["dir"]
    out = out_dir / theme / "cursors_scalable"

    for css in CSS_NAMES:
        cur = names.get(css) or names.get(FALLBACKS.get(css, ""))
        if cur is None:
            raise KeyError(f"{theme}: no cursor serves '{css}'")
        write_cursor(out, css, cur, defaults, svg_dir, cfg["colors"])
    print(f"{out}: {len(CSS_NAMES)} cursors")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "-o", "--out", type=Path, default=ROOT / "themes",
        help="icons directory to write <theme>/cursors_scalable into "
        "(default: themes/)",
    )
    p.add_argument(
        "themes", nargs="*",
        default=["Bibata-Modern-Classic", "Bibata-Modern-Ice"],
        help="theme names from render.json "
        "(default: Bibata-Modern-Classic Bibata-Modern-Ice)",
    )
    args = p.parse_args()

    with open(ROOT / "render.json") as f:
        render = json.load(f)
    for theme in args.themes:
        if theme not in render:
            sys.exit(f"unknown theme '{theme}' (see render.json)")
        build(theme, render, args.out)


if __name__ == "__main__":
    main()
