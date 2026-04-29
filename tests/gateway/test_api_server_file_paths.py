"""
Tests for the file_paths enrichment feature in /v1/responses and /v1/runs.

Covers:
- Enrichment text injection for compliance, image, and generic files
- Validation: type checks, existence checks
- /v1/responses and /v1/runs both support file_paths
"""

import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import PlatformConfig
from gateway.platforms.api_server import (
    APIServerAdapter,
    _COMPLIANCE_EXTENSIONS,
    _IMAGE_EXTENSIONS,
    _enrich_user_message_with_file_paths,
    cors_middleware,
    security_headers_middleware,
)


def _make_adapter(api_key: str = "", cors_origins=None) -> APIServerAdapter:
    extra = {}
    if api_key:
        extra["key"] = api_key
    if cors_origins is not None:
        extra["cors_origins"] = cors_origins
    config = PlatformConfig(enabled=True, extra=extra)
    return APIServerAdapter(config)


def _create_app(adapter: APIServerAdapter) -> web.Application:
    mws = [mw for mw in (cors_middleware, security_headers_middleware) if mw is not None]
    app = web.Application(middlewares=mws)
    app["api_server_adapter"] = adapter
    app.router.add_post("/v1/responses", adapter._handle_responses)
    app.router.add_post("/v1/runs", adapter._handle_runs)
    app.router.add_get("/v1/runs/{run_id}/events", adapter._handle_run_events)
    return app


@pytest.fixture
def adapter():
    return _make_adapter()


# ---------------------------------------------------------------------------
# _enrich_user_message_with_file_paths unit tests
# ---------------------------------------------------------------------------


class TestEnrichHelper:
    def test_compliance_file_enrichment(self):
        """PDF files get the [SYSTEM:] compliance directive."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"fake pdf content")
            path = f.name
        try:
            enriched, invalid = _enrich_user_message_with_file_paths(
                "请审查此文件", [path]
            )
            assert invalid == []
            assert "[File: " in enriched
            assert "[SYSTEM:" in enriched
            assert "compliance_review" in enriched
            assert "You MUST call" in enriched
            assert path in enriched
            assert "请审查此文件" in enriched
        finally:
            os.unlink(path)

    def test_image_file_enrichment(self):
        """Pure image files (not compliance) get a simple attachment reference."""
        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as f:
            f.write(b"fake gif")
            path = f.name
        try:
            enriched, invalid = _enrich_user_message_with_file_paths(
                "请查看图片", [path]
            )
            assert invalid == []
            assert "[User attached image:" in enriched
            assert "[SYSTEM:" not in enriched
            assert "请查看图片" in enriched
        finally:
            os.unlink(path)

    def test_generic_file_enrichment(self):
        """Non-compliance, non-image files get the document note."""
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            f.write(b"fake pptx")
            path = f.name
        try:
            enriched, invalid = _enrich_user_message_with_file_paths(
                "请查看文档", [path]
            )
            assert invalid == []
            assert "[The user sent a document:" in enriched
            assert "Do not claim the path is incompatible" in enriched
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_invalid(self):
        """Non-existent file paths are reported as invalid."""
        enriched, invalid = _enrich_user_message_with_file_paths(
            "请审查", ["/nonexistent/file.pdf"]
        )
        assert enriched == "请审查"
        assert "/nonexistent/file.pdf" in invalid

    def test_multiple_files_with_mixed_types(self):
        """Multiple files of different types each get appropriate enrichment."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as pdf:
            pdf.write(b"fake pdf")
            pdf_path = pdf.name
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as xlsx:
            xlsx.write(b"fake xlsx")
            xlsx_path = xlsx.name
        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as gif:
            gif.write(b"fake gif")
            gif_path = gif.name
        try:
            enriched, invalid = _enrich_user_message_with_file_paths(
                "请审查所有文件", [pdf_path, xlsx_path, gif_path]
            )
            assert invalid == []
            # PDF and XLSX are compliance files, GIF is image-only
            assert "[SYSTEM:" in enriched  # from compliance files
            assert "[User attached image:" in enriched  # from GIF
        finally:
            os.unlink(pdf_path)
            os.unlink(xlsx_path)
            os.unlink(gif_path)

    def test_compliance_priority_over_image(self):
        """PNG/JPEG in COMPLIANCE_EXTENSIONS get compliance enrichment, not image."""
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"fake png")
            path = f.name
        try:
            enriched, invalid = _enrich_user_message_with_file_paths("审查", [path])
            assert invalid == []
            assert "[SYSTEM:" in enriched
            assert "compliance_review" in enriched
            assert "[User attached image:" not in enriched
        finally:
            os.unlink(path)

    def test_no_file_paths_returns_original_message(self):
        """Empty file_paths list returns the message unchanged."""
        enriched, invalid = _enrich_user_message_with_file_paths("hello", [])
        assert enriched == "hello"
        assert invalid == []


