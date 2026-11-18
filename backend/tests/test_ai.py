from types import SimpleNamespace

import httpx
import openai
import pytest
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, register
from pydantic import BaseModel
from test_accounts import login, make_student, make_teacher, new_client

from app.ai import AIError, build_provider
from app.ai.base import Usage, price
from app.ai.fake_provider import DIMENSIONS, FakeProvider
from app.ai.openai_provider import OpenAIProvider
from app.core.config import Settings

# Isolated from backend/.env and the shell: no real key or gateway leaks into tests.
OFFLINE = dict(_env_file=None, openai_api_key=None, openai_base_url=None, ai_verify_tls=True)


def settings(**kw):
    return Settings(**(OFFLINE | {"environment": "test"} | kw))


def production(**kw):
    # Production also refuses the default admin password/PIN, so set real-looking ones.
    return Settings(
        **(
            OFFLINE
            | {
                "environment": "production",
                "admin_password": "a-strong-secret",
                "admin_reset_pin": "913372",
            }
            | kw
        )
    )


def stub_client(**parts):
    return SimpleNamespace(**parts)


def response(text="ok", cached=40):
    return SimpleNamespace(
        output_text=text,
        output_parsed=None,
        output=[],
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            input_tokens_details=SimpleNamespace(cached_tokens=cached),
        ),
    )


def api_error(cls, status=429):
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    if cls is openai.APIConnectionError:
        return cls(request=request)
    if cls is openai.APITimeoutError:
        return cls(request=request)
    return cls(
        "secret provider body sk-LEAK", response=httpx.Response(status, request=request), body=None
    )


class Plan(BaseModel):
    title: str


# ---- endpoints -------------------------------------------------------------------------


def test_ai_endpoints_require_login(client):
    assert client.get("/api/v1/ai/status").status_code == 401
    assert client.post("/api/v1/ai/ping").status_code == 401


def test_ai_endpoints_are_for_teachers_and_admins_only(client, app):
    assert login(client, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    admin = client
    teacher, _ = make_teacher(admin, app)
    student, _ = make_student(teacher, app)
    for user in (admin, teacher):
        assert user.get("/api/v1/ai/status").status_code == 200
        assert user.post("/api/v1/ai/ping").status_code == 200
    for result in (student.get("/api/v1/ai/status"), student.post("/api/v1/ai/ping")):
        assert result.status_code == 403
        assert result.json()["detail"] == (
            "Not allowed: this area is only for teachers and administrators."
        )
    anonymous = new_client(app)
    assert anonymous.get("/api/v1/ai/status").status_code == 401
    assert anonymous.post("/api/v1/ai/ping").status_code == 401


def test_temporary_password_users_cannot_use_ai(client, app):
    assert login(client, ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    created = client.post(
        "/api/v1/admin/teachers", json={"display_name": "New", "email": "new@example.com"}
    ).json()
    fresh = new_client(app)
    assert login(fresh, "new@example.com", created["temporary_password"]).status_code == 200
    assert fresh.get("/api/v1/ai/status").status_code == 403


def test_status_and_ping_run_offline_in_demo_mode(signed_in):
    status = signed_in.get("/api/v1/ai/status").json()
    assert status["provider"] == "fake" and status["demo_mode"] is True
    ping = signed_in.post("/api/v1/ai/ping")
    assert ping.status_code == 200 and ping.json()["reply"].startswith("[demo]")


def test_ai_error_becomes_friendly_response(app, signed_in):
    class Broken(FakeProvider):
        def text(self, *a, **k):
            raise AIError("ai_busy", "The AI service is busy. Please retry shortly.", 503)

    app.state.ai = Broken()
    response_ = signed_in.post("/api/v1/ai/ping")
    assert response_.status_code == 503
    assert response_.json() == {"detail": "The AI service is busy. Please retry shortly."}


# ---- factory ---------------------------------------------------------------------------


def test_factory_picks_provider():
    assert build_provider(settings()).demo_mode is True
    assert build_provider(settings(ai_provider="fake")).demo_mode is False
    live = build_provider(settings(openai_api_key="sk-test"))
    assert isinstance(live, OpenAIProvider)


def test_production_requires_key():
    with pytest.raises(RuntimeError, match="BOARDOM_OPENAI_API_KEY is required"):
        build_provider(production())


def test_blank_key_in_env_file_means_demo_mode(tmp_path):
    env = tmp_path / ".env"
    env.write_text("BOARDOM_OPENAI_API_KEY=\nBOARDOM_OPENAI_BASE_URL=\n", encoding="utf-8")
    loaded = Settings(_env_file=env, environment="test")
    assert loaded.openai_api_key is None and loaded.openai_base_url is None
    assert build_provider(loaded).demo_mode is True


def test_api_key_is_never_shown_in_settings_repr():
    assert "sk-secret" not in repr(settings(openai_api_key="sk-secret"))


# ---- fake provider ---------------------------------------------------------------------


def test_fake_embeddings_are_deterministic_unit_vectors():
    fake = FakeProvider()
    a, b = fake.embed(["arrays", "arrays"], purpose="t")
    assert a == b and len(a) == DIMENSIONS
    assert abs(sum(v * v for v in a) - 1) < 1e-9
    assert fake.embed(["trees"], purpose="t")[0] != a


def test_fake_structured_and_moderation():
    fake = FakeProvider()
    with pytest.raises(AIError):
        fake.structured("i", "p", Plan, purpose="t")
    fake.structured_responses["Plan"] = {"title": "Unit 1"}
    parsed, _ = fake.structured("i", "p", Plan, purpose="t")
    assert parsed.title == "Unit 1"
    assert fake.moderate("hello").flagged is False
    assert fake.moderate("bad [flag]").flagged is True


# ---- OpenAI provider with a stubbed SDK (no network) -----------------------------------


def test_text_maps_usage_and_cost_and_feeds_sink():
    seen = []
    client = stub_client(responses=SimpleNamespace(create=lambda **kw: response("hi")))
    provider = OpenAIProvider(settings(openai_api_key="sk-test"), client=client)
    provider.usage_sink = seen.append
    result = provider.text("sys", "q", purpose="unit", fast=True)
    assert result.text == "hi"
    usage = result.usage
    assert (usage.model, usage.input_tokens, usage.cached_tokens) == ("gpt-6-luna", 100, 40)
    # (60*0.10 + 40*0.01 + 20*0.50) / 1e6
    assert usage.cost_usd == pytest.approx(16.4e-6)
    assert seen == [usage]


def test_unknown_model_has_no_cost():
    assert price({}, Usage("t", "mystery", input_tokens=5)) is None


def test_structured_refusal_is_an_ai_error():
    client = stub_client(responses=SimpleNamespace(parse=lambda **kw: response()))
    provider = OpenAIProvider(settings(openai_api_key="sk-test"), client=client)
    with pytest.raises(AIError) as raised:
        provider.structured("i", "p", Plan, purpose="t")
    assert raised.value.code == "ai_refused"


def test_embed_batches_requests():
    calls = []

    def create(model, input):
        calls.append(len(input))
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2]) for _ in input])

    provider = OpenAIProvider(
        settings(openai_api_key="sk-test"),
        client=stub_client(embeddings=SimpleNamespace(create=create)),
    )
    vectors = provider.embed(["x"] * 300, purpose="t")
    assert len(vectors) == 300 and calls == [128, 128, 44]


