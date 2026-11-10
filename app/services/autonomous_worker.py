"""Autonomous Self-Scraping Background Engine.

Enables the system to discover, crawl, extract, validate, and persist leads
on its own across predefined or dynamic geographical targets and industries
without manual user intervention.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.orchestrator import execute_autonomous_run

logger = logging.getLogger("dakini.autonomous")

# Default autonomous scraping targets
DEFAULT_AUTONOMOUS_TARGETS: list[dict[str, str]] = [
    {"city": "Bhubaneswar", "category": "Digital Marketing", "state": "Odisha"},
    {"city": "Mumbai", "category": "Digital Marketing", "state": "Maharashtra"},
    {"city": "Bengaluru", "category": "Software Development", "state": "Karnataka"},
    {"city": "Delhi", "category": "Digital Marketing", "state": "Delhi"},
    {"city": "Hyderabad", "category": "Real Estate", "state": "Telangana"},
    {"city": "Pune", "category": "IT Services", "state": "Maharashtra"},
    {"city": "Kolkata", "category": "Digital Marketing", "state": "West Bengal"},
    {"city": "Chennai", "category": "Healthcare", "state": "Tamil Nadu"},
    {"city": "Ahmedabad", "category": "Business Services", "state": "Gujarat"},
    {"city": "Jaipur", "category": "Travel", "state": "Rajasthan"},
]


class AutonomousScraperEngine:
    """Thread-safe background daemon that autonomously runs lead discovery and verification."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running: bool = False
        self._current_target: Optional[dict[str, Any]] = None
        self._total_runs_completed: int = 0
        self._total_leads_accumulated: int = 0
        self._last_run_time: str = ""
        self._activity_log: list[dict[str, Any]] = []
        self._targets: list[dict[str, str]] = list(DEFAULT_AUTONOMOUS_TARGETS)
        self._interval_seconds: int = 45
        self._default_limit: int = 25

    def is_active(self) -> bool:
        with self._lock:
            return self._is_running and bool(self._thread and self._thread.is_alive())

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "is_running": self._is_running and bool(self._thread and self._thread.is_alive()),
                "current_target": self._current_target,
                "total_runs_completed": self._total_runs_completed,
                "total_leads_accumulated": self._total_leads_accumulated,
                "last_run_time": self._last_run_time,
                "interval_seconds": self._interval_seconds,
                "targets_count": len(self._targets),
                "recent_activity": self._activity_log[-10:],
            }

    def start(
        self,
        interval_seconds: int = 45,
        default_limit: int = 25,
        targets: Optional[list[dict[str, str]]] = None,
    ) -> bool:
        with self._lock:
            if self._is_running and self._thread and self._thread.is_alive():
                return False  # Already active

            self._interval_seconds = max(10, interval_seconds)
            self._default_limit = default_limit
            if targets:
                self._targets = list(targets)
            elif not self._targets:
                self._targets = list(DEFAULT_AUTONOMOUS_TARGETS)

            self._stop_event.clear()
            self._is_running = True
            self._thread = threading.Thread(
                target=self._run_loop,
                name="DakiniAutonomousWorker",
                daemon=True,
            )
            self._thread.start()
            self._log_event("Started autonomous self-scraping engine", {"interval": self._interval_seconds})
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self._is_running:
                return False
            self._is_running = False
            self._stop_event.set()
            self._current_target = None
            self._log_event("Stopped autonomous self-scraping engine")
            return True

    def run_sweep(
        self,
        targets: Optional[list[dict[str, str]]] = None,
        limit_per_target: int = 25,
        phone_required: bool = True,
    ) -> dict[str, Any]:
        """Execute an immediate synchronous or async multi-target sweep."""
        sweep_targets = targets or self._targets or DEFAULT_AUTONOMOUS_TARGETS
        total_discovered = 0
        total_qualified = 0
        total_with_phone = 0
        results_summary = []

        start_time = time.monotonic()
        for t in sweep_targets:
            c = t.get("city", "")
            cat = t.get("category", "Digital Marketing")
            st = t.get("state", "")
            if not c:
                continue

            try:
                res = execute_autonomous_run(
                    city=c,
                    category=cat,
                    state=st,
                    limit=limit_per_target,
                    phone_required=phone_required,
                )
                q = res.get("qualified", 0)
                d = res.get("discovered", 0)
                p = res.get("leads_with_phone", 0)

                total_discovered += d
                total_qualified += q
                total_with_phone += p

                results_summary.append({
                    "city": c,
                    "category": cat,
                    "discovered": d,
                    "qualified": q,
                    "with_phone": p,
                    "csv_file": res.get("csv_file"),
                })
            except Exception as exc:
                results_summary.append({
                    "city": c,
                    "category": cat,
                    "error": str(exc),
                })

        duration = round(time.monotonic() - start_time, 2)
        summary = {
            "status": "completed",
            "targets_scraped": len(sweep_targets),
            "total_discovered": total_discovered,
            "total_qualified": total_qualified,
            "total_with_phone": total_with_phone,
            "duration_seconds": duration,
            "details": results_summary,
        }

        with self._lock:
            self._total_runs_completed += len(sweep_targets)
            self._total_leads_accumulated += total_qualified
            self._last_run_time = datetime.now(timezone.utc).isoformat()
            self._log_event(
                f"Completed autonomous multi-city sweep ({total_qualified} leads collected)",
                {"targets": len(sweep_targets), "duration": duration},
            )

        # Trigger master excel update
        try:
            from export_db_to_excel import main as run_export
            run_export()
        except Exception:
            pass

        return summary

    def _run_loop(self) -> None:
        """Internal autonomous execution loop picking targets sequentially."""
        target_idx = 0

        while not self._stop_event.is_set():
            if not self._targets:
                self._stop_event.wait(5.0)
                continue

            target = self._targets[target_idx % len(self._targets)]
            target_idx += 1

            city = target.get("city", "Mumbai")
            category = target.get("category", "Digital Marketing")
            state = target.get("state", "")

            with self._lock:
                self._current_target = {
                    "city": city,
                    "category": category,
                    "state": state,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }

            try:
                print(f"[autonomous-engine] Autonomously scraping {category} in {city}...", flush=True)
                res = execute_autonomous_run(
                    city=city,
                    category=category,
                    state=state,
                    limit=self._default_limit,
                    phone_required=True,
                )

                q_count = res.get("qualified", 0)
                p_count = res.get("leads_with_phone", 0)

                with self._lock:
                    self._total_runs_completed += 1
                    self._total_leads_accumulated += q_count
                    self._last_run_time = datetime.now(timezone.utc).isoformat()
                    self._current_target = None
                    self._log_event(
                        f"Scraped {q_count} verified leads ({p_count} with phone) in {city} ({category})",
                        {"city": city, "category": category, "leads": q_count},
                    )

                # Export database updates
                try:
                    from export_db_to_excel import main as run_export
                    run_export()
                except Exception:
                    pass

            except Exception as exc:
                print(f"[autonomous-engine] Error scraping {city} | {category}: {exc}", flush=True)
                with self._lock:
                    self._current_target = None
                    self._log_event(f"Error scraping {city}: {exc}")

            # Sleep between autonomous cycles with stop checking
            self._stop_event.wait(timeout=self._interval_seconds)

        with self._lock:
            self._is_running = False
            self._current_target = None

    def _log_event(self, message: str, meta: Optional[dict[str, Any]] = None) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "message": message,
            "meta": meta or {},
        }
        self._activity_log.append(entry)
        if len(self._activity_log) > 50:
            self._activity_log.pop(0)


# Global singleton instance
AUTONOMOUS_ENGINE = AutonomousScraperEngine()

