"""Read-only course, semester, allocation, and import history service."""

from __future__ import annotations

from ffcs_studio.persistence.repositories import PaginatedResult, Repository


class CatalogService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def list_imports(self, *, page: int, page_size: int) -> PaginatedResult:
        return self.repository.list_imports(page=page, page_size=page_size)

    def import_detail(self, import_id: str) -> dict[str, object] | None:
        return self.repository.import_detail(import_id)

    def import_diff(self, import_id: str) -> list[dict[str, object]] | None:
        return self.repository.import_diff(import_id)

    def semesters(self) -> list[dict[str, object]]:
        return self.repository.semesters()

    def offerings(
        self,
        *,
        campus: str | None,
        semester_label: str | None,
        search: str | None,
        category: str | None,
        component: str | None,
        page: int,
        page_size: int,
    ) -> PaginatedResult:
        return self.repository.list_offerings(
            campus=campus,
            semester_label=semester_label,
            search=search,
            category=category,
            component=component,
            page=page,
            page_size=page_size,
        )

    def offering(self, offering_id: int) -> dict[str, object] | None:
        return self.repository.offering_detail(offering_id)

    def allocations(self, offering_id: int) -> list[dict[str, object]] | None:
        return self.repository.offering_allocations(offering_id)
