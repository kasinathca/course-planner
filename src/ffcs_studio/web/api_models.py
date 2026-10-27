"""Versioned HTTP request and response contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IssueResponse(BaseModel):
    level: str
    code: str
    path: str
    message: str


class ValidationResponse(BaseModel):
    api_version: str = "1.0"
    valid: bool
    validation_id: str
    expires_at: str
    source_format: str
    filename: str
    campus: str
    semester_label: str
    course_count: int
    allocation_count: int
    issues: list[IssueResponse]


class PreviewRequest(BaseModel):
    validation_id: str = Field(min_length=20, max_length=200)


class PreviewResponse(BaseModel):
    api_version: str = "1.0"
    preview_id: str
    expires_at: str
    filename: str
    campus: str
    semester_label: str
    course_count: int
    allocation_count: int
    issues: list[IssueResponse]
    reconciliation: dict[str, Any]


class CommitRequest(BaseModel):
    preview_id: str = Field(min_length=20, max_length=200)


class CommitResponse(BaseModel):
    api_version: str = "1.0"
    status: str
    import_id: str
    data_revision: int
    course_count: int
    allocation_count: int
    backup_created: bool


class PaginatedResponse(BaseModel):
    api_version: str = "1.0"
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int


class ItemsResponse(BaseModel):
    api_version: str = "1.0"
    items: list[dict[str, Any]]
