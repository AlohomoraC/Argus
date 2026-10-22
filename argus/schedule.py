"""Scheduling. The OS timer wakes `argus.py tick` hourly; each job runs once a day after `schedule.hour`
(in `timezone`) and keeps its own done-marker, so a failed job retries next hour without resending the
other, and a laptop asleep at send time catches up on wake. DST needs no special handling.
"""
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .settings import ROOT
from .util import today

JOBS = ("news", "papers")


def marker(cfg, job):
    return cfg.state / f"{job}_last_sent"


def due(cfg, job):
    if not cfg[job]["enabled"]:
        return False
    if datetime.now().hour < cfg["schedule"]["hour"]:
        return False
    m = marker(cfg, job)
    return not (m.exists() and m.read_text().strip() == today())


def cleanup(cfg, days=14):
    """Keep two weeks of generated digests and logs."""
    cutoff = time.time() - days * 86400
    for base in (cfg.path(cfg["paths"]["out"]), cfg.logs):
        for f in base.rglob("*") if base.exists() else []:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()


def mark_done(cfg, job):
    cfg.state.mkdir(parents=True, exist_ok=True)
    marker(cfg, job).write_text(today())


class Tee:
    """Mirror stdout into the day's log file."""

    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file, self.stdout = open(path, "a"), sys.stdout

    def write(self, s):
        self.file.write(s)
        self.stdout.write(s)

    def flush(self):
        self.file.flush()
        self.stdout.flush()


# ---------------------------------------------------------------- installers

def _program(cfg):
    return [sys.executable, str(ROOT / "argus.py"), "tick"] + (
        ["--config", str(cfg.config_path)] if cfg.config_path and Path(cfg.config_path) != ROOT / "config.json" else [])


def _plist(cfg):
    label = cfg["schedule"]["label"]
    args = "".join(f"<string>{a}</string>" for a in _program(cfg))
    log = cfg.logs / "scheduler.log"
    return label, f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key><array>{args}</array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{os.environ.get('PATH', '')}</string></dict>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


def _cron_line(cfg):
    cmd = " ".join(f"'{a}'" for a in _program(cfg))
    return f"0 * * * * PATH='{os.environ.get('PATH', '')}' {cmd} >> '{cfg.logs / 'scheduler.log'}' 2>&1  # argus"


def install(cfg, apply=True):
    cfg.logs.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Darwin":
        label, plist = _plist(cfg)
        path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        if not apply:
            print(f"# would write {path}\n{plist}")
            return
        uid = os.getuid()
        subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plist)
        subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(path)], check=True)
        print(f"installed launchd job {label} -> {path} (runs hourly; jobs fire after "
              f"{cfg['schedule']['hour']}:00 {cfg['timezone']})")
    elif shutil.which("crontab"):
        line = _cron_line(cfg)
        if not apply:
            print(line)
            return
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        kept = [ln for ln in current.splitlines() if "# argus" not in ln]
        subprocess.run(["crontab", "-"], input="\n".join(kept + [line]) + "\n", text=True, check=True)
        print("installed crontab entry (hourly)")
    else:
        raise SystemExit("No launchd or crontab found. Run `argus.py tick` hourly with your own scheduler, "
                         "or use the GitHub Actions workflow in .github/workflows/digest.yml.")


def uninstall(cfg):
    if platform.system() == "Darwin":
        label = cfg["schedule"]["label"]
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], capture_output=True)
        path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
        if path.exists():
            path.unlink()
        print(f"removed launchd job {label}")
    elif shutil.which("crontab"):
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        kept = [ln for ln in current.splitlines() if "# argus" not in ln]
        subprocess.run(["crontab", "-"], input="\n".join(kept) + "\n", text=True, check=True)
        print("removed crontab entry")
