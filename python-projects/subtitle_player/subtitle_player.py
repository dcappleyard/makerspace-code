#!/usr/bin/env python3

"""
Play a subtitle file on its own black screen, in sync with an external player.

The use case this is built for: put a disc in the DVD player, hit play, then start
this on a laptop sitting next to the TV and watch just the subtitles. Nothing here
decodes video or audio -- it is a stopwatch that draws text -- so the only thing
that matters is how quickly you can drag its clock into line with the disc.

Display:
    Subtitles are drawn on black using a rolling context window: every cue within
    +/- N seconds of the current time is on screen at once, with the line that is
    live right now in bright white and its neighbours progressively dimmed. The
    current line is anchored to a fixed height so it never jumps around as context
    appears above and below it. N is adjustable live with [ and ]; N = 0 shows only
    the current line.

Aligning with the disc:
    Coarse    arrow keys, +/- 5s (or 60s with up/down)
    Fine      shift+arrows for 1s, , and . for half a second
    Instant   press S the moment you hear a line begin, and the nearest cue is
              snapped to start right now -- usually one keypress is enough

    The HUD shows the running offset, so you can see how far you have drifted from
    a straight play-from-the-top.

Keys:
    space            play / pause
    left / right     -5s / +5s          shift+left / shift+right   -1s / +1s
    , / .            -0.5s / +0.5s      up / down                  -60s / +60s
    S or return      snap the nearest cue to start now
    [ / ]            narrow / widen the context window
    - / =            smaller / larger text
    F                fullscreen (esc leaves fullscreen, or quits if windowed)
    O                open a different subtitle file (or just drop one on the window)
    H                pin the controls open / let them auto-hide
    Q                quit

Example:
    python3 subtitle_player.py "examples/your-episode.srt" --window 6 --fullscreen
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

try:
    import pygame
except ImportError:  # pragma: no cover - environment problem, not a code path
    sys.exit(
        "pygame is not installed.\n"
        "  cd python-projects/subtitle_player\n"
        "  /usr/bin/python3 -m venv .venv && .venv/bin/pip install -r requirements.txt\n"
        "then run this script with .venv/bin/python"
    )


# --- Tunables ---------------------------------------------------------------

DEFAULT_WINDOW = 6.0        # seconds of context shown either side of "now"
WINDOW_MIN = 0.0
WINDOW_MAX = 20.0
WINDOW_STEP = 1.0

ANCHOR_FRACTION = 0.42      # where the top of the current line sits, as a fraction
TEXT_WIDTH_FRACTION = 0.85  # of the surface height / width respectively
FONT_HEIGHT_FRACTION = 0.075
FONT_MIN_PX = 12
FONT_MAX_PX = 240
FONT_SCALE_STEP = 1.12

COLOR_BG = (0, 0, 0)
COLOR_CURRENT = (255, 255, 255)
COLOR_NEAR = (150, 150, 150)
COLOR_FAR = (90, 90, 90)

HUD_IDLE_SECONDS = 2.5      # mouse still for this long -> controls fade away
TOAST_SECONDS = 1.5
FPS = 30
WINDOWED_SIZE = (1100, 640)


# --- Parsing ----------------------------------------------------------------

TIMECODE_RE = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})"
)
TAG_RE = re.compile(r"</?(?:i|b|u|font)(?:\s[^>]*)?>", re.IGNORECASE)
ASS_OVERRIDE_RE = re.compile(r"\{\\[^}]*\}")


@dataclass
class Cue:
    start: float
    end: float
    lines: List[str]


def _decode(raw: bytes) -> str:
    """Subtitle files in the wild are utf-8, cp1252, or something close enough."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _to_seconds(hours: str, minutes: str, seconds: str, millis: str) -> float:
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis.ljust(3, "0")) / 1000.0
    )


def _clean(line: str) -> str:
    return ASS_OVERRIDE_RE.sub("", TAG_RE.sub("", line)).strip()


