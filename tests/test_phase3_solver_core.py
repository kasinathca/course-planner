from __future__ import annotations

import random
import threading

from ffcs_studio.solver.counting import count_exact
from ffcs_studio.solver.models import (
    CountStatus,
    CoursePlan,
    CourseRole,
    CreditConstraints,
    CreditSource,
    EvaluationMode,
    RankingPolicy,
    ScenarioSnapshot,
    SearchTermination,
    SolverCandidate,
    SolverInterval,
)
from ffcs_studio.solver.occupancy import (
    interval_mask,
    masks_match_interval_overlap,
    occupancy_mask,
)
from ffcs_studio.solver.optimized import solve_top_k
from ffcs_studio.solver.reference import reference_solution_identities


def meeting(
    allocation_id: int,
    day: int,
    start: int,
    end: int,
    *,
    kind: str = "theory",
    session_id: str | None = None,
) -> SolverInterval:
    return SolverInterval(
        day=day,
        start_minute=start,
        end_minute=end,
        kind=kind,
        allocation_id=allocation_id,
        component_type="ELA" if kind == "lab" else "TH",
        slot=f"S{allocation_id}",
        faculty=f"Faculty {allocation_id}",
        venue=f"Room {allocation_id}",
        session_id=session_id,
    )


def candidate(
    course: str,
    offering_id: int,
    allocation_id: int,
    intervals: tuple[SolverInterval, ...],
) -> SolverCandidate:
    return SolverCandidate(
        candidate_id=f"{course}-{allocation_id}",
        offering_id=offering_id,
        revision_id=1000 + offering_id,
        course_code=course,
        allocation_ids=(allocation_id,),
        meetings=intervals,
        occupancy_mask=occupancy_mask(intervals),
        verification_status="verified",
    )


def course(
    code: str,
    offering_id: int,
    role: CourseRole,
    candidates: tuple[SolverCandidate, ...],
    *,
    priority: int = 1,
    credits: int | None = 3000,
    category: str = "PC",
) -> CoursePlan:
    return CoursePlan(
        offering_id=offering_id,
        revision_id=1000 + offering_id,
        course_code=code,
        course_title=code,
        category=category,
        role=role,
        priority_tier=priority,
        curriculum_type="TH",
        curriculum_source=CreditSource.VERIFIED,
        credit_milli=credits,
        credit_source=CreditSource.VERIFIED if credits is not None else CreditSource.UNKNOWN,
        candidates=candidates,
    )


def scenario(
    courses: tuple[CoursePlan, ...],
    *,
    top_k: int = 100,
    credits: CreditConstraints | None = None,
    ranking: RankingPolicy | None = None,
    max_nodes: int | None = None,
) -> ScenarioSnapshot:
    return ScenarioSnapshot(
        scenario_id="test-scenario",
        fingerprint="f" * 64,
        campus="Vellore",
        semester_label="Synthetic",
        calendar_id="calendar-1",
        calendar_verification="official_verified",
        mode=EvaluationMode.STRICT_VERIFIED,
        courses=courses,
        occupied_intervals=(),
        occupied_mask=0,
        credit_constraints=credits or CreditConstraints(),
        ranking_policy=ranking or RankingPolicy(),
        top_k=top_k,
        max_search_nodes=max_nodes,
    )


def test_minute_bitset_matches_half_open_interval_overlap() -> None:
    left = meeting(1, 0, 480, 530)
    touching = meeting(2, 0, 530, 580)
    overlap = meeting(3, 0, 529, 540)
    other_day = meeting(4, 1, 480, 530)
    assert masks_match_interval_overlap(left, touching)
    assert masks_match_interval_overlap(left, overlap)
    assert masks_match_interval_overlap(left, other_day)
    assert not interval_mask(left) & interval_mask(touching)
    assert interval_mask(left) & interval_mask(overlap)


def test_one_required_course_keeps_every_section_and_exact_count() -> None:
    options = (
        candidate("A", 1, 1, (meeting(1, 0, 480, 530),)),
        candidate("A", 1, 2, (meeting(2, 1, 480, 530),)),
    )
    problem = scenario((course("A", 1, CourseRole.REQUIRED, options),))
    searched = solve_top_k(problem)
    counted = count_exact(problem)
    assert searched.termination is SearchTermination.EXHAUSTED
    assert len(searched.results) == 2
    assert all(result.selected_courses == ("A",) for result in searched.results)
    assert counted.status is CountStatus.EXACT
    assert counted.exact_count == 2


def test_two_conflicting_required_courses_are_infeasible() -> None:
    first = candidate("A", 1, 1, (meeting(1, 0, 480, 530),))
    second = candidate("B", 2, 2, (meeting(2, 0, 500, 550),))
    problem = scenario(
        (
            course("A", 1, CourseRole.REQUIRED, (first,)),
            course("B", 2, CourseRole.REQUIRED, (second,)),
        )
    )
    assert solve_top_k(problem).termination is SearchTermination.INFEASIBLE
    assert count_exact(problem).exact_count == 0


def test_required_course_is_never_omitted_for_optional_course() -> None:
    required = candidate("REQ", 1, 1, (meeting(1, 0, 480, 530),))
    optional = candidate("OPT", 2, 2, (meeting(2, 0, 480, 530),))
    problem = scenario(
        (
            course("REQ", 1, CourseRole.REQUIRED, (required,)),
            course("OPT", 2, CourseRole.OPTIONAL, (optional,)),
        )
    )
    outcome = solve_top_k(problem)
    assert len(outcome.results) == 1
    assert outcome.results[0].selected_courses == ("REQ",)


