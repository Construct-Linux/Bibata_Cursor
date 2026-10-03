# Bibata-Modern-Construct

The cursor theme of CONSTRUCT, a GNOME desktop built from Wolfi packages: the
Bibata Modern cursors (right-handed) in CONSTRUCT's colours, with the
`cursors_scalable/` SVGs GNOME Shell 51 draws its own cursor from.

This is a fork of [Bibata Cursor](https://github.com/ful1e5/Bibata_Cursor) by
Abdulkaiz Khatri ([ful1e5](https://github.com/ful1e5)), who designed the
cursors. It keeps upstream's modern SVGs and cursor table and replaces the
Node and clickgen build with one Python program.

## Build

Needs Python 3.11 or newer and `rsvg-convert` (librsvg).

```sh
python3 build.py -o ~/.local/share/icons
```

writes `Bibata-Modern-Construct/` there:

- `index.theme`
- `cursors/`: X cursors in the sizes GNOME uses (24 to 96) with every alias
  name Bibata ships, for X11, XWayland and GTK/Qt clients
- `cursors_scalable/`: one SVG directory with `metadata.json` per CSS cursor
  name, for GNOME Shell 51

`svg/` holds the sources, drawn in placeholder colours (`#00FF00` fill,
`#0000FF` outline, `#FF0000` watch) that `COLORS` in `build.py` replaces.
`cursors.toml` says which SVG serves which X11 names, with hotspots, sizes and
frame delay.

## License

GPL-3.0, as upstream Bibata. See [LICENSE](LICENSE).
