"""Sunrise: stars fade, dawn colors build, the sun comes up the core.

The sunset scene run backwards. The base pairs below `horizon` are the
ground; the rest is sky. It starts on a night sky with a few twinkling stars
at the top; they fade as dawn colors build up from the horizon, and the top of
the sun comes over the horizon at exactly the halfway point of `minutes`
(default 30), so a 30-minute entry that starts at sunrise - 15m rises on
time. The sun then climbs the core and the sky goes to day blue, which it
holds after `minutes`. (Shared with sunset; details in effects/_sky.py.)

Options (play.py -o key=value, or options: in a show entry):
  horizon      base pairs of ground at the bottom (default 1; 0 = no ground)
  color        sky colors at sunrise: "random" (default, one of the built-in
               palettes, varied a little), a palette (classic, fire, pastel,
               desert, tropical, purple_haze), or colors from the horizon up,
               e.g. "orange,pink,purple,navy"
  stars        on (default) / off: stars in the top two base pairs before dawn
  minutes      length of the scene; the sun rises at the halfway point (default 30)
  green_flash  off (default) / on: a green streak up the core as the sun appears
  seed         random seed (None = new each run)
"""
from effects import _sky

DESCRIPTION = "Stars fade, dawn builds, and the sun rises at the halfway point"

OPTIONS = {**_sky.OPTIONS, "green_flash": False}


def prepare(opts):
    return _sky.prepare(opts, rising=True)


render = _sky.render
