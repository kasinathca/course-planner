"""Semester, offering, allocation, and provenance query routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ffcs_studio.services.catalog_service import CatalogService
from ffcs_studio.web.api_models import ItemsResponse, PaginatedResponse

router = APIRouter(prefix="/api/v1", tags=["courses"])


@router.get("/semesters", response_model=ItemsResponse)
async def semesters(request: Request) -> ItemsResponse:
    catalog: CatalogService = request.app.state.catalog_service
    return ItemsResponse(items=catalog.semesters())


@router.get("/offerings", response_model=PaginatedResponse)
async def offerings(
    request: Request,
    campus: str | None = Query(None, min_length=1, max_length=100),
    semester_label: str | None = Query(None, min_length=1, max_length=200),
    search: str | None = Query(None, min_length=1, max_length=200),
    category: str | None = Query(None, min_length=1, max_length=50),
    component: str | None = Query(None, min_length=1, max_length=50),
    page: int = Query(1, ge=1, le=1_000_000),
    page_size: int = Query(25, ge=1, le=100),
) -> PaginatedResponse:
    catalog: CatalogService = request.app.state.catalog_service
    result = catalog.offerings(
        campus=campus,
        semester_label=semester_label,
        search=search,
        category=category,
        component=component,
        page=page,
        page_size=page_size,
    )
    return PaginatedResponse(**result)


@router.get("/offerings/{offering_id}", response_model=None)
async def offering(offering_id: int, request: Request) -> dict[str, object] | JSONResponse:
    catalog: CatalogService = request.app.state.catalog_service
    result = catalog.offering(offering_id)
    if result is None:
        return _not_found()
    return {"api_version": "1.0", **result}


@router.get("/offerings/{offering_id}/allocations", response_model=None)
async def allocations(offering_id: int, request: Request) -> ItemsResponse | JSONResponse:
    catalog: CatalogService = request.app.state.catalog_service
    result = catalog.allocations(offering_id)
    if result is None:
        return _not_found()
    return ItemsResponse(items=result)


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "offering_not_found", "message": "Offering was not found"}},
    )
