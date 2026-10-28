"""Academic component vocabulary and evidence-scoped pairing rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CurriculumType(StrEnum):
    TH = "TH"
    ETL = "ETL"
    ETP = "ETP"
    LO = "LO"
    ELJ = "ELJ"
    PJ = "PJ"
    SS = "SS"
    UNKNOWN = "unknown"


class AllocationType(StrEnum):
    TH = "TH"
    ETH = "ETH"
    ELA = "ELA"
    EPJ = "EPJ"
    SS = "SS"
    UNKNOWN = "unknown"


class PairingState(StrEnum):
    VERIFIED_ALLOWED = "verified_allowed"
    VERIFIED_FORBIDDEN = "verified_forbidden"
    PROVISIONAL = "provisional"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class ComponentRequirement:
    allocation_type: AllocationType
    required: bool = True


@dataclass(frozen=True, slots=True)
class ComponentTemplate:
    curriculum_type: CurriculumType
    requirements: tuple[ComponentRequirement, ...]
    source: str
    provisional: bool = True


DEFAULT_TEMPLATES: dict[CurriculumType, ComponentTemplate] = {
    CurriculumType.TH: ComponentTemplate(
        CurriculumType.TH,
        (ComponentRequirement(AllocationType.TH),),
        "documented Phase 2 default; explicit ETH may replace TH after review",
    ),
    CurriculumType.ETL: ComponentTemplate(
        CurriculumType.ETL,
        (ComponentRequirement(AllocationType.ETH), ComponentRequirement(AllocationType.ELA)),
        "docs/03_RULES_AND_DECISIONS.md",
    ),
    CurriculumType.ETP: ComponentTemplate(
        CurriculumType.ETP,
        (ComponentRequirement(AllocationType.ETH), ComponentRequirement(AllocationType.EPJ)),
        "docs/03_RULES_AND_DECISIONS.md",
    ),
    CurriculumType.LO: ComponentTemplate(
        CurriculumType.LO,
        (ComponentRequirement(AllocationType.ELA),),
        "documented Phase 2 default; requires catalogue confirmation",
    ),
    CurriculumType.ELJ: ComponentTemplate(
        CurriculumType.ELJ,
        (ComponentRequirement(AllocationType.ELA), ComponentRequirement(AllocationType.EPJ)),
        "documented Phase 2 default; requires catalogue confirmation",
    ),
    CurriculumType.PJ: ComponentTemplate(
        CurriculumType.PJ,
        (ComponentRequirement(AllocationType.EPJ),),
        "documented Phase 2 default; requires catalogue confirmation",
    ),
    CurriculumType.SS: ComponentTemplate(
        CurriculumType.SS,
        (ComponentRequirement(AllocationType.SS),),
        "docs/03_RULES_AND_DECISIONS.md",
    ),
    CurriculumType.UNKNOWN: ComponentTemplate(CurriculumType.UNKNOWN, (), "unknown", True),
}


def allocation_type(raw: str) -> AllocationType:
    try:
        return AllocationType(raw.strip().upper())
    except ValueError:
        return AllocationType.UNKNOWN