def test_optional_subsets_are_counted_separately_from_top_k() -> None:
    required = candidate("REQ", 1, 1, (meeting(1, 0, 480, 530),))
    optional_a = candidate("A", 2, 2, (meeting(2, 1, 480, 530),))
    optional_b = candidate("B", 3, 3, (meeting(3, 2, 480, 530),))
    problem = scenario(
        (
            course("REQ", 1, CourseRole.REQUIRED, (required,)),
            course("A", 2, CourseRole.OPTIONAL, (optional_a,), priority=1),
            course("B", 3, CourseRole.OPTIONAL, (optional_b,), priority=2),
        ),
        top_k=2,
    )
    searched = solve_top_k(problem)
    counted = count_exact(problem)
    assert len(searched.results) == 2
    assert searched.feasible_solutions_seen == 4
    assert counted.exact_count == 4
    assert searched.results[0].selected_courses == ("A", "B", "REQ")


def test_credit_minimum_and_maximum_are_hard_constraints() -> None:
    required = candidate("REQ", 1, 1, (meeting(1, 0, 480, 530),))
    optional = candidate("OPT", 2, 2, (meeting(2, 1, 480, 530),))
    minimum = scenario(
        (
            course("REQ", 1, CourseRole.REQUIRED, (required,), credits=3000),
            course("OPT", 2, CourseRole.OPTIONAL, (optional,), credits=2000),
        ),
        credits=CreditConstraints(minimum_milli=5000, maximum_milli=5000),
    )
    assert count_exact(minimum).exact_count == 1
    assert solve_top_k(minimum).results[0].metrics.total_credits_milli == 5000


def test_occupied_period_removes_an_otherwise_valid_section() -> None:
    option = candidate("A", 1, 1, (meeting(1, 0, 480, 530),))
    base = scenario((course("A", 1, CourseRole.REQUIRED, (option,)),))
    occupied = meeting(-1, 0, 500, 510)
    blocked = ScenarioSnapshot(
        **{
            **{name: getattr(base, name) for name in base.__dataclass_fields__},
            "occupied_intervals": (occupied,),
            "occupied_mask": occupancy_mask((occupied,)),
        }
    )
    assert solve_top_k(blocked).termination is SearchTermination.INFEASIBLE


def test_priority_tier_precedes_lab_workload() -> None:
    required = candidate("REQ", 1, 1, (meeting(1, 0, 480, 530),))
    high_lab = candidate(
        "HIGH",
        2,
        2,
        (meeting(2, 1, 480, 580, kind="lab", session_id="lab-high"),),
    )
    low_no_lab = candidate("LOW", 3, 3, (meeting(3, 2, 480, 530),))
    problem = scenario(
        (
            course("REQ", 1, CourseRole.REQUIRED, (required,)),
            course("HIGH", 2, CourseRole.OPTIONAL, (high_lab,), priority=1),
            course("LOW", 3, CourseRole.OPTIONAL, (low_no_lab,), priority=2),
        )
    )
    best = solve_top_k(problem).results[0]
    assert "HIGH" in best.selected_courses
    assert best.metrics.physical_lab_sessions == 1


def test_ranking_policy_does_not_change_feasible_result_identities() -> None:
    option_a = candidate("A", 1, 1, (meeting(1, 0, 480, 530),))
    option_b = candidate("A", 1, 2, (meeting(2, 0, 900, 950),))
    base_courses = (course("A", 1, CourseRole.REQUIRED, (option_a, option_b)),)
    morning = scenario(base_courses, ranking=RankingPolicy(prefer_morning_theory=True))
    evening = scenario(base_courses, ranking=RankingPolicy(prefer_evening_theory=True))
    assert {item.result_id for item in solve_top_k(morning).results} == {
        item.result_id for item in solve_top_k(evening).results
    }
    assert solve_top_k(morning).results[0].result_id != solve_top_k(evening).results[0].result_id


def test_reference_and_optimized_match_deterministic_random_scenarios() -> None:
    generator = random.Random(20261028)
    for case in range(20):
        courses = []
        for index in range(generator.randint(1, 4)):
            options = []
            for option_index in range(generator.randint(1, 2)):
                start = generator.choice((480, 530, 580, 630, 840, 890))
                allocation_id = case * 100 + index * 10 + option_index + 1
                options.append(
                    candidate(
                        f"C{index}",
                        index + 1,
                        allocation_id,
                        (meeting(allocation_id, generator.randrange(3), start, start + 50),),
                    )
                )
            courses.append(
                course(
                    f"C{index}",
                    index + 1,
                    CourseRole.REQUIRED if index == 0 else CourseRole.OPTIONAL,
                    tuple(options),
                    priority=index + 1,
                )
            )
        problem = scenario(tuple(courses), top_k=100)
        reference = reference_solution_identities(problem)
        optimized = solve_top_k(problem)
        assert {item.result_id for item in optimized.results} == reference
        assert count_exact(problem).exact_count == len(reference)


def test_pre_cancelled_search_and_count_never_claim_completion() -> None:
    option = candidate("A", 1, 1, (meeting(1, 0, 480, 530),))
    problem = scenario((course("A", 1, CourseRole.REQUIRED, (option,)),))
    event = threading.Event()
    event.set()
    assert solve_top_k(problem, cancel_event=event).termination is SearchTermination.CANCELLED
    counted = count_exact(problem, cancel_event=event)
    assert counted.status is CountStatus.CANCELLED
    assert counted.exact_count is None


def test_resource_limited_count_is_not_reported_exact() -> None:
    options = tuple(
        candidate("A", 1, index, (meeting(index, index % 5, 480, 530),)) for index in range(1, 20)
    )
    problem = scenario(
        (course("A", 1, CourseRole.REQUIRED, options),),
        max_nodes=5,
    )
    counted = count_exact(problem)
    assert counted.status is CountStatus.RESOURCE_LIMIT
    assert counted.exact_count is None
