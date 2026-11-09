import base64
import json
import struct
import zlib
from types import SimpleNamespace
from typing import Any

import pytest

from app.market import ai


def png(w: int = 400, h: int = 200) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return ai.PNG_MAGIC + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_decode_png_accepts_valid_and_data_url() -> None:
    img = png()
    assert ai.decode_png(b64(img)) == img
    assert ai.decode_png("data:image/png;base64," + b64(img)) == img


@pytest.mark.parametrize(
    ("data", "msg"),
    [
        ("not base64!!", "invalid base64"),
        (b64(b"GIF89a" + b"\x00" * 64), "not a PNG"),
        (b64(png(100, 50)), "outside"),
        (b64(png(3000, 200)), "outside"),
        ("A" * (ai.MAX_PNG_BYTES * 2), "too large"),
    ],
)
def test_decode_png_rejects(data: str, msg: str) -> None:
    with pytest.raises(ai.ImageError, match=msg):
        ai.decode_png(data)


def test_costs() -> None:
    assert ai.cost_usd("claude-opus-5-5", 1_000_000, 0) == 4.0
    assert ai.cost_usd("claude-opus-5-5", 0, 1_000_000) == 20.0
    assert ai.cost_usd("claude-sonnet-5-5", 10_000, 2_000) == pytest.approx(0.04)
    assert ai.cost_usd("claude-opus-5-5", 0, 0, cache_read=1_000_000) == pytest.approx(0.2)
    assert ai.cost_usd("unknown-model", 1_000_000, 0) == 5.0  # conservative
    assert ai.reservation_usd("claude-opus-5-5") == pytest.approx((16000 * 4 + 24000 * 20) / 1e6)
    assert ai.reservation_usd("claude-sonnet-5-5") < ai.reservation_usd("claude-opus-5-5")


def test_output_schema_matches_pydantic_model() -> None:
    assert set(ai.OUTPUT_SCHEMA["required"]) == set(ai.AnalysisResult.model_fields)
    assert ai.OUTPUT_SCHEMA["additionalProperties"] is False
    ai.AnalysisResult.model_validate(ai.FIXTURE_RESULT)
    with pytest.raises(ValueError):
        ai.AnalysisResult.model_validate({**ai.FIXTURE_RESULT, "extra": 1})


class _Stream:
    def __init__(self, msg: Any, calls: list[dict[str, Any]], kwargs: dict[str, Any]) -> None:
        self._msg, self._calls, self._kwargs = msg, calls, kwargs

    async def __aenter__(self) -> "_Stream":
        self._calls.append(self._kwargs)
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_final_message(self) -> Any:
        return self._msg


def _analyzer(msg: Any) -> tuple[ai.AnthropicAnalyzer, list[dict[str, Any]]]:
    a = ai.AnthropicAnalyzer("sk-ant-test-key")
    calls: list[dict[str, Any]] = []
    a._client = SimpleNamespace(  # type: ignore[assignment]
        beta=SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: _Stream(msg, calls, kw)))
    )
    return a, calls


def _msg(stop: str = "end_turn", text: str | None = None, model: str = "claude-opus-5-5") -> Any:
    content = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    usage = SimpleNamespace(
        input_tokens=10_000, output_tokens=2_000, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )
    details = SimpleNamespace(category="cyber") if stop == "refusal" else None
    return SimpleNamespace(
        id="msg_1", model=model, stop_reason=stop, stop_details=details, content=content, usage=usage
    )


async def test_analyzer_success_request_shape_and_cost() -> None:
    a, calls = _analyzer(_msg(text=json.dumps(ai.FIXTURE_RESULT)))
    res = await a.analyze(png(), {"instrument": {"symbol": "NVDA"}}, "claude-opus-5-5")
    assert res.status == "ok" and res.result and res.result["confidence"] == "medium"
    assert res.cost("claude-opus-5-5") == pytest.approx((10_000 * 4 + 2_000 * 20) / 1e6)
    kw = calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"]["effort"] == "high" and kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["fallbacks"] == "default" and kw["betas"] == [ai.FALLBACK_BETA]
    blocks = kw["messages"][0]["content"]
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/png"
    assert '"NVDA"' in blocks[1]["text"]


async def test_analyzer_refusal_max_tokens_invalid_and_fallback_pricing() -> None:
    a, _ = _analyzer(_msg(stop="refusal"))
    res = await a.analyze(png(), {"instrument": {}}, "claude-opus-5-5")
    assert res.status == "refused" and "cyber" in (res.error or "") and res.input_tokens == 10_000
    a, _ = _analyzer(_msg(stop="max_tokens", text='{"summary": "abgeschn'))
    assert (await a.analyze(png(), {"instrument": {}}, "claude-opus-5-5")).status == "error"
    a, _ = _analyzer(_msg(text='{"summary": "x"}'))
    res = await a.analyze(png(), {"instrument": {}}, "claude-opus-5-5")
    assert res.status == "error" and "ungültig" in (res.error or "")
    a, _ = _analyzer(_msg(text=json.dumps(ai.FIXTURE_RESULT), model="claude-opus-4-8"))  # served by fallback
    res = await a.analyze(png(), {"instrument": {}}, "claude-opus-5-5")
    assert res.model_served == "claude-opus-4-8"
    assert res.cost("claude-opus-5-5") == pytest.approx((10_000 * 5 + 2_000 * 25) / 1e6)


async def test_build_analyzer() -> None:
    assert isinstance(ai.build_analyzer("fixture", ""), ai.FixtureAnalyzer)
    assert not ai.build_analyzer("live", "").configured
    res = await ai.FixtureAnalyzer().analyze(png(), {"instrument": {"id": 1}}, "claude-sonnet-5-5")
    assert res.status == "ok" and res.cost("claude-sonnet-5-5") > 0
