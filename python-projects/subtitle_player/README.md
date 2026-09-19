# subtitle_player

Plays a subtitle file on its own black screen, so you can start a DVD on a DVD player
and read the subtitles on a computer next to the TV. It decodes nothing — it is a
stopwatch that draws text — so the whole job is dragging its clock into line with the
disc, which is what the sync controls are for.

Subtitles are shown as a rolling context window: every cue within ±N seconds of now is
on screen at once, current line in bright white, neighbours dimmed. The current line is
anchored at a fixed height so it never jumps as context appears around it.

## Setup

The `python3` on `PATH` is PlatformIO's and has no working GUI stack, so use Apple's:

```bash
cd python-projects/subtitle_player && /usr/bin/python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python subtitle_player.py "examples/your-episode.srt" --fullscreen
```

Run it with no path and a file picker opens; you can also drop an `.srt` onto the window
at any time. Useful flags: `--window 6` (context seconds), `--start 1:30`, `--font-size`.

## Aligning with the disc

Start the disc, start the player, then when you hear a line begin, hit **S** — the
nearest cue is snapped to start right now. That usually lands it in one keypress. Use
the arrows to trim from there; the HUD shows how far you have drifted.

| Key | |
|---|---|
| `space` | play / pause |
| `←` `→` | ∓5s |
| `shift`+`←` `→` | ∓1s |
| `,` `.` | ∓0.5s |
| `↑` `↓` | ∓60s |
| `S` / `return` | snap nearest cue to start now |
| `[` `]` | narrow / widen the context window (0–20s) |
| `-` `=` | text size |
| `F` | fullscreen (`esc` leaves it, or quits if windowed) |
| `O` | open another file |
| `H` | pin the controls open / let them auto-hide |
| `Q` | quit |

The control bar (play/pause, ∓5s, draggable seek bar) fades out while playing and comes
back on mouse movement.

## Notes

- Reads `.srt`, tolerating CRLF, UTF-8/cp1252/latin-1, missing cue numbers, and `<i>` /
  `{\an8}` markup. Malformed blocks are skipped with a count on stderr.
- `examples/` is a scratch folder for your own subtitle files. Its contents are
  gitignored — subtitle files are third-party content, so none ship with this repo.
  Any path works, though; the folder is just a convenient default.
- If `pip install pygame` ever fails to find a wheel, `pygame-ce` is a drop-in
  replacement — same `import pygame`, no code change.
