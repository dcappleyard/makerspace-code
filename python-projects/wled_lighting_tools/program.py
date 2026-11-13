"""The program: the shows, the on/off windows and the defaults (the config's
schedule: and shows: sections), kept in a git-tracked file so it travels with
the effects.

    program/program.yaml       tracked; edited by the dashboard or by hand
    config.yaml                git-ignored machine config: wled:, location:
    (data/config.yaml in Docker)

The program file is $WLED_PROGRAM, else program/program.yaml next to the code.
If it doesn't exist, schedule:/shows: from the machine config are used (the
pre-program layout). If both have them, the program file wins.
"""
import logging
import os
from pathlib import Path

from schedule import Schedule
from shows import load_shows
from testpattern import load_config

HERE = Path(__file__).resolve().parent
PROGRAM_KEYS = ("schedule", "shows")
log = logging.getLogger("runner")


def program_path():
    return Path(os.environ.get("WLED_PROGRAM") or HERE / "program" / "program.yaml")


def mtime(path):
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def merge(machine_cfg, program_cfg):
    """Machine config + program -> the config the runner uses."""
    cfg = {k: v for k, v in machine_cfg.items() if k not in PROGRAM_KEYS}
    for k in PROGRAM_KEYS:
        if k in program_cfg:
            cfg[k] = program_cfg[k]
    return cfg


def load_program(machine_cfg, path=None, quiet=False):
    """-> (merged config, the file the program came from).

    Raises ValueError if the program file can't be read or isn't a mapping."""
    path = Path(path) if path else program_path()
    if not path.exists():
        return machine_cfg, None
    try:
        prog = load_config(path)
    except Exception as e:                 # YAML error, e.g. merge-conflict markers
        raise ValueError(f"{path.name}: {e}") from None
    if not isinstance(prog, dict):
        raise ValueError(f"{path.name}: not a YAML mapping")
    if not quiet and any(k in machine_cfg for k in PROGRAM_KEYS):
        log.info("using the program in %s; schedule:/shows: in the machine config are ignored", path)
    return merge(machine_cfg, prog), path


def check(cfg):
    """Validate a merged config well enough to run it. Returns a warning string
    (e.g. an effect this build doesn't have, which the runner will skip) or
    None; raises ValueError if it can't be run at all."""
    try:
        shows_, default = load_shows(cfg, strict=True)
        warning = None
    except ValueError as e:
        warning = str(e)
        shows_, default = load_shows(cfg)          # skips the bad entries (logged)
    if not shows_:
        raise ValueError(f"no playable shows ({warning})" if warning else "no shows")
    try:
        Schedule.from_config(cfg, default)
    except Exception as e:
        raise ValueError(f"schedule: {e}") from None
    return warning
