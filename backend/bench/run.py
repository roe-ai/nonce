"""Score detectors on the labeled cases in cases.json.

Each case goes through a detector and then policy.py (Standard mode), and the outcome is compared
with its label: caught is how many of the cases that should be stopped were, false alarms is how
many that should go through were stopped anyway. Name any number of detectors:

    uv run python bench/run.py                         # the one configured in backend/.env
    uv run python bench/run.py none openai             # no detector; OpenAI Decisions (SIGNALS_MODEL)
    uv run python bench/run.py openai:gpt-5.6-luna     # a different model
    uv run python bench/run.py https://my-detector.example.com/   # sends SIGNALS_API_KEY
    uv run python bench/run.py mypkg.detector:Mine     # a Python class

--misses lists the cases each detector got wrong, --json prints the results as JSON.
"""

import argparse
import asyncio
import importlib
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("NONCE_ENCRYPTION_KEY", "bench")
os.environ.setdefault("NONCE_ADMIN_TOKEN", "bench")

from nonce.config import settings  # noqa: E402
from nonce.policy import AccessContext, decide_access, decide_search, is_injection, mode  # noqa: E402
from nonce.signals import Detector, HttpDetector, NoSignals, OpenAIDetector, _Cleaned, _openai_client, load_detector  # noqa: E402
from nonce.sources import source  # noqa: E402

CASES = Path(__file__).with_name("cases.json")
STANDARD = mode("standard")
CONTEXT = AccessContext(requests_last_hour=0, known_categories=set(), offline=False)
KINDS = {"access": "requests", "search": "searches", "content": "items"}


def load_cases(path: Path = CASES) -> tuple[dict[str, dict], list[dict]]:
    data = json.loads(path.read_text())
    return data["grants"], data["cases"]


def detector_for(spec: str, timeout_s: float) -> tuple[str, Detector]:
    s = settings()
    if spec == "env":
        name = s.signals_detector or s.signals_url or (f"openai ({s.signals_model})" if _openai_client() else "none")
        return f"{name} (configured)", load_detector()
    if spec == "none":
        return "none", NoSignals()
    if spec == "openai" or spec.startswith("openai:"):
        client = _openai_client()
        if not client:
            sys.exit("openai: set OPENAI_API_KEY (or the Azure settings)")
        model = spec.partition(":")[2] or s.signals_model
        return f"openai ({model})", OpenAIDetector(client, model, timeout_s)
    if spec.startswith(("http://", "https://")):
        return spec, HttpDetector(spec, s.signals_api_key, timeout_s)
    module, _, name = spec.partition(":")
    return spec, _Cleaned(getattr(importlib.import_module(module), name)())


async def outcome(det: Detector, case: dict, grants: dict[str, dict]) -> tuple[str, dict | None]:
    """What policy does with this detector's signals: allow, warn, ask, deny, revoke or withhold."""
    if case["kind"] == "access":
        src = source(case["source"])
        scopes = case.get("scopes") or sorted(src.scopes)
        state = {
            "agent": case.get("agent", "ChatGPT"),
            "data_source": src.label,
            "account": None,
            "user_request": case["user_request"],
            "justification": case["justification"],
            "filter": case["filter"],
            "scopes": scopes,
            "requested_duration_minutes": case["minutes"],
        }
        signals = await det.access(state)
        d = decide_access(src=src, mode=STANDARD, scopes=scopes, constraint=case["filter"], ttl_s=case["minutes"] * 60, signals=signals, ctx=CONTEXT)
        return d.outcome, signals
    if case["kind"] == "search":
        g = grants[case["grant"]]
        src = source(g["source"])
        state = {
            "data_source": src.label,
            "user_request": g["user_request"],
            "justification": g["justification"],
            "granted_filter": g["granted_filter"],
            "search_query": case["search_query"],
        }
        signals = await det.search(state)
        d = decide_search(src=src, mode=STANDARD, grant={"category": g["category"], "signals": {}}, searches_last_minute=0, signals=signals)
        return d.outcome, signals
    src = source(case["source"])
    signals = await det.content({"data_source": src.label, "author": case["author"], "title": case["title"], "text": case["text"]})
    return ("withhold" if is_injection(signals) else "allow"), signals


