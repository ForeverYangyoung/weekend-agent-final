from fastapi.testclient import TestClient

from backend.server import app


def test_health() -> None:
    c = TestClient(app)
    r = c.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data.get("stream") == "/v1/agent/stream"
    assert data.get("confirm") == "/v1/agent/confirm"
    assert data.get("replan") == "/v1/agent/replan"


def test_root_serves_frontend_or_build_hint() -> None:
    c = TestClient(app)
    r = c.get("/")
    if r.status_code == 200:
        assert "text/html" in r.headers.get("content-type", "")
    else:
        assert r.status_code == 503
        assert "npm" in r.text


def test_stream_agent_sse_awaiting_confirm() -> None:
    c = TestClient(app)
    for url in ("/v1/agent/stream", "/agent/stream"):
        buf = ""
        with c.stream(
            "POST",
            url,
            json={"user_input": "下午两个人随便逛逛"},
        ) as resp:
            assert resp.status_code == 200
            for chunk in resp.iter_text():
                buf += chunk
        assert "event" in buf
        assert "awaiting_confirm" in buf
        assert '"event": "done"' in buf or '"event":"done"' in buf
