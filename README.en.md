# Kuixiang Grid Overlay

[简体中文](README.md)

An unofficial, Windows-only translucent grid overlay for Kuixiang engraving software. It detects the magenta paper boundary in the canvas and draws a click-through centimetre grid over the target window without modifying the application, template JSON, preview, or engraving path.

> This is an independent community project. It is not affiliated with, endorsed by, or sponsored by the developers or distributor of Kuixiang.

## Features

- Detects bright, dark, pale, and anti-aliased magenta paper borders.
- Draws a configurable grid; the default is `1 cm × 1 cm` on A4 portrait paper.
- Reconstructs a complete rectangle from four corners or any three compatible corners.
- Uses a one-axis fallback for two adjacent corners and a full rectangle for two diagonal corners.
- Hides the overlay when only one corner is available.
- Commits updates every three frames and applies cross-batch confirmation to page changes and degraded detections.
- Handles DPI virtualization, 125%/150%/175% display scaling, and multi-monitor movement.
- Uses a non-activating, click-through owner window rather than a globally topmost window.
- Includes diagnostics, rotating logs, global hotkeys, regression tests, and Windows scheduled-task launch scripts.

## Requirements

- Windows 10 or Windows 11.
- Python 3.10 or newer. Development and tests currently use Python 3.12.
- By default, the target window title must contain `奎享雕刻`. Change `target_title_keywords` in `config.py` for another title.

## Installation

```powershell
git clone https://github.com/A-m-o-r-F-a-t-i/kuixiang-grid-overlay.git
cd kuixiang-grid-overlay

py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

```powershell
.\run_overlay.bat
```

The launcher registers and starts an on-demand interactive scheduled task named `KuixiangGridOverlay`. It does not enable start-at-login.

Stop the overlay:

```powershell
.\stop_overlay.ps1
```

Remove the scheduled task:

```powershell
Unregister-ScheduledTask -TaskName KuixiangGridOverlay -Confirm:$false
```

## Configuration

The main options are defined in `config.py`:

| Option | Default | Purpose |
| --- | ---: | --- |
| `paper_width_cm` | `21.0` | Paper width in centimetres |
| `paper_height_cm` | `29.7` | Paper height in centimetres |
| `grid_width_cm` | `1.0` | Horizontal grid spacing |
| `grid_height_cm` | `1.0` | Vertical grid spacing |
| `paper_orientation` | `"portrait"` | `portrait`, `landscape`, or `auto` |
| `update_every_frames` | `3` | Frames accumulated per committed update |
| `capture_interval_ms` | `100` | Detection interval |
| `overlay_alpha` | `0.48` | Overlay opacity |
| `major_every_cm` | `5.0` | Major-grid interval |
| `target_title_keywords` | `("奎享雕刻",)` | Target window title keywords |

Temporary command-line overrides are also available:

```powershell
.\.venv\Scripts\python.exe .\overlay.py `
  --paper-width 21 `
  --paper-height 29.7 `
  --grid-width 1 `
  --grid-height 1 `
  --orientation portrait
```

## Detection behaviour

| Valid corners | Behaviour |
| ---: | --- |
| 4 | Full horizontal and vertical grid |
| 3 | Reconstruct the missing corner and draw a full grid |
| 2 diagonal | Recover the full rectangle |
| 2 adjacent | Draw only the reliably determined axis |
| 1 | Hide the grid |
| 0 | Keep the last stable geometry briefly, then hide |

The detector combines HSV hue, RGB channel differences, line merging, and corner geometry. When `PrintWindow` returns DPI-virtualized logical pixels, the detected rectangle, corners, and pixels-per-centimetre values are mapped back to the physical client area.

## Hotkeys

| Hotkey | Action |
| --- | --- |
| `Ctrl + Alt + G` | Toggle the overlay |
| `Ctrl + Alt + D` | Save a diagnostic snapshot |
| `Ctrl + Alt + Q` | Quit |

Diagnostics are written to `debug/` and logs to `logs/`; both are ignored by Git.

## Tests

```powershell
.\.venv\Scripts\python.exe -m compileall -q .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

Run a one-shot diagnostic without creating the overlay:

```powershell
.\.venv\Scripts\python.exe .\overlay.py --diagnose-once
```

## Limitations

- The grid is visual-only and is never added to templates or engraving output.
- Automatic detection expects a magenta-like paper border.
- Windows is the only supported platform.
- Two adjacent corners do not uniquely determine a full rectangle, so the overlay deliberately falls back to one axis.

## License

Released under the [MIT License](LICENSE).

