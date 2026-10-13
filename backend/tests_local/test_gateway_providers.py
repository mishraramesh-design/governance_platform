import asyncio
import httpx
import gateway


def _patch(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(gateway.httpx, "AsyncClient",
                        lambda **k: real(transport=httpx.MockTransport(handler), **k))


def test_anthropic_and_gemini_calls(monkeypatch):
    seen = {}

    def handler(req):
        seen[req.url.host] = req
        if "anthropic" in req.url.host:
            return httpx.Response(200, json={"content": [{"type": "text", "text": "AGREE ok"}]})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "gem ok"}]}}]})
    _patch(monkeypatch, handler)
    a = asyncio.run(gateway._run_llm("sys", "hi", {"provider": "anthropic", "model": "m"}, "k1", "t"))
    g = asyncio.run(gateway._run_llm("sys", "hi", {"provider": "gemini", "model": "m"}, "k2", "t"))
    assert a == "AGREE ok" and g == "gem ok"
    assert seen["api.anthropic.com"].headers["x-api-key"] == "k1"
    assert seen["generativelanguage.googleapis.com"].headers["x-goog-api-key"] == "k2"


def test_no_key_falls_back_to_zero_llm():
    r = asyncio.run(gateway.complete("requirement_rewrite", "x", "maker", None))
    assert r["mode"] == "zero-llm"
