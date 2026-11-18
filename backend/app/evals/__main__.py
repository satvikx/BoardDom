"""`uv run python -m app.evals` - run the golden set and store the results.

Uses backend/.env like the API. Without an AI key it runs offline with the demo provider
(numbers then show what the pipeline's checks add, not real model quality).
"""

import sys

from app.ai import build_provider
from app.core.config import Settings
from app.db.session import build_engine, session_factory
from app.evals import run_evals, table
from app.models.entities import EvalRun, utcnow
from app.services import demo_ai
from app.services.usage import make_sink


def main() -> int:
    settings = Settings()
    engine = build_engine(settings.resolved_database_url)
    factory = session_factory(engine)
    provider = build_provider(settings)
    demo_ai.install(provider)
    provider.usage_sink = make_sink(factory)  # eval calls show up on the efficiency page
    with factory() as db:
        run = EvalRun(provider=provider.name)
        db.add(run)
        db.commit()
        print(
            f"Running the golden set with the {provider.name} provider"
            + (" (demo mode)" if getattr(provider, "demo_mode", False) else "")
            + "..."
        )
        try:
            results = run_evals(provider, settings)
        except Exception as exc:  # noqa: BLE001 - report and record the failure
            run.status, run.message, run.finished_at = "failed", type(exc).__name__, utcnow()
            db.commit()
            print(f"Evals failed: {type(exc).__name__}", file=sys.stderr)
            return 1
        run.status, run.results, run.finished_at = "succeeded", results, utcnow()
        db.commit()
    provider.usage_sink.flush()
    print(table(results))
    print(f"Stored as eval run {run.id} ({results['seconds']} s).")
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
