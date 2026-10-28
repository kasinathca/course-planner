"""Bounded process workers for responsive, cancellable solver and count jobs."""

from __future__ import annotations

import multiprocessing
import queue
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ffcs_studio.solver.counting import count_exact
from ffcs_studio.solver.models import CountOutcome, CountStatus, ScenarioSnapshot, SearchOutcome
from ffcs_studio.solver.optimized import solve_top_k


class SolverJobError(RuntimeError):
    code = "solver_job_error"


class SolverJobNotFound(SolverJobError):
    code = "solver_job_not_found"


class SolverJobConflict(SolverJobError):
    code = "solver_job_conflict"


@dataclass(slots=True)
class JobRecord:
    job_id: str
    scenario: ScenarioSnapshot
    status: str = "queued"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    started_at: str | None = None
    completed_at: str | None = None
    progress: dict[str, int | float | str] = field(default_factory=dict)
    outcome: SearchOutcome | None = None
    error: str | None = None
    process: Any | None = None
    event: Any | None = None
    messages: Any | None = None
    count_status: CountStatus = CountStatus.NOT_REQUESTED
    count_outcome: CountOutcome | None = None
    count_progress: dict[str, int | float | str] = field(default_factory=dict)
    count_process: Any | None = None
    count_event: Any | None = None
    count_messages: Any | None = None