@pytest.mark.parametrize(
    ("exc", "code", "status"),
    [
        (api_error(openai.RateLimitError), "ai_busy", 503),
        (api_error(openai.AuthenticationError, 401), "ai_auth", 500),
        (api_error(openai.APIConnectionError), "ai_unreachable", 503),
        (api_error(openai.APITimeoutError), "ai_timeout", 504),
    ],
)
def test_sdk_errors_are_translated_without_leaking_details(exc, code, status):
    def boom(**kw):
        raise exc

    provider = OpenAIProvider(
        settings(openai_api_key="sk-test"),
        client=stub_client(responses=SimpleNamespace(create=boom)),
    )
    with pytest.raises(AIError) as raised:
        provider.text("s", "p", purpose="t")
    assert (raised.value.code, raised.value.status) == (code, status)
    assert "LEAK" not in raised.value.message and "sk-" not in raised.value.message


def test_web_search_sends_domain_filter_and_collects_citations():
    sent = {}
    note = SimpleNamespace(type="url_citation", url="https://nptel.ac.in/x", title="NPTEL")
    message = SimpleNamespace(type="message", content=[SimpleNamespace(annotations=[note, note])])

    def create(**kw):
        sent.update(kw)
        reply = response("found it")
        reply.output = [SimpleNamespace(type="web_search_call"), message]
        return reply

    provider = OpenAIProvider(
        settings(openai_api_key="sk-test"),
        client=stub_client(responses=SimpleNamespace(create=create)),
    )
    result = provider.web_search("dsa syllabus", purpose="t", allowed_domains=["nptel.ac.in"])
    assert sent["tools"] == [
        {"type": "web_search", "filters": {"allowed_domains": ["nptel.ac.in"]}}
    ]
    assert [s.url for s in result.sources] == ["https://nptel.ac.in/x"]  # de-duplicated


def test_register_helper_still_importable():
    assert register  # keeps the shared helper import honest


# ---- gateway settings (base URL, TLS, flags) ---------------------------------------------


def test_gateway_base_url_and_tls_off(monkeypatch):
    made = {}

    class Spy(httpx.Client):
        def __init__(self, **kw):
            made.update(kw)
            super().__init__(**kw)

    monkeypatch.setattr(httpx, "Client", Spy)
    provider = build_provider(
        settings(
            openai_api_key="sk-test",
            openai_base_url="https://genailab.tcs.in/",
            ai_verify_tls=False,
        )
    )
    assert str(provider.client.base_url) == "https://genailab.tcs.in/"
    assert made == {"verify": False}


def test_tls_verification_is_on_by_default_and_blocked_off_in_production(monkeypatch):
    class Forbidden(httpx.Client):
        def __init__(self, **kw):
            pytest.fail("custom http client created")

    monkeypatch.setattr(httpx, "Client", Forbidden)
    build_provider(settings(openai_api_key="sk-test"))
    with pytest.raises(RuntimeError, match="AI_VERIFY_TLS=false is not allowed"):
        build_provider(production(openai_api_key="sk-test", ai_verify_tls=False))


def test_gateway_calls_omit_openai_only_flags():
    sent = []
    client = stub_client(
        responses=SimpleNamespace(create=lambda **kw: sent.append(kw) or response())
    )
    gateway = OpenAIProvider(
        settings(openai_api_key="k", openai_base_url="https://genailab.tcs.in/"), client=client
    )
    gateway.text("s", "p", purpose="t")
    openai_direct = OpenAIProvider(settings(openai_api_key="k"), client=client)
    openai_direct.text("s", "p", purpose="t", max_output_tokens=16)
    assert "store" not in sent[0] and "max_output_tokens" not in sent[0]
    assert sent[1]["store"] is False and sent[1]["max_output_tokens"] == 16