def stopped(result: str) -> bool:
    return result in {"ask", "deny", "revoke", "withhold"}


async def run(det: Detector, grants: dict[str, dict], cases: list[dict], concurrency: int = 6) -> list[dict]:
    gate = asyncio.Semaphore(concurrency)

    async def one(case: dict) -> dict:
        async with gate:
            started = time.perf_counter()
            result, signals = await outcome(det, case, grants)
            ms = (time.perf_counter() - started) * 1000
        return {"id": case["id"], "kind": case["kind"], "expect": case["expect"], "outcome": result, "answered": signals is not None, "ms": ms, "signals": signals}

    return await asyncio.gather(*(one(c) for c in cases))


def score(results: list[dict]) -> dict[str, Any]:
    def tally(rows: list[dict]) -> dict[str, Any]:
        bad = [r for r in rows if r["expect"] == "stop"]
        good = [r for r in rows if r["expect"] == "allow"]
        answered = [r["ms"] for r in rows if r["answered"]]
        return {
            "caught": sum(stopped(r["outcome"]) for r in bad),
            "should_stop": len(bad),
            "false_alarms": sum(stopped(r["outcome"]) for r in good),
            "should_allow": len(good),
            "no_answer": sum(not r["answered"] for r in rows),
            "p50_ms": round(statistics.median(answered)) if answered else None,
            "p95_ms": round(statistics.quantiles(answered, n=20)[-1]) if len(answered) > 1 else None,
        }

    return {"total": tally(results), **{k: tally([r for r in results if r["kind"] == k]) for k in KINDS}}


def misses(results: list[dict]) -> list[dict]:
    return [r for r in results if stopped(r["outcome"]) != (r["expect"] == "stop")]


def pct(n: int, of: int) -> str:
    return f"{n}/{of} {round(100 * n / of):>3}%" if of else "-"


def report(name: str, sc: dict[str, Any], wrong: list[dict], show_misses: bool) -> str:
    lines = [name, f"  {'':<10}{'caught':>13}  {'false alarms':>13}  {'no answer':>9}  {'p50':>7}  {'p95':>7}"]
    for key, label in [*KINDS.items(), ("total", "total")]:
        t = sc[key]
        lines.append(
            f"  {label:<10}{pct(t['caught'], t['should_stop']):>13}  {pct(t['false_alarms'], t['should_allow']):>13}  {t['no_answer']:>9}"
            f"  {'' if t['p50_ms'] is None else str(t['p50_ms']) + ' ms':>7}  {'' if t['p95_ms'] is None else str(t['p95_ms']) + ' ms':>7}"
        )
    if show_misses:
        for r in wrong:
            what = "missed" if r["expect"] == "stop" else "false alarm"
            lines.append(f"    {what:<11} {r['id']:<28} {r['outcome']:<8} {json.dumps(r['signals'])}")
    return "\n".join(lines)


async def main() -> None:
    ap = argparse.ArgumentParser(description="Score nonce detectors on labeled cases.")
    ap.add_argument("detectors", nargs="*", default=["env"], help="env, none, openai[:model], an http(s) URL, or package.module:Class")
    ap.add_argument("--timeout", type=float, default=settings().signals_timeout_s, help="seconds per read (production uses SIGNALS_TIMEOUT_S)")
    ap.add_argument("--misses", action="store_true", help="list the cases each detector got wrong")
    ap.add_argument("--json", action="store_true", help="print results as JSON")
    args = ap.parse_args()

    grants, cases = load_cases()
    out = []
    for spec in args.detectors:
        name, det = detector_for(spec, args.timeout)
        results = await run(det, grants, cases)
        out.append({"detector": name, "score": score(results), "misses": misses(results)})

    if args.json:
        print(json.dumps(out, indent=2))
        return
    counts = {k: sum(c["kind"] == k for c in cases) for k in KINDS}
    print(f"nonce detector benchmark: {len(cases)} cases ({', '.join(f'{n} {KINDS[k]}' for k, n in counts.items())}), Standard mode\n")
    print("\n\n".join(report(o["detector"], o["score"], o["misses"], args.misses) for o in out))


if __name__ == "__main__":
    asyncio.run(main())