def parse_srt(path: str) -> List[Cue]:
    """Parse an .srt file into time-sorted cues, skipping anything malformed."""
    with open(path, "rb") as handle:
        text = _decode(handle.read())
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    cues: List[Cue] = []
    malformed = 0
    for block in re.split(r"\n\s*\n", text):
        if not block.strip():
            continue
        lines = block.strip("\n").split("\n")
        # A leading cue number is conventional but not required.
        if len(lines) > 1 and lines[0].strip().isdigit() and "-->" in lines[1]:
            lines = lines[1:]
        match = TIMECODE_RE.search(lines[0]) if lines else None
        if match is None:
            malformed += 1
            continue
        start = _to_seconds(*match.group(1, 2, 3, 4))
        end = _to_seconds(*match.group(5, 6, 7, 8))
        body = [cleaned for cleaned in (_clean(l) for l in lines[1:]) if cleaned]
        if not body:
            malformed += 1
            continue
        cues.append(Cue(start, max(start, end), body))

    if malformed:
        print(
            "{}: skipped {} malformed block(s)".format(os.path.basename(path), malformed),
            file=sys.stderr,
        )
    if not cues:
        raise ValueError("no subtitles found in {}".format(path))
    cues.sort(key=lambda cue: (cue.start, cue.end))
    return cues


# --- Clock ------------------------------------------------------------------

class Clock:
    """Playback position, derived from time.monotonic() so it cannot drift."""

    def __init__(self, duration: float, position: float = 0.0) -> None:
        self.duration = max(0.0, duration)
        self._position = self._clamp(position)
        self._started_at = None  # type: Optional[float]

    @property
    def playing(self) -> bool:
        return self._started_at is not None

    def now(self) -> float:
        if self._started_at is None:
            return self._position
        return self._clamp(self._position + (time.monotonic() - self._started_at))

    def play(self) -> None:
        if self._started_at is None:
            self._started_at = time.monotonic()

    def pause(self) -> None:
        if self._started_at is not None:
            self._position = self.now()
            self._started_at = None

    def toggle(self) -> None:
        self.pause() if self.playing else self.play()

    def seek(self, target: float) -> float:
        self._position = self._clamp(target)
        if self._started_at is not None:
            self._started_at = time.monotonic()
        return self._position

    def _clamp(self, value: float) -> float:
        return max(0.0, min(self.duration, value))


# --- Helpers ----------------------------------------------------------------

def format_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "{}:{:02d}:{:02d}".format(hours, minutes, secs)
    return "{:02d}:{:02d}".format(minutes, secs)


def parse_timestamp(value: str) -> float:
    """Accept SS, MM:SS or HH:MM:SS (fractional seconds allowed)."""
    parts = value.split(":")
    if len(parts) > 3:
        raise argparse.ArgumentTypeError("expected SS, MM:SS or HH:MM:SS")
    total = 0.0
    try:
        for part in parts:
            total = total * 60 + float(part)
    except ValueError:
        raise argparse.ArgumentTypeError("not a time: {!r}".format(value))
    return total


def wrap_lines(font, lines: Sequence[str], max_width: int) -> List[str]:
    """Greedy word wrap -- pygame's font has no wrapping of its own."""
    wrapped: List[str] = []
    for line in lines:
        words = line.split()
        if not words:
            continue
        current = words[0]
        for word in words[1:]:
            candidate = current + " " + word
            if font.size(candidate)[0] <= max_width:
                current = candidate
            else:
                wrapped.append(current)
                current = word
        wrapped.append(current)
    return wrapped


def choose_file_dialog() -> Optional[str]:
    """Native file picker via osascript; None if cancelled or not on macOS."""
    if sys.platform != "darwin":
        return None
    script = 'POSIX path of (choose file with prompt "Select a subtitle file")'
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


# --- Player -----------------------------------------------------------------