class SolverJobManager:
    def __init__(self, *, max_workers: int = 2, cancel_grace_seconds: float = 2.0) -> None:
        self.max_workers = max_workers
        self.cancel_grace_seconds = cancel_grace_seconds
        self._context: Any = multiprocessing.get_context("spawn")
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.RLock()
        self._closed = False

    def create(self, scenario: ScenarioSnapshot) -> dict[str, Any]:
        with self._lock:
            self._ensure_open()
            self._refresh_locked()
            self._trim_locked()
            job_id = uuid4().hex
            record = JobRecord(job_id=job_id, scenario=scenario)
            self._jobs[job_id] = record
            self._start_pending_locked()
            return self._status_locked(record)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._refresh_locked()
            record = self._record(job_id)
            return self._status_locked(record)

    def results(self, job_id: str, *, page: int, page_size: int) -> dict[str, Any]:
        with self._lock:
            self._refresh_locked()
            record = self._record(job_id)
            results = record.outcome.results if record.outcome else ()
            start = (page - 1) * page_size
            items = results[start : start + page_size]
            search = record.outcome.to_dict() if record.outcome else None
            if search is not None:
                search.pop("results", None)
            return {
                "job_id": job_id,
                "status": record.status,
                "search": search,
                "items": [item.to_dict() for item in items],
                "page": page,
                "page_size": page_size,
                "total": len(results),
            }

    def result_snapshot(self, job_id: str, result_id: str) -> dict[str, Any]:
        """Return one completed result with its frozen worker scenario for durable saving."""
        with self._lock:
            self._refresh_locked()
            record = self._record(job_id)
            if record.outcome is None:
                raise SolverJobConflict("Solver results are not available yet")
            result = next(
                (item for item in record.outcome.results if item.result_id == result_id), None
            )
            if result is None:
                raise SolverJobNotFound("The requested solver result was not found in this job")
            return {
                "scenario": record.scenario,
                "result": result,
                "search_termination": record.outcome.termination.value,
                "search_exhaustive": record.outcome.exhaustive,
            }

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._refresh_locked()
            record = self._record(job_id)
            if record.status == "queued":
                record.status = "cancelled"
                record.completed_at = datetime.now(UTC).isoformat()
            elif record.status in {"running", "cancellation_requested"}:
                record.status = "cancellation_requested"
                if record.event is not None:
                    record.event.set()
                self._schedule_fallback(job_id, count=False)
            return self._status_locked(record)

    def start_count(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._refresh_locked()
            record = self._record(job_id)
            if record.count_status not in {CountStatus.NOT_REQUESTED}:
                raise SolverJobConflict("count was already requested for this job")
            record.count_status = CountStatus.PENDING
            self._start_pending_locked()
            return self._count_status_locked(record)

    def count_status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._refresh_locked()
            return self._count_status_locked(self._record(job_id))

    def cancel_count(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._refresh_locked()
            record = self._record(job_id)
            if record.count_status is CountStatus.PENDING:
                record.count_status = CountStatus.CANCELLED
            elif record.count_status is CountStatus.RUNNING:
                if record.count_event is not None:
                    record.count_event.set()
                self._schedule_fallback(job_id, count=True)
            return self._count_status_locked(record)

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            processes: list[tuple[Any, Any]] = []
            for record in self._jobs.values():
                if record.event is not None:
                    record.event.set()
                if record.count_event is not None:
                    record.count_event.set()
                if record.process is not None:
                    processes.append((record.process, record.messages))
                if record.count_process is not None:
                    processes.append((record.count_process, record.count_messages))
        for process, messages in processes:
            process.join(self.cancel_grace_seconds)
            if process.is_alive():
                process.terminate()
                process.join(1)
            if messages is not None:
                messages.close()

    def _record(self, job_id: str) -> JobRecord:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise SolverJobNotFound("solver job was not found") from exc

    def _ensure_open(self) -> None:
        if self._closed:
            raise SolverJobConflict("solver job manager is shutting down")

    def _active_count_locked(self) -> int:
        return sum(
            int(record.process is not None and record.process.is_alive())
            + int(record.count_process is not None and record.count_process.is_alive())
            for record in self._jobs.values()
        )

    def _start_pending_locked(self) -> None:
        while self._active_count_locked() < self.max_workers:
            pending_search = next(
                (record for record in self._jobs.values() if record.status == "queued"), None
            )
            if pending_search is not None:
                self._start_search_locked(pending_search)
                continue
            pending_count = next(
                (
                    record
                    for record in self._jobs.values()
                    if record.count_status is CountStatus.PENDING
                ),
                None,
            )
            if pending_count is None:
                break
            self._start_count_locked(pending_count)

    def _start_search_locked(self, record: JobRecord) -> None:
        record.messages = self._context.Queue(maxsize=64)
        record.event = self._context.Event()
        record.process = self._context.Process(
            target=_search_worker,
            args=(record.scenario, record.messages, record.event),
            name=f"ffcs-solver-{record.job_id[:8]}",
        )
        record.process.start()
        record.status = "running"
        record.started_at = datetime.now(UTC).isoformat()

    def _start_count_locked(self, record: JobRecord) -> None:
        record.count_messages = self._context.Queue(maxsize=64)
        record.count_event = self._context.Event()
        record.count_process = self._context.Process(
            target=_count_worker,
            args=(record.scenario, record.count_messages, record.count_event),
            name=f"ffcs-count-{record.job_id[:8]}",
        )
        record.count_process.start()
        record.count_status = CountStatus.RUNNING

    def _refresh_locked(self) -> None:
        for record in self._jobs.values():
            self._drain_search_locked(record)
            self._drain_count_locked(record)
        self._start_pending_locked()

    def _drain_search_locked(self, record: JobRecord) -> None:
        self._consume_search_messages(record)
        if record.process is not None and not record.process.is_alive():
            record.process.join()
            if record.outcome is None and record.messages is not None:
                with suppress(queue.Empty):
                    kind, value = record.messages.get(timeout=0.1)
                    self._apply_search_message(record, kind, value)
            if record.outcome is None and record.status not in {"failed", "cancelled"}:
                record.status = "failed"
                record.error = "solver worker exited without a result"
                record.completed_at = datetime.now(UTC).isoformat()
            if record.messages is not None:
                record.messages.close()
            record.messages = None
            record.process = None
            record.event = None

    def _drain_count_locked(self, record: JobRecord) -> None:
        self._consume_count_messages(record)
        if record.count_process is not None and not record.count_process.is_alive():
            record.count_process.join()
            if record.count_outcome is None and record.count_messages is not None:
                with suppress(queue.Empty):
                    kind, value = record.count_messages.get(timeout=0.1)
                    self._apply_count_message(record, kind, value)
            if record.count_outcome is None and record.count_status is CountStatus.RUNNING:
                record.count_status = CountStatus.FAILED
                record.count_progress = {"error": "count worker exited without a result"}
            if record.count_messages is not None:
                record.count_messages.close()
            record.count_messages = None
            record.count_process = None
            record.count_event = None

    def _consume_search_messages(self, record: JobRecord) -> None:
        if record.messages is None:
            return
        while True:
            try:
                kind, value = record.messages.get_nowait()
            except queue.Empty:
                break
            self._apply_search_message(record, kind, value)

    def _apply_search_message(self, record: JobRecord, kind: str, value: Any) -> None:
        if kind == "progress":
            record.progress = value
        elif kind == "complete":
            record.outcome = value
            record.status = value.termination.value
            record.completed_at = datetime.now(UTC).isoformat()
        elif kind == "failed":
            record.status = "failed"
            record.error = value
            record.completed_at = datetime.now(UTC).isoformat()

    def _consume_count_messages(self, record: JobRecord) -> None:
        if record.count_messages is None:
            return
        while True:
            try:
                kind, value = record.count_messages.get_nowait()
            except queue.Empty:
                break
            self._apply_count_message(record, kind, value)

    def _apply_count_message(self, record: JobRecord, kind: str, value: Any) -> None:
        if kind == "progress":
            record.count_progress = value
        elif kind == "complete":
            record.count_outcome = value
            record.count_status = value.status
        elif kind == "failed":
            record.count_status = CountStatus.FAILED
            record.count_progress = {"error": value}

    def _status_locked(self, record: JobRecord) -> dict[str, Any]:
        return {
            "job_id": record.job_id,
            "scenario_id": record.scenario.scenario_id,
            "scenario_fingerprint": record.scenario.fingerprint,
            "status": record.status,
            "created_at": record.created_at,
            "started_at": record.started_at,
            "completed_at": record.completed_at,
            "progress": record.progress,
            "error": record.error,
            "result_count": len(record.outcome.results) if record.outcome else 0,
            "exhaustive": record.outcome.exhaustive if record.outcome else False,
            "count_status": record.count_status.value,
        }

    def _count_status_locked(self, record: JobRecord) -> dict[str, Any]:
        return {
            "job_id": record.job_id,
            "status": record.count_status.value,
            "progress": record.count_progress,
            "result": record.count_outcome.to_dict() if record.count_outcome else None,
        }

    def _schedule_fallback(self, job_id: str, *, count: bool) -> None:
        thread = threading.Thread(
            target=self._force_cancel_after_grace,
            args=(job_id, count),
            daemon=True,
            name=f"ffcs-cancel-{job_id[:8]}",
        )
        thread.start()

    def _force_cancel_after_grace(self, job_id: str, count: bool) -> None:
        time.sleep(self.cancel_grace_seconds)
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            process = record.count_process if count else record.process
            if process is not None and process.is_alive():
                process.terminate()
                process.join(1)
                if count:
                    record.count_status = CountStatus.CANCELLED
                else:
                    record.status = "cancelled"
                    record.completed_at = datetime.now(UTC).isoformat()

    def _trim_locked(self) -> None:
        completed = [
            record
            for record in self._jobs.values()
            if record.status not in {"queued", "running", "cancellation_requested"}
            and record.count_status not in {CountStatus.PENDING, CountStatus.RUNNING}
        ]
        for record in sorted(completed, key=lambda item: item.created_at)[:-50]:
            self._jobs.pop(record.job_id, None)


def _search_worker(scenario: ScenarioSnapshot, messages: Any, event: Any) -> None:
    def progress(value: dict[str, int | float | str]) -> None:
        with suppress(queue.Full):
            messages.put_nowait(("progress", value))

    try:
        outcome = solve_top_k(scenario, cancel_event=event, progress=progress)
        _put_final(messages, ("complete", outcome))
    except BaseException as exc:
        _put_final(messages, ("failed", f"{type(exc).__name__}: {exc}"))


def _count_worker(scenario: ScenarioSnapshot, messages: Any, event: Any) -> None:
    def progress(value: dict[str, int | float | str]) -> None:
        with suppress(queue.Full):
            messages.put_nowait(("progress", value))

    try:
        outcome = count_exact(scenario, cancel_event=event, progress=progress)
        _put_final(messages, ("complete", outcome))
    except BaseException as exc:
        _put_final(messages, ("failed", f"{type(exc).__name__}: {exc}"))


def _put_final(messages: Any, value: tuple[str, object]) -> None:
    while True:
        try:
            messages.put_nowait(value)
            return
        except queue.Full:
            with suppress(queue.Empty):
                messages.get_nowait()
