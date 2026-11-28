"""Sunset: the sun goes down the core into the ground, the sky turns, stars come out.

The base pairs below `horizon` are the ground; the rest is sky. Over
`minutes` (default 30) the sun comes down the core from the top and its top
goes below the horizon at exactly the halfway point, so a 30-minute entry
that starts at sunset - 15m sets on time. The sky warms from day blue to the
sunset colors, then the afterglow sinks toward the horizon and dims to night
while a few stars twinkle in at the top. Right as the sun goes, a green flash
streaks up the core. After `minutes` it holds the night sky. (Shared with
sunrise; details in effects/_sky.py.)

Options (play.py -o key=value, or options: in a show entry):
  horizon      base pairs of ground at the bottom (default 1; 0 = no ground)
  color        sky colors at sunset: "random" (default, one of the built-in
               palettes, varied a little), a palette (classic, fire, pastel,
               desert, tropical, purple_haze), or colors from the horizon up,
               e.g. "orange,pink,purple,navy"
  stars        on (default) / off: stars in the top two base pairs at night
  moon         on (default) / off: on the tree strand, a moon (4-5 white lights
               on the top of its loop) that comes out with the stars
  minutes      length of the scene; the sun sets at the halfway point (default 30)
  green_flash  on (default) / off: the green streak up the core as the sun goes
  seed         random seed (None = new each run)
"""
from effects import _sky

DESCRIPTION = "The sun sinks into the ground at the halfway point; afterglow, then stars"

OPTIONS = {**_sky.OPTIONS, "green_flash": True}


def prepare(opts):
    return _sky.prepare(opts, rising=False)


render = _sky.render
render_tree = _sky.render_tree
