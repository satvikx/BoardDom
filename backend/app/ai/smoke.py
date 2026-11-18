"""Live check of the AI wiring: `uv run python -m app.ai.smoke [--models] [--web]`.

Reads backend/.env (BOARDOM_OPENAI_API_KEY, BOARDOM_OPENAI_BASE_URL, model names), makes a few
tiny calls and reports each capability separately, so you can see what your gateway supports.
"""

import sys

from app.ai import AIError, build_provider
from app.core.config import Settings


def check(label, call):
    try:
        print(f"{label:<9} OK   {call()}")
    except AIError as exc:
        print(f"{label:<9} FAIL [{exc.code}] {exc.message}")
    except Exception as exc:  # noqa: BLE001 - diagnostic script: show the type, never the body
        print(f"{label:<9} FAIL {type(exc).__name__}")


def main() -> int:
    settings = Settings()
    provider = build_provider(settings)
    if provider.demo_mode:
        print("No BOARDOM_OPENAI_API_KEY in backend/.env: nothing live to test.")
        return 1
    endpoint = settings.openai_base_url or "api.openai.com"
    print(f"endpoint: {endpoint}  tls_verify={settings.ai_verify_tls}")
    if "--models" in sys.argv:
        check("models", lambda: ", ".join(m.id for m in provider.client.models.list().data))

    def text():
        r = provider.text("Reply in one short sentence.", "Hiii Broo", purpose="smoke", fast=True)
        return f"{r.usage.model}  {r.usage.latency_ms} ms  {r.text.strip()[:60]!r}"

    check("text", text)
    check("embed", lambda: f"dims={len(provider.embed(['hello'], purpose='smoke')[0])}")
    check("moderate", lambda: f"flagged={provider.moderate('hello').flagged}")
    if "--web" in sys.argv:

        def web():
            found = provider.web_search("latest Python version", purpose="smoke")
            return f"sources={len(found.sources)}"

        check("web", web)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
