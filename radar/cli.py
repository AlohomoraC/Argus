"""Command line: `python3 radar.py <command>`. Run `python3 radar.py -h` for help."""
import argparse
import sys
import traceback

from . import deliver, doctor, llm, news, papers, render, schedule, settings, tracking
from .util import today

JOB_RUNNERS = {"news": news.run, "papers": papers.run}
EXIT_AGENT = 3  # a step is waiting for the host agent (agent backend)


def _run_jobs(cfg, jobs, backend, gate):
    """Run jobs in order; returns an exit code. `gate` applies the scheduled-time/done-marker rules."""
    model = llm.make(cfg, backend)
    if gate and model.resumable:
        raise SystemExit("`tick` drives script mode; with the agent backend, schedule your agent instead (AGENTS.md).")
    status, waiting = 0, []
    for job in jobs:
        if gate and not schedule.due(cfg, job):
            continue
        print(f"=== {job} ({'dry run' if cfg.dry_run else model.__class__.__name__})")
        try:
            JOB_RUNNERS[job](cfg, model)
            if not cfg.dry_run:
                schedule.mark_done(cfg, job)
        except llm.NeedsAgent as e:
            waiting += e.pending
        except Exception as e:
            status = 1
            traceback.print_exc()
            if cfg["notify_on_failure"] and not cfg.dry_run:
                deliver.send_text(cfg, render.ui(cfg)["failure"].format(job=job) + f": {type(e).__name__}: {str(e)[:300]}")
    if waiting:
        print("\nAGENT ACTION REQUIRED — answer each request, then re-run the same command:")
        for req, resp in waiting:
            print(f"  read  {req}\n  write {resp}")
        return EXIT_AGENT
    return status


def main(argv=None):
    ap = argparse.ArgumentParser(prog="radar.py", description="AI Radar — daily AI news, open-source and agent-paper digest.")
    ap.add_argument("--config", help="path to config.json (default: ./config.json or $RADAR_CONFIG)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run jobs now")
    r.add_argument("jobs", nargs="*", metavar="JOB", help="news, papers or all (default: all)")
    r.add_argument("--dry-run", action="store_true", help="write artifacts to out/dry-run; send nothing, change no state")
    r.add_argument("--backend", choices=list(llm.BACKENDS), help="override llm.backend")

    sub.add_parser("tick", help="scheduled entry point: run jobs that are due (call this hourly)")
    sub.add_parser("due", help="exit 0 if any job is due now, else 1 (lets CI skip setup when idle)")

    t = sub.add_parser("track", help="manage continuously tracked topics")
    tsub = t.add_subparsers(dest="action", required=True)
    tsub.add_parser("list")
    ta = tsub.add_parser("add")
    ta.add_argument("name")
    ta.add_argument("--known", default="(added manually)")
    tr = tsub.add_parser("remove")
    tr.add_argument("id")

    s = sub.add_parser("schedule", help="install the hourly OS timer (launchd on macOS, crontab elsewhere)")
    s.add_argument("action", choices=["install", "uninstall", "print"])

    d = sub.add_parser("doctor", help="check configuration, tools, network and delivery")
    d.add_argument("--send-test", action="store_true", help="also send a test message")

    args = ap.parse_args(argv)
    cfg = settings.load(args.config)

    if args.cmd == "run":
        cfg.dry_run = args.dry_run
        bad = [j for j in args.jobs if j not in (*JOB_RUNNERS, "all")]
        if bad:
            ap.error(f"unknown job(s) {bad}; choose news, papers or all")
        jobs = list(JOB_RUNNERS) if not args.jobs or "all" in args.jobs else args.jobs
        return _run_jobs(cfg, jobs, args.backend, gate=False)
    if args.cmd == "tick":
        if not any(schedule.due(cfg, j) for j in JOB_RUNNERS):
            return 0
        sys.stdout = schedule.Tee(cfg.logs / f"{today()}.log")
        code = _run_jobs(cfg, list(JOB_RUNNERS), None, gate=True)
        schedule.cleanup(cfg)
        return code
    if args.cmd == "due":
        due = [j for j in JOB_RUNNERS if schedule.due(cfg, j)]
        print("due: " + (", ".join(due) or "nothing"))
        return 0 if due else 1
    if args.cmd == "track":
        if args.action == "list":
            for x in tracking.topics(cfg):
                print(f"[{x['status']:8}] {x['id']:28} {x['kind']:6} updated {x['last_update']}  {x['name']} — {x['known'][:60]}")
        elif args.action == "add":
            print("added", tracking.add(cfg, args.name, args.known, "manual", today())["id"])
        else:
            print("removed" if tracking.remove(cfg, args.id) else f"no topic {args.id}")
        return 0
    if args.cmd == "schedule":
        if args.action == "uninstall":
            schedule.uninstall(cfg)
        else:
            schedule.install(cfg, apply=args.action == "install")
        return 0
    if args.cmd == "doctor":
        return 0 if doctor.run(cfg, args.send_test) else 1
    return 0
