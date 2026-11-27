"""Voice input: the recording goes to Groq (faked here) and only text comes back."""
import io
import json
import threading
import urllib.error
import urllib.request

import pytest

from app.api.stdlib_server import serve
from app.core.rate_limit import RateLimiter
from app.database.repositories import Store
from app.services import speech_service
from app.services.trip_service import ApiError, PlannerService

ENV = {"GROQ_API_KEY": "secret-test-key"}
AUDIO = b"\x1aE\xdf\xa3" + b"0" * 4000


def heard(text, status=200, calls=None):
    def transport(url, headers, body, timeout):
        if calls is not None:
            calls.append((url, headers, body))
        return status, {"text": text}
    return transport


def test_a_recording_is_sent_to_groq_whisper():
    calls = []
    text = speech_service.transcribe(AUDIO, "audio/webm;codecs=opus", env=ENV, transport=heard(" Three days ", calls=calls))
    url, headers, body = calls[0]
    assert text == "Three days" and url == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert headers["Authorization"] == "Bearer secret-test-key" and "multipart/form-data" in headers["Content-Type"]
    assert b'filename="speech.webm"' in body and b"whisper-large-v3-turbo" in body and AUDIO in body


@pytest.mark.parametrize("audio,kind,env,status", [
    (AUDIO, "audio/webm", {}, 503), (AUDIO, "text/plain", ENV, 415), (b"x" * 10, "audio/webm", ENV, 422),
    (b"x" * (speech_service.MAX_AUDIO_BYTES + 1), "audio/webm", ENV, 413),
])
def test_unusable_recordings_are_not_sent(audio, kind, env, status):
    with pytest.raises(speech_service.SpeechError) as e:
        speech_service.transcribe(audio, kind, env=env, transport=lambda *a: pytest.fail("must not be sent"))
    assert e.value.status == status


@pytest.mark.parametrize("provider,ours", [(401, 503), (429, 429), (500, 502), (400, 502)])
def test_provider_errors_are_explained_without_the_key(provider, ours):
    with pytest.raises(speech_service.SpeechError) as e:
        speech_service.transcribe(AUDIO, "audio/webm", env=ENV, transport=heard("", status=provider))
    assert e.value.status == ours and "secret" not in e.value.message


@pytest.mark.parametrize("status,code,says,never", [
    (401, "invalid_api_key", "API key (error 401)", "blocked"),
    (403, "model_permission_blocked_org", "organization settings. Allow it at https://console.groq.com/settings/limits ", "API key"),
    (403, "model_permission_blocked_project", "https://console.groq.com/settings/project/limits ", "API key"),
    (403, None, "refused the voice request (error 403)", "API key"),
])
def test_a_refusal_says_what_was_refused_and_logs_groqs_reason(status, code, says, never, caplog):
    def transport(*a):
        return status, {"error": {"code": code, "message": "Groq says no to secret-test-key"}}
    with pytest.raises(speech_service.SpeechError) as e:
        speech_service.transcribe(AUDIO, "audio/webm", env=ENV, transport=transport)
    assert says in e.value.message and never not in e.value.message and "secret" not in e.value.message
    assert f"HTTP {status}" in caplog.text and "Groq says no to ***" in caplog.text and "secret" not in caplog.text


@pytest.mark.parametrize("body,reason", [
    (b'{"error": {"code": "model_permission_blocked_project", "message": "blocked"}}', "blocked"),
    (b"<html><body><h1>Access denied</h1></body></html>", "Access denied"),
])
def test_the_real_transport_keeps_the_error_answer(body, reason, monkeypatch):
    def refuse(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(body))
    monkeypatch.setattr(speech_service.urllib.request, "urlopen", refuse)
    status, data = speech_service.default_transport("https://example.invalid", {}, b"", 1)
    assert status == 403 and data["error"]["message"] == reason


def test_silence_and_network_failure():
    def broken(*a):
        raise OSError("down")
    for transport, status in ((heard("   "), 422), (broken, 502)):
        with pytest.raises(speech_service.SpeechError) as e:
            speech_service.transcribe(AUDIO, "audio/mp4", env=ENV, transport=transport)
        assert e.value.status == status


def test_the_daily_limit_stops_further_calls():
    store, env, calls = Store(":memory:"), {**ENV, "VOICE_DAILY_LIMIT": "2"}, []
    for _ in range(2):
        speech_service.transcribe(AUDIO, "audio/webm", env=env, store=store, transport=heard("hi", calls=calls))
    with pytest.raises(speech_service.SpeechError) as e:
        speech_service.transcribe(AUDIO, "audio/webm", env=env, store=store, transport=heard("hi", calls=calls))
    assert e.value.status == 429 and len(calls) == 2


def test_spoken_secrets_are_discarded(make):
    service = PlannerService(make(env=ENV))
    service.speech_transport = heard("my card is 4111 1111 1111 1111")
    with pytest.raises(ApiError) as e:
        service.transcribe(AUDIO, "audio/webm")
    assert e.value.status == 422 and "4111" not in e.value.message


def test_voice_has_its_own_rate_limit_and_health_says_if_it_works(make):
    service = PlannerService(make(env=ENV), limiter=RateLimiter({"voice": [(1, 60)]}))
    service.speech_transport = heard("hello")
    assert service.transcribe(AUDIO, "audio/webm") == {"text": "hello"}
    with pytest.raises(ApiError) as e:
        service.transcribe(AUDIO, "audio/webm")
    assert e.value.status == 429 and service.health()["voice_input"] is True
    assert PlannerService(make()).health()["voice_input"] is False


def test_both_routes_work_over_http(make):
    service = PlannerService(make(env=ENV))
    service.speech_transport = heard("show day 2")
    server = serve(service, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/api/v1"

    def post(path, data, kind):
        request = urllib.request.Request(base + path, data=data, headers={"Content-Type": kind}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    try:
        assert post("/transcribe", AUDIO, "audio/webm") == (200, {"text": "show day 2"})
        status, body = post("/chat", json.dumps({"message": "hi"}).encode(), "application/json")
        assert status == 200 and "plan a trip" in body["reply"]
        assert post("/chat", b"{}", "application/json")[0] == 422
    finally:
        server.shutdown()


def test_both_routes_work_in_fastapi(make):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from app.main import create_app
    service = PlannerService(make(env=ENV))
    service.speech_transport = heard("show day 2")
    web = TestClient(create_app(service))
    said = web.post("/api/v1/transcribe", content=AUDIO, headers={"Content-Type": "audio/webm"})
    assert (said.status_code, said.json()) == (200, {"text": "show day 2"})
    assert "plan a trip" in web.post("/api/v1/chat", json={"message": "hi"}).json()["reply"]
    too_big = web.post("/api/v1/transcribe", content=b"x" * (speech_service.MAX_AUDIO_BYTES + 1),
                       headers={"Content-Type": "audio/webm"})
    assert too_big.status_code == 413 and "under a minute" in too_big.json()["error"]
