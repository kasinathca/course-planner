"""Bounded process-backed jobs for potentially expensive recovery searches."""

from __future__ import annotations

import multiprocessing
import queue
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from multiprocessing.context import SpawnContext
from typing import Any
from uuid import uuid4

from ffcs_studio.degree.recovery import recover, request_from_payload


class RecoveryJobError(RuntimeError):
    code = "recovery_job_error"


class RecoveryJobNotFound(RecoveryJobError):
    code = "recovery_job_not_found"


@dataclass(slots=True)
class _RecoveryJob:
    job_id: str
    process: Any
    queue: Any
    cancel_event: Any
    status: str
    created_at: str
    result: dict[str, Any] | None = None
    error: str | None = None


class RecoveryJobManager:
    def __init__(self, *, max_workers: int = 2, cancel_grace_seconds: float = 1.0) -> None:
        self._context: SpawnContext = multiprocessing.get_context("spawn")
        self._max_workers = max_workers
        self._cancel_grace_seconds = cancel_grace_seconds
        self._jobs: dict[str, _RecoveryJob] = {}
        self._lock = threading.Lock()

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._refresh_all()
            active = sum(
                job.status in {"queued", "running", "cancellation_requested"}
                for job in self._jobs.values()
            )
            if active >= self._max_workers:
                raise RecoveryJobError("The configured recovery-worker limit is busy")
            job_id = uuid4().hex
            result_queue = self._context.Queue(maxsize=2)
            cancel_event = self._context.Event()
            process = self._context.Process(
                target=_recovery_worker,
                args=(payload, result_queue, cancel_event),
                name=f"ffcs-recovery-{job_id[:8]}",
            )
            job = _RecoveryJob(
                job_id,
                process,
                result_queue,
                cancel_event,
                "queued",
                datetime.now(UTC).isoformat(),
            )
            self._jobs[job_id] = job
            process.start()
            job.status = "running"
            return self._public(job)

    def status(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._job(job_id)
            self._refresh(job)
            return self._public(job)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._job(job_id)
            self._refresh(job)
            if job.status not in {"queued", "running", "cancellation_requested"}:
                return self._public(job)
            job.status = "cancellation_requested"
            job.cancel_event.set()
            job.process.join(self._cancel_grace_seconds)
            if job.process.is_alive():
                job.process.terminate()
                job.process.join(self._cancel_grace_seconds)
                job.status = "cancelled"
            self._refresh(job)
            return self._public(job)

    def shutdown(self) -> None:
        with self._lock:
            for job in self._jobs.values():
                if job.process.is_alive():
                    job.cancel_event.set()
                    job.process.join(self._cancel_grace_seconds)
                    if job.process.is_alive():
                        job.process.terminate()
                        job.process.join(self._cancel_grace_seconds)
                job.queue.close()

    def _job(self, job_id: str) -> _RecoveryJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise RecoveryJobNotFound("Recovery job was not found") from exc

    def _refresh_all(self) -> None:
        for job in self._jobs.values():
            self._refresh(job)

    def _refresh(self, job: _RecoveryJob) -> None:
        while True:
            try:
                message = job.queue.get_nowait()
            except queue.Empty:
                break
            if message["kind"] == "result":
                job.result = message["result"]
                job.status = str(job.result["status"])
            else:
                job.error = str(message["message"])
                job.status = "failed"
        if not job.process.is_alive() and job.status in {"running", "cancellation_requested"}:
            job.process.join(timeout=0)
            if job.result is None and job.error is None:
                job.status = "cancelled" if job.cancel_event.is_set() else "failed"

    @staticmethod
    def _public(job: _RecoveryJob) -> dict[str, Any]:
        return {
            "job_id": job.job_id,
            "status": job.status,
            "created_at": job.created_at,
            "result": job.result,
            "error": job.error,
        }


def _recovery_worker(payload: dict[str, Any], result_queue: Any, cancel_event: Any) -> None:
    try:
        result = recover(request_from_payload(payload), cancel_event)
        result_queue.put({"kind": "result", "result": result})
    except BaseException as exc:
        result_queue.put({"kind": "error", "message": str(exc)})
