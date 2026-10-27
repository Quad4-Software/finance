from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_clock import app_today
from app.core.database import get_async_session
from app.core.rate_limit import document_rate_limit
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.schemas.document import DocumentGenerateRequest
from app.services import document_render, document_service
from app.services.document_service import PLAN_SECTIONS, REPORT_SECTIONS

router = APIRouter(prefix="/api/documents", tags=["documents"])

# Same floor as reports.py: the fiscal year starts in April only for Indian
# workspaces.
def _financial_year_start_month(tax_jurisdiction: str | None) -> int:
    return 4 if (tax_jurisdiction or "").upper() == "IN" else 1


def _check_sections(request: DocumentGenerateRequest, allowed: tuple[str, ...]) -> None:
    """The sections allowlist rejects unknown keys rather than ignoring them.

    A silently dropped key would produce a document missing a section the
    caller asked for, which is worse than a clear 422.
    """
    if request.sections is None:
        return
    unknown = [key for key in request.sections if key not in allowed]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown sections: {', '.join(unknown)}. Allowed: {', '.join(allowed)}",
        )
    if not request.sections:
        raise HTTPException(
            status_code=422,
            detail="Select at least one section",
        )


def _as_download(document, fmt: str) -> StreamingResponse:
    """Render the assembled document in the requested format and stream it."""
    if fmt == "html":
        payload = document_render.render_html(document).encode("utf-8")
        media_type = "text/html"
        extension = "html"
    else:
        payload = document_render.render_pdf(document)
        media_type = "application/pdf"
        extension = "pdf"
    filename = f"quad4-{document.kind}-{app_today().strftime('%Y%m')}.{extension}"
    return StreamingResponse(
        iter([payload]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/report", dependencies=[Depends(document_rate_limit)])
async def generate_report(
    body: DocumentGenerateRequest,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """A styled financial report for the chosen period, as PDF or HTML.

    A POST that writes nothing: the request has to be a body because the
    section allowlist and title fields do not belong in a query string.
    """
    _check_sections(body, REPORT_SECTIONS)
    try:
        document = await document_service.build_report_document(
            session, ctx.workspace, ctx.user_id, body,
            financial_year_start_month=_financial_year_start_month(
                ctx.workspace.tax_jurisdiction
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _as_download(document, body.format)


@router.post("/plan", dependencies=[Depends(document_rate_limit)])
async def generate_plan(
    body: DocumentGenerateRequest,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """A forward-looking financial plan: goals, budgets, forecast, savings.

    Every projection in the document is labelled an estimate; the plan never
    states an outcome as certain.
    """
    _check_sections(body, PLAN_SECTIONS)
    try:
        document = await document_service.build_plan_document(
            session, ctx.workspace, ctx.user_id, body,
            financial_year_start_month=_financial_year_start_month(
                ctx.workspace.tax_jurisdiction
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _as_download(document, body.format)
