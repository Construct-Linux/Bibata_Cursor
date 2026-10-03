#!/usr/bin/env python3
"""Build the Bibata-Modern-Construct cursor theme from Bibata's SVGs.

    python3 build.py -o <icons_dir>

writes <icons_dir>/Bibata-Modern-Construct/ with:

  index.theme
  cursors/           X cursors (Xcursor files and their alias symlinks), what
                     X11, XWayland and GTK/Qt clients load
  cursors_scalable/  SVGs and metadata.json per CSS cursor name, what GNOME
                     Shell 51 draws its own cursor from; a theme without them
                     falls back to the shell's built-in Adwaita

Both come from the same SVGs, colours and cursors.toml (hotspots,
frame delay, sizes, the X11 names each SVG serves), so they cannot drift.

Needs Python 3.11+ and rsvg-convert (librsvg), nothing else: the Xcursor files
are written here directly (format in Xcursor(3)), replacing upstream's
cbmp (Node) and clickgen (Python) pipeline.
"""

import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
import tomllib
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SVG_DIR = ROOT / "svg"
CONFIG = ROOT / "cursors.toml"

THEME = "Bibata-Modern-Construct"
COMMENT = "Bibata Modern in Construct's colours"

# Bibata's SVGs are drawn in placeholder colours that each theme replaces.
# The values are the brand's palette.toml [cursor] (fill, outline, watch).
COLORS = {
    "#00FF00": "#0B1116",  # fill
    "#0000FF": "#FFFFFF",  # outline
    "#FF0000": "#00E5FF",  # watch, the accent of the busy cursors
}

# The SVGs are drawn on a 256px canvas, which is scaled whole to each cursor
# size: hotspots in the config are in canvas pixels.
CANVAS = 256

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
CSS_FALLBACKS = {"all-resize": "move"}

# GNOME Shell scales an SVG's intrinsic size by cursor-size / nominal_size;
# drawing the canvas at 24px keeps a cursor the size it has under X11.
NOMINAL_SIZE = 24

XCURSOR_IMAGE = 0xFFFD0002
SVG_SIZE = re.compile(r'(<svg\b[^>]*?)\swidth="256"\sheight="256"')


def load_cursors():
    """The config's cursors, each with its defaults filled in."""
    with open(CONFIG, "rb") as f:
        table = tomllib.load(f)["cursors"]
    defaults = table.pop("fallback_settings")
    cursors = []
    for cur in table.values():
        stem = cur["png"].removesuffix(".png")
        if "*" in stem:
            # Animated: <name>/<name>-NN.svg, one SVG per frame.
            frames = sorted((SVG_DIR / stem.split("-*")[0]).glob(stem + ".svg"))
        else:
            frames = [SVG_DIR / (stem + ".svg")]
        if not frames or not all(f.is_file() for f in frames):
            sys.exit(f"{cur['x11_name']}: no SVG for {cur['png']}")
        cursors.append({
            "name": cur["x11_name"],
            "links": cur.get("x11_symlinks", []),
            "frames": frames,
            "hotspot": (cur.get("x_hotspot", defaults["x_hotspot"]),
                        cur.get("y_hotspot", defaults["y_hotspot"])),
            "delay": cur.get("x11_delay", defaults["x11_delay"]),
            "sizes": cur.get("x11_sizes", defaults["x11_sizes"]),
        })
    return cursors


def colorize(svg):
    # As upstream's cbmp: every occurrence, case-insensitive, in order.
    for match, replace in COLORS.items():
        svg = re.sub(re.escape(match), replace, svg, flags=re.I)
    return svg


# --- X cursors -------------------------------------------------------------

def rasterize(svg, size):
    """Render SVG text to size x size straight-alpha RGBA bytes."""
    png = subprocess.run(
        ["rsvg-convert", "--width", str(size), "--height", str(size)],
        input=svg.encode(), capture_output=True, check=True,
    ).stdout
    return decode_png(png)


