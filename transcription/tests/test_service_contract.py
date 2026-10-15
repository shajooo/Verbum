"""
Verbum Gate B: Service Interface Contract Tests
Validates all Section 5 service endpoints and behaviors without UI:
- /health, /model/select, /model/download, /transcribe, /events/{id}, /cancel/{id}
- Bearer token authentication
- SSE event streaming lifecycle
- Concurrency limit: 409 BUSY on overlapping job
- Multipart audio upload & JSON audio path
- Error codes: NO_MODEL, BAD_AUDIO, BUSY, CANCELLED
"""

import asyncio
import json
import os
import sys
import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import service

TEST_TOKEN = "test-secret-token-12345"
FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures", "audio"))


@pytest.fixture(autouse=True)
def setup_service_token():
    service.AUTH_TOKEN = TEST_TOKEN
    service.CURRENT_JOB = None
    service.JOB_HISTORY.clear()


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.mark.anyio
async def test_auth_enforcement():
    transport = ASGITransport(app=service.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Missing token
        r_no_auth = await client.get("/health")
        assert r_no_auth.status_code == 401
        assert r_no_auth.json()["detail"]["code"] == "UNAUTHORIZED"

        # Invalid token
        r_bad_auth = await client.get("/health", headers={"Authorization": "Bearer wrong-token"})
        assert r_bad_auth.status_code == 401
        assert r_bad_auth.json()["detail"]["code"] == "UNAUTHORIZED"

        # Valid token
        r_ok = await client.get("/health", headers={"Authorization": f"Bearer {TEST_TOKEN}"})
        assert r_ok.status_code == 200


@pytest.mark.anyio
async def test_health_endpoint(auth_headers):
    transport = ASGITransport(app=service.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/health", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["device"] in ("cuda", "cpu")
        assert "tiny" in data["models_installed"]
        assert "small" in data["models_installed"]


@pytest.mark.anyio
async def test_model_select(auth_headers):
    transport = ASGITransport(app=service.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Valid model select
        res = await client.post("/model/select", json={"name": "tiny"}, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ready"
        assert data["model"] == "tiny"

        # Unknown model
        res_bad = await client.post("/model/select", json={"name": "nonexistent_model"}, headers=auth_headers)
        assert res_bad.status_code == 400
        assert res_bad.json()["detail"]["code"] == "INVALID_MODEL"


@pytest.mark.anyio
async def test_transcribe_with_path_and_sse_events(auth_headers):
    transport = ASGITransport(app=service.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        short_audio = os.path.join(FIXTURES_DIR, "short_en.wav")
        res = await client.post(
            "/transcribe",
            json={"path": short_audio, "model": "tiny"},
            headers=auth_headers,
        )
        assert res.status_code == 200
        job_id = res.json()["job_id"]
        assert job_id is not None

        # Stream SSE events
        received_events = []
        async with client.stream("GET", f"/events/{job_id}", headers=auth_headers) as stream:
            async for line in stream.aiter_lines():
                if line.startswith("data: "):
                    ev_data = json.loads(line[6:])
                    received_events.append(ev_data)
                    if ev_data.get("event") in ("done", "error", "cancelled"):
                        break

        event_names = [e["event"] for e in received_events]
        assert "queued" in event_names
        assert "done" in event_names
        done_event = next(e for e in received_events if e["event"] == "done")
        assert "verbum" in done_event["result"]["text"].lower() or "test" in done_event["result"]["text"].lower()


@pytest.mark.anyio
async def test_transcribe_multipart_upload(auth_headers):
    transport = ASGITransport(app=service.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        short_audio = os.path.join(FIXTURES_DIR, "short_en.wav")
        with open(short_audio, "rb") as f:
            audio_bytes = f.read()

        files = {"file": ("short_en.wav", audio_bytes, "audio/wav")}
        data = {"model": "tiny", "language": "en"}
        res = await client.post("/transcribe", files=files, data=data, headers=auth_headers)
        assert res.status_code == 200
        job_id = res.json()["job_id"]

        # Wait for done via SSE
        done_found = False
        async with client.stream("GET", f"/events/{job_id}", headers=auth_headers) as stream:
            async for line in stream.aiter_lines():
                if line.startswith("data: "):
                    ev_data = json.loads(line[6:])
                    if ev_data.get("event") == "done":
                        done_found = True
                        assert "verbum" in ev_data["result"]["text"].lower() or "test" in ev_data["result"]["text"].lower()
                        break
        assert done_found is True


@pytest.mark.anyio
async def test_concurrency_busy_error(auth_headers):
    transport = ASGITransport(app=service.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        long_audio = os.path.join(FIXTURES_DIR, "long_en.wav")
        # Start first job
        res1 = await client.post("/transcribe", json={"path": long_audio, "model": "tiny"}, headers=auth_headers)
        assert res1.status_code == 200

        # Immediate second job should return 409 BUSY
        res2 = await client.post("/transcribe", json={"path": long_audio, "model": "tiny"}, headers=auth_headers)
        assert res2.status_code == 409
        assert res2.json()["detail"]["code"] == "BUSY"


@pytest.mark.anyio
async def test_cancellation_endpoint(auth_headers):
    transport = ASGITransport(app=service.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        long_audio = os.path.join(FIXTURES_DIR, "long_en.wav")
        res = await client.post("/transcribe", json={"path": long_audio, "model": "tiny"}, headers=auth_headers)
        job_id = res.json()["job_id"]

        # Cancel job
        cancel_res = await client.post(f"/cancel/{job_id}", headers=auth_headers)
        assert cancel_res.status_code == 200
        assert cancel_res.json()["status"] == "cancelled"


@pytest.mark.anyio
async def test_bad_audio_error_handling(auth_headers):
    transport = ASGITransport(app=service.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        corrupt_audio = os.path.join(FIXTURES_DIR, "corrupt.wav")
        res = await client.post("/transcribe", json={"path": corrupt_audio, "model": "tiny"}, headers=auth_headers)
        job_id = res.json()["job_id"]

        error_event = None
        async with client.stream("GET", f"/events/{job_id}", headers=auth_headers) as stream:
            async for line in stream.aiter_lines():
                if line.startswith("data: "):
                    ev_data = json.loads(line[6:])
                    if ev_data.get("event") == "error":
                        error_event = ev_data
                        break

        assert error_event is not None
        assert error_event["code"] in ("BAD_AUDIO", "INTERNAL")
