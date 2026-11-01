"""Autonomous background worker for Dakini Public-Web Business Discovery System.

Usage:
    python -m app.worker              (Continuous polling worker)
    python -m app.worker --once       (Process current queued runs and exit)
    python -m app.worker --run --city Mumbai --category "Digital Marketing" --limit 25
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from app.config import WORKER_LOCK_FILE, WORKER_POLL_INTERVAL_SECONDS
from app.services.orchestrator import execute_autonomous_run
from app.services.persistence import (
    get_queued_or_interrupted_run,
    update_research_run,
)

_SHUTDOWN_REQUESTED = False


def _signal_handler(signum: int, frame: Any) -> None:
    global _SHUTDOWN_REQUESTED
    print("\n[worker] Shutdown signal received. Finishing active tasks gracefully...")
    _SHUTDOWN_REQUESTED = True


def acquire_worker_lock(lock_path: str = WORKER_LOCK_FILE) -> bool:
    """Acquire single-worker lock file; handle stale locks."""
    p = Path(lock_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        try:
            pid = int(p.read_text().strip())
            # Check if process is still alive on Windows/Unix
            if pid != os.getpid():
                try:
                    os.kill(pid, 0)
                    print(f"[worker] Another worker instance (PID {pid}) is already running. Exiting.")
                    return False
                except OSError:
                    # Stale lock from crashed process
                    print(f"[worker] Removing stale lock from PID {pid}.")
                    p.unlink(missing_ok=True)
        except Exception:
            p.unlink(missing_ok=True)

    try:
        p.write_text(str(os.getpid()))
        return True
    except Exception as exc:
        print(f"[worker] Failed to acquire lock file: {exc}")
        return False


def release_worker_lock(lock_path: str = WORKER_LOCK_FILE) -> None:
    p = Path(lock_path)
    if p.exists():
        try:
            if p.read_text().strip() == str(os.getpid()):
                p.unlink(missing_ok=True)
        except Exception:
            pass


def process_next_run() -> bool:
    """Find and execute next queued or interrupted research run."""
    run_record = get_queued_or_interrupted_run()
    if not run_record:
        return False

    run_id = run_record["run_id"]
    print(f"\n[worker] Processing run {run_id}: {run_record['industry']} in {run_record['city']}...")

    try:
        execute_autonomous_run(
            city=run_record["city"],
            category=run_record["industry"],
            state=run_record.get("state", ""),
            country=run_record.get("country", "India"),
            locality=run_record.get("locality", ""),
            run_id=run_id,
            trigger_type="worker",
        )
        return True
    except (KeyboardInterrupt, SystemExit):
        update_research_run(run_id=run_id, execution_status="partially_completed")
        raise
    except Exception as exc:
        print(f"[worker] Error executing run {run_id}: {exc}")
        update_research_run(
            run_id=run_id,
            execution_status="failed",
            error_message=str(exc),
        )
        return False


def run_worker_loop(once: bool = False) -> None:
    """Autonomous polling loop."""
    if not acquire_worker_lock():
        sys.exit(1)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    print(f"\n=======================================================")
    print(f" Dakini AI - Autonomous Public-Web Discovery Worker")
    print(f" Mode: {'Run Once' if once else 'Continuous Background Poller'}")
    print(f" Polling Interval: {WORKER_POLL_INTERVAL_SECONDS}s")
    print(f" PID: {os.getpid()}")
    print(f"=======================================================\n")

    try:
        while not _SHUTDOWN_REQUESTED:
            processed = process_next_run()
            if once:
                break
            if not processed:
                time.sleep(WORKER_POLL_INTERVAL_SECONDS)
    finally:
        release_worker_lock()
        print("[worker] Worker stopped cleanly.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dakini AI Autonomous Discovery Worker")
    parser.add_argument("--once", action="store_true", help="Process queued runs and exit")
    parser.add_argument("--run", action="store_true", help="Execute single manual research run directly")
    parser.add_argument("--city", type=str, default="Mumbai", help="Target city")
    parser.add_argument("--category", type=str, default="Digital Marketing", help="Target industry category")
    parser.add_argument("--state", type=str, default="", help="Target state")
    parser.add_argument("--limit", type=int, default=25, help="Target lead count")

    args = parser.parse_args()

    if args.run:
        execute_autonomous_run(
            city=args.city,
            category=args.category,
            state=args.state,
            limit=args.limit,
            trigger_type="cli",
        )
    else:
        run_worker_loop(once=args.once)


if __name__ == "__main__":
    main()