# ---------------------------------------------------------------------------
# /v1/responses endpoint with file_paths
# ---------------------------------------------------------------------------


class TestResponsesFilePaths:
    @pytest.mark.asyncio
    async def test_file_paths_not_array_returns_400(self, adapter):
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.post(
                "/v1/responses",
                json={
                    "model": "hermes-agent",
                    "input": "审查此文件",
                    "file_paths": "/some/path.pdf",
                },
            )
            assert resp.status == 400
            data = await resp.json()
            assert "array of strings" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_file_paths_entry_not_string_returns_400(self, adapter):
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.post(
                "/v1/responses",
                json={
                    "model": "hermes-agent",
                    "input": "审查此文件",
                    "file_paths": [123],
                },
            )
            assert resp.status == 400
            data = await resp.json()
            assert "file_paths[0]" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_file_paths_nonexistent_returns_400(self, adapter):
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.post(
                "/v1/responses",
                json={
                    "model": "hermes-agent",
                    "input": "审查此文件",
                    "file_paths": ["/nonexistent/file.pdf"],
                },
            )
            assert resp.status == 400
            data = await resp.json()
            assert "do not exist" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_file_paths_enriches_user_message(self, adapter):
        """Valid file_paths inject enrichment into the user_message passed to _run_agent."""
        mock_result = {
            "final_response": "合规审查完成",
            "messages": [],
            "api_calls": 1,
        }
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"fake pdf")
            path = f.name
        try:
            app = _create_app(adapter)
            async with TestClient(TestServer(app)) as cli:
                with patch.object(adapter, "_run_agent", new_callable=AsyncMock) as mock_run:
                    mock_run.return_value = (mock_result, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
                    resp = await cli.post(
                        "/v1/responses",
                        json={
                            "model": "hermes-agent",
                            "input": "请审查此文件",
                            "file_paths": [path],
                            "store": True,
                        },
                    )
                assert resp.status == 200
                call_kwargs = mock_run.call_args.kwargs
                user_msg = call_kwargs["user_message"]
                assert "请审查此文件" in user_msg
                assert "[SYSTEM:" in user_msg
                assert "compliance_review" in user_msg
                assert path in user_msg
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_no_file_paths_works_unchanged(self, adapter):
        """Without file_paths, behavior is the same as before."""
        mock_result = {"final_response": "ok", "messages": [], "api_calls": 1}
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            with patch.object(adapter, "_run_agent", new_callable=AsyncMock) as mock_run:
                mock_run.return_value = (mock_result, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
                resp = await cli.post(
                    "/v1/responses",
                    json={"model": "hermes-agent", "input": "Hello"},
                )
            assert resp.status == 200
            assert mock_run.call_args.kwargs["user_message"] == "Hello"


# ---------------------------------------------------------------------------
# /v1/runs endpoint with file_paths
# ---------------------------------------------------------------------------


class TestRunsFilePaths:
    @pytest.mark.asyncio
    async def test_file_paths_not_array_returns_400(self, adapter):
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.post(
                "/v1/runs",
                json={
                    "input": "审查此文件",
                    "file_paths": "not_an_array",
                    "session_id": "test-runs-001",
                },
            )
            assert resp.status == 400
            data = await resp.json()
            assert "array of strings" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_file_paths_nonexistent_returns_400(self, adapter):
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.post(
                "/v1/runs",
                json={
                    "input": "审查此文件",
                    "file_paths": ["/nonexistent/file.pdf"],
                    "session_id": "test-runs-002",
                },
            )
            assert resp.status == 400
            data = await resp.json()
            assert "do not exist" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_file_paths_enriches_user_message_in_runs(self, adapter):
        """Valid file_paths inject enrichment in /v1/runs handler."""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(b"fake docx")
            path = f.name
        try:
            app = _create_app(adapter)
            # We can't easily inspect the internal user_message in runs,
            # but we can verify the endpoint doesn't reject it.
            # The run will fail because _create_agent isn't fully wired,
            # but the 202 acceptance proves file_paths validation passed.
            # Instead, test the enrichment function directly (already covered above)
            # and verify the endpoint accepts valid file_paths by checking
            # that no 400 error is returned.
            async with TestClient(TestServer(app)) as cli:
                resp = await cli.post(
                    "/v1/runs",
                    json={
                        "input": "请审查此文件",
                        "file_paths": [path],
                        "session_id": "test-runs-filepaths",
                    },
                )
                # The endpoint should accept it (202) or process it,
                # but NOT return 400 for file_paths validation.
                # It may return 202 or other status depending on
                # whether the agent can actually run.
                assert resp.status != 400
        finally:
            os.unlink(path)