def decode_png(data):
    """Decode the 8-bit RGBA, non-interlaced PNG rsvg-convert writes."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat = 8, []
    while pos < len(data):
        length, kind = struct.unpack_from(">I4s", data, pos)
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(
                ">IIBBBBB", body)
            if (depth, ctype, interlace) != (8, 6, 0):
                raise ValueError(f"unsupported PNG {depth=} {ctype=}")
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
        pos += 12 + length

    raw = zlib.decompress(b"".join(idat))
    stride = width * 4
    out = bytearray(stride * height)
    prev = bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        ftype = raw[start]
        row = bytearray(raw[start + 1:start + 1 + stride])
        if ftype == 1:  # Sub
            for i in range(4, stride):
                row[i] = (row[i] + row[i - 4]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                left = row[i - 4] if i >= 4 else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                a = row[i - 4] if i >= 4 else 0
                b = prev[i]
                c = prev[i - 4] if i >= 4 else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                if pa <= pb and pa <= pc:
                    pred = a
                elif pb <= pc:
                    pred = b
                else:
                    pred = c
                row[i] = (row[i] + pred) & 0xFF
        elif ftype != 0:
            raise ValueError(f"bad PNG filter {ftype}")
        out[y * stride:(y + 1) * stride] = row
        prev = row
    return bytes(out)


def to_xcursor_pixels(rgba):
    """Straight RGBA bytes to Xcursor's premultiplied ARGB, little-endian."""
    out = bytearray(len(rgba))
    for i in range(0, len(rgba), 4):
        a = rgba[i + 3]
        if a == 0:
            continue
        r, g, b = rgba[i], rgba[i + 1], rgba[i + 2]
        if a != 255:
            r, g, b = ((r * a + 127) // 255, (g * a + 127) // 255,
                       (b * a + 127) // 255)
        out[i], out[i + 1], out[i + 2], out[i + 3] = b, g, r, a
    return bytes(out)


def xcursor_images(cur):
    """[(size, xhot, yhot, delay, pixels)], frame by frame, size by size."""
    hx, hy = cur["hotspot"]
    images = []
    for frame in cur["frames"]:
        svg = colorize(frame.read_text())
        for size in cur["sizes"]:
            # Truncated, as clickgen scales them, so hotspots match upstream.
            xhot = min(hx * size // CANVAS, size - 1)
            yhot = min(hy * size // CANVAS, size - 1)
            pixels = to_xcursor_pixels(rasterize(svg, size))
            images.append((size, xhot, yhot, cur["delay"], pixels))
    return images


def write_xcursor(path, images):
    header = 16
    toc = 12 * len(images)
    chunks, entries = [], []
    pos = header + toc
    for size, xhot, yhot, delay, pixels in images:
        chunk = struct.pack("<9I", 36, XCURSOR_IMAGE, size, 1, size, size,
                            xhot, yhot, delay) + pixels
        entries.append(struct.pack("<3I", XCURSOR_IMAGE, size, pos))
        chunks.append(chunk)
        pos += len(chunk)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sIII", b"Xcur", header, 0x10000, len(images)))
        f.writelines(entries)
        f.writelines(chunks)


def build_cursors(cursors, out, jobs):
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    def one(cur):
        write_xcursor(out / cur["name"], xcursor_images(cur))

    # rsvg-convert runs outside the GIL, so threads keep the CPUs busy.
    with ThreadPoolExecutor(jobs) as pool:
        list(pool.map(one, cursors))

    links = 0
    for cur in cursors:
        for link in cur["links"]:
            (out / link).symlink_to(cur["name"])
            links += 1
    print(f"{out}: {len(cursors)} cursors, {links} links")


# --- GNOME Shell scalable cursors -----------------------------------------

def build_scalable(cursors, out):
    by_name = {}
    for cur in cursors:
        for name in [cur["name"], *cur["links"]]:
            by_name[name] = cur

    if out.exists():
        shutil.rmtree(out)
    for css in CSS_NAMES:
        cur = by_name.get(css) or by_name.get(CSS_FALLBACKS.get(css, ""))
        if cur is None:
            sys.exit(f"no cursor serves '{css}'")
        dst = out / css
        dst.mkdir(parents=True)

        scale = NOMINAL_SIZE / CANVAS
        hx = round(cur["hotspot"][0] * scale, 2)
        hy = round(cur["hotspot"][1] * scale, 2)
        animated = len(cur["frames"]) > 1
        meta = []
        for f in cur["frames"]:
            svg, n = SVG_SIZE.subn(
                rf'\1 width="{NOMINAL_SIZE}" height="{NOMINAL_SIZE}"',
                colorize(f.read_text()), count=1)
            if n != 1:
                sys.exit(f"{f}: SVG root is not 256x256")
            (dst / f.name).write_text(svg)
            frame = {"filename": f.name}
            if animated:
                frame["delay"] = cur["delay"]
            frame.update(hotspot_x=hx, hotspot_y=hy, nominal_size=NOMINAL_SIZE)
            meta.append(frame)
        with open(dst / "metadata.json", "w") as f:
            json.dump(meta, f, indent=4)
            f.write("\n")
    print(f"{out}: {len(CSS_NAMES)} cursors")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-o", "--out", type=Path, required=True,
                   help=f"icons directory to write {THEME}/ into")
    p.add_argument("-j", "--jobs", type=int, default=None,
                   help="rsvg-convert processes at once (default: CPUs)")
    args = p.parse_args()

    if shutil.which("rsvg-convert") is None:
        sys.exit("rsvg-convert not found (librsvg)")

    cursors = load_cursors()
    theme = args.out / THEME
    theme.mkdir(parents=True, exist_ok=True)
    (theme / "index.theme").write_text(
        f"[Icon Theme]\nName={THEME}\nComment={COMMENT}\n")
    build_cursors(cursors, theme / "cursors", args.jobs)
    build_scalable(cursors, theme / "cursors_scalable")


if __name__ == "__main__":
    main()
