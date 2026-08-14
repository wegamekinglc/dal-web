"""Stateless Curve Lab authoring and capability resources."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.dependencies import gateway_dependency, store_dependency
from app.schemas.curve_lab import (
    CURVE_LAB_V1_SUCCESS_FAMILIES,
    CURVE_LAB_V1_SUCCESS_REGISTRY,
    CurveBuildRunResponse,
    CurveDraftDocumentInputV2,
    CurveDraftResponse,
    CurveImportJobResponse,
    CurveLabCapabilitiesResponse,
    CurveLabErrorResponse,
    CurveLabQuoteCanonicalizationRequest,
    CurveLabQuoteCanonicalizationResponse,
    CurveLabQuoteRenderingRequest,
    CurveLabQuoteRenderingResponse,
    CurveLabRegistryEntryDTO,
    CurveRuntimeManifestV1,
    CurveVersionCreateRequest,
    CurveVersionResponse,
    FixingSnapshotCreateV1,
    FixingSnapshotResponseV1,
    MatrixResultV2,
    RiskRunRequestV2,
    RiskRunResponseV2,
)
from app.services.archive_preflight import ArchiveLimits
from app.services.curve_lab_lifecycle import (
    _version_public,
    archive_version,
    clone_version,
    create_build_run,
    create_draft,
    create_version,
    get_build_run,
    get_draft,
    get_import_job,
    get_version,
    import_native_json,
    list_versions,
    native_payload,
    update_draft,
    version_runtime_manifest,
)
from app.services.curve_risk import (
    create_fixing_snapshot,
    create_risk_run,
    get_fixing_snapshot,
    get_matrix,
    get_risk_run,
)
from app.services.quote_canonicalization import (
    canonicalize_quote,
    render_quote,
)

router = APIRouter(prefix="/api/curve-lab", tags=["curve-lab"])

# ``CurveLabLifecycleError`` and ``QuoteCanonicalizationError`` propagate to the
# app-level exception handlers registered in ``app.main``.


async def _read_bounded_request_body(
    request: Request,
    *,
    wire_bytes: int = ArchiveLimits().wire_bytes,
) -> bytes:
    """Buffer no more than the preflight cap plus one sentinel byte."""

    chunks: list[bytes] = []
    length = 0
    async for chunk in request.stream():
        remaining = wire_bytes + 1 - length
        if remaining <= 0:
            break
        bounded = chunk[:remaining]
        chunks.append(bounded)
        length += len(bounded)
        if length > wire_bytes:
            break
    return b"".join(chunks)


@router.get("/capabilities", response_model=CurveLabCapabilitiesResponse)
async def get_curve_lab_capabilities() -> CurveLabCapabilitiesResponse:
    return CurveLabCapabilitiesResponse(
        success_families=CURVE_LAB_V1_SUCCESS_FAMILIES,
        registry=tuple(
            CurveLabRegistryEntryDTO(
                instrument_type=row.instrument_type,
                quote_coordinate_kind=row.quote_coordinate_kind,
                canonical_raw_unit=row.canonical_raw_unit,
                exact_risk_raw_bump=row.exact_risk_raw_bump,
                normalized_risk_bump=row.normalized_risk_bump,
            )
            for row in CURVE_LAB_V1_SUCCESS_REGISTRY
        ),
    )


@router.post(
    "/quote-canonicalizations",
    response_model=CurveLabQuoteCanonicalizationResponse,
    responses={422: {"model": CurveLabErrorResponse}},
)
async def canonicalize_authoring_quote(
    request: CurveLabQuoteCanonicalizationRequest,
) -> CurveLabQuoteCanonicalizationResponse:
    return canonicalize_quote(
        request.instrument_type,
        request.input_lexeme,
        request.input_convention,
    )


@router.post(
    "/quote-renderings",
    response_model=CurveLabQuoteRenderingResponse,
    responses={422: {"model": CurveLabErrorResponse}},
)
async def render_authoring_quote(
    request: CurveLabQuoteRenderingRequest,
) -> CurveLabQuoteRenderingResponse:
    return CurveLabQuoteRenderingResponse(
        rendered_quote=render_quote(
            request.instrument_type,
            request.canonical_raw_quote,
            request.display_convention,
            request.display_scale,
        )
    )


@router.post("/drafts", response_model=CurveDraftResponse, status_code=201)
async def create_curve_draft(
    request: CurveDraftDocumentInputV2,
    store=Depends(store_dependency),
) -> dict:
    return create_draft(store, request)


@router.get("/drafts/{draft_id}", response_model=CurveDraftResponse)
async def get_curve_draft(draft_id: str, store=Depends(store_dependency)) -> dict:
    return get_draft(store, draft_id)


@router.put("/drafts/{draft_id}", response_model=CurveDraftResponse)
async def update_curve_draft(
    draft_id: str,
    request: CurveDraftDocumentInputV2,
    if_match: Annotated[str, Header(alias="If-Match")],
    store=Depends(store_dependency),
) -> dict:
    try:
        revision = int(if_match.strip().strip('"'))
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "DRAFT_REVISION_INVALID",
                "message": "If-Match must contain one quoted integer revision.",
                "field": "If-Match",
                "value": if_match,
                "resource_id": draft_id,
                "details": {},
            },
        ) from exc
    return update_draft(store, draft_id, revision, request)


@router.post(
    "/drafts/{draft_id}/build-runs",
    response_model=CurveBuildRunResponse,
    status_code=202,
)
async def create_curve_build_run(
    draft_id: str,
    store=Depends(store_dependency),
    gateway=Depends(gateway_dependency),
) -> dict:
    return create_build_run(store, gateway, draft_id)


@router.get("/build-runs/{run_id}", response_model=CurveBuildRunResponse)
async def get_curve_build_run(run_id: str, store=Depends(store_dependency)) -> dict:
    return get_build_run(store, run_id)


@router.post(
    "/versions",
    response_model=CurveVersionResponse,
    responses={201: {"model": CurveVersionResponse}},
)
async def create_curve_version(
    request: CurveVersionCreateRequest,
    response: Response,
    store=Depends(store_dependency),
) -> dict:
    result, created = create_version(store, request)
    response.status_code = 201 if created else 200
    return result


@router.get("/versions", response_model=list[CurveVersionResponse])
async def list_curve_versions(
    include_archived: Annotated[bool, Query()] = False,
    store=Depends(store_dependency),
) -> list[dict]:
    return list_versions(store, include_archived)


@router.get("/versions/{version_id}", response_model=CurveVersionResponse)
async def get_curve_version(version_id: str, store=Depends(store_dependency)) -> dict:
    return _version_public(get_version(store, version_id))


@router.post("/versions/{version_id}/archive", response_model=CurveVersionResponse)
async def archive_curve_version(version_id: str, store=Depends(store_dependency)) -> dict:
    return archive_version(store, version_id)


@router.post(
    "/versions/{version_id}/clone",
    response_model=CurveDraftResponse,
    status_code=201,
)
async def clone_curve_version(version_id: str, store=Depends(store_dependency)) -> dict:
    return clone_version(store, version_id)


@router.get("/versions/{version_id}/native-json")
async def get_curve_version_native_json(
    version_id: str, store=Depends(store_dependency)
) -> Response:
    payload = native_payload(store, version_id)
    return Response(content=payload, media_type="application/json")


@router.get(
    "/versions/{version_id}/runtime-manifest",
    response_model=CurveRuntimeManifestV1,
)
async def get_curve_version_runtime_manifest(
    version_id: str,
    store=Depends(store_dependency),
) -> dict:
    return version_runtime_manifest(store, version_id)


@router.post(
    "/import-jobs",
    response_model=CurveImportJobResponse,
    status_code=202,
)
async def create_curve_import_job(
    request: Request,
    content_encoding: Annotated[str | None, Header(alias="Content-Encoding")] = None,
    runtime_manifest_json: Annotated[
        str | None,
        Header(alias="X-Curve-Lab-Runtime-Manifest"),
    ] = None,
    store=Depends(store_dependency),
    gateway=Depends(gateway_dependency),
) -> dict:
    payload = await _read_bounded_request_body(request)
    try:
        runtime_manifest = (
            CurveRuntimeManifestV1.model_validate_json(runtime_manifest_json)
            if runtime_manifest_json is not None
            else None
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "IMPORT_RUNTIME_MANIFEST_INVALID",
                "message": "Runtime manifest is not a closed CurveRuntimeManifestV1.",
                "field": "X-Curve-Lab-Runtime-Manifest",
                "value": None,
                "resource_id": None,
                "details": {"errors": exc.error_count()},
            },
        ) from exc
    return import_native_json(
        store,
        gateway,
        payload,
        content_encoding,
        runtime_manifest,
    )


@router.get(
    "/import-jobs/{job_id}",
    response_model=CurveImportJobResponse,
)
async def get_curve_import_job(job_id: str, store=Depends(store_dependency)) -> dict:
    return get_import_job(store, job_id)


@router.post(
    "/fixing-snapshots",
    response_model=FixingSnapshotResponseV1,
    status_code=201,
)
async def post_fixing_snapshot(
    request: FixingSnapshotCreateV1,
    store=Depends(store_dependency),
) -> dict:
    return create_fixing_snapshot(store, request)


@router.get(
    "/fixing-snapshots/{snapshot_id}",
    response_model=FixingSnapshotResponseV1,
)
async def read_fixing_snapshot(
    snapshot_id: str,
    store=Depends(store_dependency),
) -> dict:
    return get_fixing_snapshot(store, snapshot_id)


@router.post(
    "/risk-runs",
    response_model=RiskRunResponseV2,
    response_model_exclude_unset=True,
    status_code=202,
)
async def create_curve_risk_run(
    request: RiskRunRequestV2,
    store=Depends(store_dependency),
    gateway=Depends(gateway_dependency),
) -> dict:
    return await asyncio.to_thread(create_risk_run, store, gateway, request)


@router.get(
    "/risk-runs/{run_id}",
    response_model=RiskRunResponseV2,
    response_model_exclude_unset=True,
)
async def get_curve_risk_run(run_id: str, store=Depends(store_dependency)) -> dict:
    return get_risk_run(store, run_id)


@router.get(
    "/risk-runs/{run_id}/matrices/{matrix_id}",
    response_model=MatrixResultV2,
)
async def get_curve_risk_matrix(
    run_id: str,
    matrix_id: str,
    store=Depends(store_dependency),
) -> dict:
    return get_matrix(store, run_id, matrix_id)


async def curve_lab_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Give pre-handler axis overrides the same stable Curve Lab envelope."""

    if request.url.path.startswith("/api/curve-lab/"):
        for error in exc.errors():
            if error["type"] == "quote_axis_override_forbidden":
                field = str(error.get("ctx", {}).get("field", "request"))
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": {
                            "code": "QUOTE_AXIS_OVERRIDE_FORBIDDEN",
                            "message": "Quote-axis values are derived from the family registry.",
                            "field": field,
                            "value": None,
                            "resource_id": None,
                            "details": {"constraint": "server_derived"},
                        }
                    },
                )
            if error["type"] == "draft_topology_invalid":
                field = str(error.get("ctx", {}).get("field", "document"))
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": {
                            "code": "DRAFT_TOPOLOGY_INVALID",
                            "message": error["msg"],
                            "field": field,
                            "value": None,
                            "resource_id": None,
                            "details": {"constraint": "closed_curve_topology"},
                        }
                    },
                )
        first = exc.errors()[0]
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": "REQUEST_VALIDATION_FAILED",
                    "message": first["msg"],
                    "field": ".".join(str(item) for item in first["loc"][1:]),
                    "value": None,
                    "resource_id": None,
                    "details": {"type": first["type"]},
                }
            },
        )
    return await request_validation_exception_handler(request, exc)
