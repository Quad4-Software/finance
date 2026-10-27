"""Downloadable documents: both formats, section allowlist, validation, auth.

The income/expenses service aggregates with PostgreSQL ``to_char``; the
SQLite test engine gets the same minimal UDF registered in
test_report_service_coverage.py.
"""

import re
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.transaction import Transaction

from tests.conftest import engine as _test_engine

pytestmark = pytest.mark.asyncio


def _py_to_char(value, fmt):
    """Minimal emulation of PostgreSQL to_char(date, fmt) for report buckets."""
    if value is None:
        return None
    s = str(value)[:10]
    y, m, d = s.split("-")
    if fmt == "YYYY-MM-DD":
        return f"{y}-{m}-{d}"
    if fmt == "YYYY-MM":
        return f"{y}-{m}"
    if fmt == "YYYY":
        return y
    return s


@event.listens_for(_test_engine.sync_engine, "connect")
def _register_to_char(dbapi_connection, _connection_record):
    dbapi_connection.create_function("to_char", 2, _py_to_char)


@pytest.fixture(autouse=True)
async def _ensure_to_char(session: AsyncSession):
    """The StaticPool reuses one connection, so register on the live handle."""
    raw = await session.connection()

    def _do(sync_conn):
        dbapi = sync_conn.connection.dbapi_connection
        dbapi.create_function("to_char", 2, _py_to_char)

    await raw.run_sync(_do)
    yield


async def test_report_requires_auth(client: AsyncClient):
    response = await client.post("/api/documents/report", json={})
    assert response.status_code == 401


async def test_plan_requires_auth(client: AsyncClient):
    response = await client.post("/api/documents/plan", json={})
    assert response.status_code == 401


async def test_report_pdf(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/documents/report", json={"format": "pdf"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    disposition = response.headers["content-disposition"]
    assert re.fullmatch(
        r'attachment; filename="quad4-report-\d{6}\.pdf"', disposition
    )
    assert response.content[:5] == b"%PDF-"
    assert len(response.content) > 1000


async def test_report_html(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/documents/report", json={"format": "html"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    disposition = response.headers["content-disposition"]
    assert 'filename="quad4-report-' in disposition
    assert disposition.endswith('.html"')
    text = response.text
    assert "<html" in text
    assert "<style>" in text
    assert "Financial report" in text


async def test_plan_pdf(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/documents/plan", json={"format": "pdf"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.content[:5] == b"%PDF-"
    assert 'filename="quad4-plan-' in response.headers["content-disposition"]


async def test_plan_html(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/documents/plan", json={"format": "html"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert "<html" in response.text
    assert "Financial plan" in response.text


async def test_report_with_data(
    client: AsyncClient,
    auth_headers,
    test_account: Account,
    test_transactions: list[Transaction],
):
    """A workspace with transactions still produces a valid document."""
    for fmt, header in (("pdf", b"%PDF-"), ("html", b"<!DOCTYPE html>")):
        response = await client.post(
            "/api/documents/report",
            json={"format": fmt, "period": "last_quarter"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.content[:len(header)] == header
        assert len(response.content) > 1000


async def test_section_allowlist(client: AsyncClient, auth_headers):
    """Only the requested sections are rendered."""
    response = await client.post(
        "/api/documents/report",
        json={"format": "html", "sections": ["net_worth"]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    text = response.text
    assert "NET WORTH" in text
    assert "INCOME VS EXPENSES" not in text
    assert "RECURRING OBLIGATIONS" not in text


async def test_unknown_section_rejected(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/documents/report",
        json={"sections": ["net_worth", "bogus_section"]},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "bogus_section" in response.json()["detail"]


async def test_plan_sections_are_not_report_sections(
    client: AsyncClient, auth_headers
):
    """Each document type owns its section set."""
    response = await client.post(
        "/api/documents/plan",
        json={"sections": ["net_worth"]},
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_empty_section_list_rejected(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/documents/report", json={"sections": []}, headers=auth_headers
    )
    assert response.status_code == 422


async def test_custom_period(client: AsyncClient, auth_headers):
    today = date.today()
    start = today.replace(day=1)
    response = await client.post(
        "/api/documents/report",
        json={
            "format": "html",
            "period": "custom",
            "start_date": start.isoformat(),
            "end_date": today.isoformat(),
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert f"{start.isoformat()} to {today.isoformat()}" in response.text


async def test_custom_period_requires_dates(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/documents/report", json={"period": "custom"}, headers=auth_headers
    )
    assert response.status_code == 422


async def test_custom_period_rejects_inverted_range(
    client: AsyncClient, auth_headers
):
    today = date.today()
    start = today.replace(day=1)
    response = await client.post(
        "/api/documents/report",
        json={
            "period": "custom",
            "start_date": today.isoformat(),
            "end_date": start.isoformat(),
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


async def test_title_and_subtitle_override(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/documents/plan",
        json={"format": "html", "title": "House fund plan", "subtitle": "For us"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert "House fund plan" in response.text
    assert "For us" in response.text


async def test_bad_format_rejected(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/documents/report", json={"format": "docx"}, headers=auth_headers
    )
    assert response.status_code == 422


async def test_viewer_can_generate(
    client: AsyncClient, viewer_auth_headers, test_workspace
):
    """A read-only role still exports what it can read."""
    response = await client.post(
        "/api/documents/report", json={}, headers=viewer_auth_headers
    )
    assert response.status_code == 200
    assert response.content[:5] == b"%PDF-"
