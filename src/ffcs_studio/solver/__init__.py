"""Pure timetable solver package, independent of HTTP and browser code."""

from ffcs_studio.solver.models import (
    CountOutcome,
    CountStatus,
    CoursePlan,
    CourseRole,
    CreditConstraints,
    CreditSource,
    EvaluationMode,
    RankingPolicy,
    ScenarioSnapshot,
    SearchOutcome,
    SearchTermination,
    SolverCandidate,
    SolverInterval,
    TimetableResult,
)

__all__ = [
    "CountOutcome",
    "CountStatus",
    "CoursePlan",
    "CourseRole",
    "CreditConstraints",
    "CreditSource",
    "EvaluationMode",
    "RankingPolicy",
    "ScenarioSnapshot",
    "SearchOutcome",
    "SearchTermination",
    "SolverCandidate",
    "SolverInterval",
    "TimetableResult",
]