class Player:
    def __init__(
        self,
        path: str,
        cues: List[Cue],
        window: float = DEFAULT_WINDOW,
        font_size: Optional[int] = None,
        start: float = 0.0,
        fullscreen: bool = False,
    ) -> None:
        self.path = path
        self.cues = cues
        self.window = window
        self.fixed_font_size = font_size
        self.font_scale = 1.0
        self.offset = 0.0
        self.clock = Clock(cues[-1].end, start)

        self.running = True
        self.fullscreen = fullscreen
        self.windowed_size = WINDOWED_SIZE
        self.hud_pinned = False
        self.hud_last_move = time.monotonic()
        self.dragging_seek = False
        self.toast_text = ""
        self.toast_until = 0.0
        self.hit_rects = {}  # type: Dict[str, pygame.Rect]
        self.seek_rect = pygame.Rect(0, 0, 0, 0)

        pygame.display.init()
        pygame.font.init()
        pygame.display.set_caption("Subtitle Player - " + os.path.basename(path))
        self.surface = None
        self._apply_mode()
        self.frame_clock = pygame.time.Clock()

    # -- setup ---------------------------------------------------------------

    def _apply_mode(self) -> None:
        if self.fullscreen:
            self.surface = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.surface = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        self._build_fonts()

    def _build_fonts(self) -> None:
        width, height = self.surface.get_size()
        base = self.fixed_font_size or int(height * FONT_HEIGHT_FRACTION)
        size = int(max(FONT_MIN_PX, min(FONT_MAX_PX, base * self.font_scale)))
        path = pygame.font.match_font("helveticaneue,helvetica,arial,dejavusans")
        self.font = pygame.font.Font(path, size) if path else pygame.font.Font(None, size)
        hud_size = max(13, int(height * 0.023))
        self.hud_font = (
            pygame.font.Font(path, hud_size) if path else pygame.font.Font(None, hud_size)
        )
        status_size = max(11, int(height * 0.019))
        self.status_font = (
            pygame.font.Font(path, status_size)
            if path
            else pygame.font.Font(None, status_size)
        )
        self.line_height = self.font.get_linesize()
        self.max_text_width = int(width * TEXT_WIDTH_FRACTION)

    # -- state ---------------------------------------------------------------

    def _visible_cues(self, now: float) -> List[Cue]:
        return [
            cue
            for cue in self.cues
            if cue.start <= now + self.window and cue.end >= now - self.window
        ]

    def _current_cue(self, now: float) -> Optional[Cue]:
        current = None
        for cue in self.cues:
            if cue.start > now:
                break
            if cue.end >= now:
                current = cue
        return current

    def _jump_to(self, target: float, label: Optional[str] = None) -> None:
        before = self.clock.now()
        after = self.clock.seek(target)
        self.offset += after - before
        if label is not None:
            self._toast(label)

    def _nudge(self, delta: float) -> None:
        self._jump_to(self.clock.now() + delta, "{:+.1f}s".format(delta))

    def _snap_to_line(self) -> None:
        now = self.clock.now()
        nearest = min(self.cues, key=lambda cue: abs(cue.start - now))
        shift = nearest.start - now
        self._jump_to(nearest.start, "synced {:+.1f}s".format(shift))

    def _toast(self, text: str) -> None:
        self.toast_text = text
        self.toast_until = time.monotonic() + TOAST_SECONDS

    def _hud_visible(self) -> bool:
        if self.hud_pinned or not self.clock.playing or self.dragging_seek:
            return True
        return time.monotonic() - self.hud_last_move < HUD_IDLE_SECONDS

    def _load(self, path: str) -> None:
        try:
            cues = parse_srt(path)
        except (OSError, ValueError) as exc:
            self._toast(str(exc))
            return
        self.path = path
        self.cues = cues
        self.clock = Clock(cues[-1].end, 0.0)
        self.offset = 0.0
        pygame.display.set_caption("Subtitle Player - " + os.path.basename(path))
        self._toast("loaded {} ({} lines)".format(os.path.basename(path), len(cues)))

    # -- events --------------------------------------------------------------

    def _handle_event(self, event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.VIDEORESIZE and not self.fullscreen:
            self.windowed_size = (max(320, event.w), max(240, event.h))
            self._apply_mode()
        elif event.type == pygame.DROPFILE:
            self._load(event.file)
        elif event.type == pygame.MOUSEMOTION:
            self.hud_last_move = time.monotonic()
            if self.dragging_seek:
                self._seek_from_mouse(event.pos[0])
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._handle_click(event.pos)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging_seek = False
        elif event.type == pygame.KEYDOWN:
            self._handle_key(event)

    def _handle_click(self, pos) -> None:
        if not self._hud_visible():
            self.hud_last_move = time.monotonic()
            return
        for name, rect in self.hit_rects.items():
            if not rect.collidepoint(pos):
                continue
            if name == "play":
                self.clock.toggle()
            elif name == "back5":
                self._nudge(-5.0)
            elif name == "fwd5":
                self._nudge(5.0)
            elif name == "seek":
                self.dragging_seek = True
                self._seek_from_mouse(pos[0])
            return

    def _seek_from_mouse(self, mouse_x: int) -> None:
        if self.seek_rect.width <= 0:
            return
        fraction = (mouse_x - self.seek_rect.x) / float(self.seek_rect.width)
        fraction = max(0.0, min(1.0, fraction))
        self._jump_to(fraction * self.clock.duration)

    def _handle_key(self, event) -> None:
        key = event.key
        shift = bool(event.mod & pygame.KMOD_SHIFT)

        if key == pygame.K_SPACE:
            self.clock.toggle()
            self._toast("playing" if self.clock.playing else "paused")
        elif key == pygame.K_LEFT:
            self._nudge(-1.0 if shift else -5.0)
        elif key == pygame.K_RIGHT:
            self._nudge(1.0 if shift else 5.0)
        elif key == pygame.K_COMMA:
            self._nudge(-0.5)
        elif key == pygame.K_PERIOD:
            self._nudge(0.5)
        elif key == pygame.K_UP:
            self._nudge(-60.0)
        elif key == pygame.K_DOWN:
            self._nudge(60.0)
        elif key in (pygame.K_s, pygame.K_RETURN, pygame.K_KP_ENTER):
            self._snap_to_line()
        elif key == pygame.K_LEFTBRACKET:
            self.window = max(WINDOW_MIN, self.window - WINDOW_STEP)
            self._toast("window +/-{:g}s".format(self.window))
        elif key == pygame.K_RIGHTBRACKET:
            self.window = min(WINDOW_MAX, self.window + WINDOW_STEP)
            self._toast("window +/-{:g}s".format(self.window))
        elif key == pygame.K_MINUS:
            self.font_scale /= FONT_SCALE_STEP
            self._build_fonts()
            self._toast("text {}px".format(self.font.get_height()))
        elif key == pygame.K_EQUALS:
            self.font_scale *= FONT_SCALE_STEP
            self._build_fonts()
            self._toast("text {}px".format(self.font.get_height()))
        elif key == pygame.K_f:
            self.fullscreen = not self.fullscreen
            self._apply_mode()
        elif key == pygame.K_ESCAPE:
            if self.fullscreen:
                self.fullscreen = False
                self._apply_mode()
            else:
                self.running = False
        elif key == pygame.K_o:
            chosen = choose_file_dialog()
            if chosen:
                self._load(chosen)
            self.hud_last_move = time.monotonic()
        elif key == pygame.K_h:
            self.hud_pinned = not self.hud_pinned
            self._toast("controls pinned" if self.hud_pinned else "controls auto-hide")
        elif key == pygame.K_q:
            self.running = False

    # -- drawing -------------------------------------------------------------

    def render(self) -> None:
        self.surface.fill(COLOR_BG)
        self._draw_subtitles()
        hud = self._hud_visible()
        if hud:
            self._draw_hud()
        else:
            self.hit_rects = {}
        pygame.mouse.set_visible(hud)
        self._draw_toast()

    def _draw_subtitles(self) -> None:
        now = self.clock.now()
        visible = self._visible_cues(now)
        if not visible:
            return
        current = self._current_cue(now)
        if current is None:
            # In a gap: anchor on whatever is coming up next, so the layout stays put.
            upcoming = [cue for cue in visible if cue.start >= now]
            anchor = upcoming[0] if upcoming else visible[-1]
        else:
            anchor = current
        anchor_index = visible.index(anchor)

        width, height = self.surface.get_size()
        blocks = []
        for index, cue in enumerate(visible):
            distance = abs(index - anchor_index)
            if distance == 0:
                color = COLOR_CURRENT if cue is current else COLOR_NEAR
            elif distance == 1:
                color = COLOR_NEAR
            else:
                color = COLOR_FAR
            lines = wrap_lines(self.font, cue.lines, self.max_text_width)
            surfaces = [self.font.render(line, True, color) for line in lines]
            blocks.append((surfaces, len(surfaces) * self.line_height))

        # The control bar's slice of the screen is reserved whether or not the bar is
        # currently drawn, so text never shifts as it fades in and out.
        margin = int(self.line_height * 0.35)
        safe_top = margin
        safe_bottom = height - self._hud_height() - margin
        gap = int(self.line_height * 0.45)

        anchor_top = int(height * ANCHOR_FRACTION)
        anchor_top = min(anchor_top, safe_bottom - blocks[anchor_index][1])
        anchor_top = max(anchor_top, safe_top)

        # Context lines are a courtesy: anything that will not fit is dropped whole
        # rather than clipped mid-line.
        placed = [(anchor_index, anchor_top)]
        y = anchor_top
        for index in range(anchor_index - 1, -1, -1):
            y -= gap + blocks[index][1]
            if y < safe_top:
                break
            placed.append((index, y))
        y = anchor_top + blocks[anchor_index][1]
        for index in range(anchor_index + 1, len(blocks)):
            y += gap
            if y + blocks[index][1] > safe_bottom:
                break
            placed.append((index, y))
            y += blocks[index][1]

        previous_clip = self.surface.get_clip()
        self.surface.set_clip(pygame.Rect(0, 0, width, safe_bottom + margin))
        for index, top in placed:
            surfaces = blocks[index][0]
            for row, surface in enumerate(surfaces):
                x = (width - surface.get_width()) // 2
                self.surface.blit(surface, (x, top + row * self.line_height))
        self.surface.set_clip(previous_clip)

    def _hud_height(self) -> int:
        return max(74, int(self.surface.get_size()[1] * 0.11))

    def _draw_hud(self) -> None:
        width, height = self.surface.get_size()
        bar_height = self._hud_height()
        top = height - bar_height
        panel = pygame.Surface((width, bar_height), pygame.SRCALPHA)
        panel.fill((16, 16, 16, 228))
        self.surface.blit(panel, (0, top))
        pygame.draw.line(self.surface, (52, 52, 52), (0, top), (width, top))

        self.hit_rects = {}
        pad = 16
        button_height = int(bar_height * 0.44)
        row_y = top + pad
        x = pad

        play_rect = pygame.Rect(x, row_y, button_height + 16, button_height)
        pygame.draw.rect(self.surface, (46, 46, 46), play_rect, border_radius=6)
        self._draw_play_icon(play_rect)
        self.hit_rects["play"] = play_rect
        x = play_rect.right + 8

        for name, label in (("back5", "-5s"), ("fwd5", "+5s")):
            text = self.hud_font.render(label, True, (228, 228, 228))
            rect = pygame.Rect(x, row_y, text.get_width() + 24, button_height)
            pygame.draw.rect(self.surface, (46, 46, 46), rect, border_radius=6)
            self.surface.blit(text, text.get_rect(center=rect.center))
            self.hit_rects[name] = rect
            x = rect.right + 8

        now = self.clock.now()
        readout = self.hud_font.render(
            "{} / {}".format(format_time(now), format_time(self.clock.duration)),
            True,
            (228, 228, 228),
        )
        readout_x = width - pad - readout.get_width()
        self.surface.blit(
            readout,
            (readout_x, row_y + (button_height - readout.get_height()) // 2),
        )

        track_left = x + 12
        track_width = max(40, readout_x - 16 - track_left)
        self.seek_rect = pygame.Rect(
            track_left, row_y + button_height // 2 - 3, track_width, 6
        )
        pygame.draw.rect(self.surface, (58, 58, 58), self.seek_rect, border_radius=3)
        fraction = now / self.clock.duration if self.clock.duration else 0.0
        filled = pygame.Rect(
            self.seek_rect.x, self.seek_rect.y, int(track_width * fraction), 6
        )
        pygame.draw.rect(self.surface, (200, 200, 200), filled, border_radius=3)
        pygame.draw.circle(
            self.surface,
            (245, 245, 245),
            (self.seek_rect.x + int(track_width * fraction), self.seek_rect.centery),
            8,
        )
        self.hit_rects["seek"] = self.seek_rect.inflate(16, 26)

        status = self.status_font.render(
            "offset {:+.1f}s    window +/-{:g}s    [S] sync to line    "
            "[F] fullscreen    [H] {}".format(
                self.offset,
                self.window,
                "auto-hide" if self.hud_pinned else "pin",
            ),
            True,
            (132, 132, 132),
        )
        self.surface.blit(status, (pad, height - pad // 2 - status.get_height()))

    def _draw_play_icon(self, rect) -> None:
        size = int(rect.height * 0.42)
        if self.clock.playing:
            bar = max(3, size // 3)
            gap = max(3, bar)
            left = rect.centerx - (bar + gap // 2)
            for offset in (0, bar + gap):
                pygame.draw.rect(
                    self.surface,
                    (235, 235, 235),
                    pygame.Rect(left + offset, rect.centery - size // 2, bar, size),
                )
        else:
            half = size // 2
            pygame.draw.polygon(
                self.surface,
                (235, 235, 235),
                [
                    (rect.centerx - half + 2, rect.centery - half),
                    (rect.centerx - half + 2, rect.centery + half),
                    (rect.centerx + half + 2, rect.centery),
                ],
            )

    def _draw_toast(self) -> None:
        remaining = self.toast_until - time.monotonic()
        if remaining <= 0 or not self.toast_text:
            return
        text = self.hud_font.render(self.toast_text, True, (255, 255, 255))
        if remaining < 0.4:
            text.set_alpha(int(255 * remaining / 0.4))
        self.surface.blit(text, (24, 20))

    # -- loop ----------------------------------------------------------------

    def run(self) -> None:
        self.clock.play()
        while self.running:
            for event in pygame.event.get():
                self._handle_event(event)
            self.render()
            pygame.display.flip()
            self.frame_clock.tick(FPS)
        pygame.quit()


# --- Entry point ------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Play a subtitle file on a black screen, in sync with a DVD.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "subtitles",
        nargs="?",
        help="path to an .srt file (a file picker opens if omitted)",
    )
    parser.add_argument(
        "--window",
        type=float,
        default=DEFAULT_WINDOW,
        help="seconds of context shown either side of now (default: %(default)s)",
    )
    parser.add_argument(
        "--font-size", type=int, help="text size in pixels (default: scales with height)"
    )
    parser.add_argument(
        "--start",
        type=parse_timestamp,
        default=0.0,
        help="start at this position, e.g. 90, 1:30 or 00:01:30",
    )
    parser.add_argument("--fullscreen", action="store_true", help="start fullscreen")
    args = parser.parse_args(argv)

    path = args.subtitles or choose_file_dialog()
    if not path:
        parser.error("no subtitle file given")
    if not os.path.isfile(path):
        parser.error("no such file: {}".format(path))

    try:
        cues = parse_srt(path)
    except (OSError, ValueError) as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 1

    player = Player(
        path=path,
        cues=cues,
        window=max(WINDOW_MIN, min(WINDOW_MAX, args.window)),
        font_size=args.font_size,
        start=args.start,
        fullscreen=args.fullscreen,
    )
    player.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
