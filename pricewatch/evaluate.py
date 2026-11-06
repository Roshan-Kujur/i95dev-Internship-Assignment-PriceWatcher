# """Eval harness for the LLM extractor.

# Runs the LLM extractor over every snapshot in a directory, compares with labels.json, and
# writes report.json and label_issues.json. The report schema is documented in tasks/ISSUE-3.md.
# """
# from __future__ import annotations

# import json
# import time
# from pathlib import Path

# from .agents.llm_extractor import extract_with_llm
# from .providers import Provider


# def run(provider: Provider, snapshots_dir: str | Path, labels_path: str | Path, out_dir: str | Path) -> dict:
#     snapshots_dir, out_dir = Path(snapshots_dir), Path(out_dir)
#     out_dir.mkdir(parents=True, exist_ok=True)
#     labels = {row["id"]: row for row in json.loads(Path(labels_path).read_text())}

#     results = []
#     t0 = time.time()
#     for snap_id, row in labels.items():
#         html = (snapshots_dir / row["file"]).read_text()
#         obs = extract_with_llm(provider, row["store"], row["url"], html)
#         exp = row["expected"]
#         results.append({"id": snap_id, "price_ok": obs.price_cents == exp["price_cents"]})

#     report = {
#         "provider": provider.name,
#         "n": len(results),
#         "overall": {"price_exact": sum(r["price_ok"] for r in results) / max(1, len(results))},
#         "elapsed_s": round(time.time() - t0, 2),
#     }
#     (out_dir / "report.json").write_text(json.dumps(report, indent=2))
#     (out_dir / "label_issues.json").write_text("[]")
#     return report



# New Evaluation Harness

"""Evaluation harness for the PriceWatch LLM extractor."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path

from .agents.llm_extractor import extract_with_llm, clean_html
from .models import Observation
from .providers import Provider, ProviderError, ProviderTimeout


CACHE_VERSION = "1"


def _load_labels(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))

    # Support either a list of labels or a dictionary of labels.
    if isinstance(data, dict):
        data = list(data.values())

    if not isinstance(data, list):
        raise ValueError("labels.json must contain a list or dictionary")

    return data


def _percentile(values: list[float], percentile: float):
    if not values:
        return None

    values = sorted(values)
    index = max(0, math.ceil(percentile * len(values)) - 1)
    return round(values[index], 2)


def _normalise_currency(value):
    return str(value or "").strip().upper()


def _check_fields(obs: Observation | None, expected: dict) -> dict:
    """Compare the four required fields with the ground truth."""

    if obs is None:
        return {
            "price_exact": False,
            "currency": False,
            "availability": False,
            "pack_size": False,
        }

    return {
        "price_exact": obs.price_cents == expected.get("price_cents"),
        "currency": (
            _normalise_currency(obs.currency)
            == _normalise_currency(expected.get("currency"))
        ),
        "availability": (
            str(obs.availability or "").lower()
            == str(expected.get("availability") or "unknown").lower()
        ),
        "pack_size": (
            obs.pack_size == expected.get("pack_size", 1)
        ),
    }


def _metrics(rows: list[dict]) -> dict:
    count = len(rows)

    result = {"n": count}

    for field in (
        "price_exact",
        "currency",
        "availability",
        "pack_size",
    ):
        correct = sum(row[field] for row in rows)
        result[field] = round(correct / count, 4) if count else 0.0

    return result


def _cache_key(provider, row, html: str) -> str:
    model = getattr(provider, "model", "unknown")
    content = (
        CACHE_VERSION
        + str(provider.name)
        + str(model)
        + str(row["url"])
        + hashlib.sha256(html.encode("utf-8")).hexdigest()
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _estimate_tokens(text: str) -> int:
    """Rough token estimate; actual provider usage is not exposed by the interface."""
    return max(1, math.ceil(len(text) / 4))


def _get_baseline_adapter(store: str, adapters: dict) -> str | None:
    """Find an existing adapter matching a store name."""

    store = str(store).lower()
    candidates = [
        store,
        store.split(".")[0],
    ]

    for candidate in candidates:
        if candidate in adapters:
            return candidate

    return None


def _run_baseline(row: dict, html: str):
    """Run the existing rule-based adapter when one exists."""

    from .agents.extractor import ADAPTERS, extract
    from .http import Client

    adapter_name = _get_baseline_adapter(row["store"], ADAPTERS)

    if adapter_name is None:
        return None

    result = extract(
        Client(),
        row["store"],
        adapter_name,
        row["url"],
        html,
    )

    # Maple can return multiple variant observations.
    if isinstance(result, list):
        return result[0] if result else None

    return result


def run(
    provider: Provider,
    snapshots_dir: str | Path,
    labels_path: str | Path,
    out_dir: str | Path,
) -> dict:

    snapshots_dir = Path(snapshots_dir)
    labels_path = Path(labels_path)
    out_dir = Path(out_dir)

    out_dir.mkdir(parents=True, exist_ok=True)

    labels = _load_labels(labels_path)

    cache_path = out_dir / "cache.json"
    cache = _load_cache(cache_path)

    results = []
    baseline_results = []
    latencies = []

    errors = {
        "timeout": 0,
        "malformed_output": 0,
        "provider_error": 0,
    }

    input_tokens = 0
    output_tokens = 0
    cache_hits = 0

    for row in labels:
        snapshot_id = row["id"]
        expected = row["expected"]
        snapshot_path = snapshots_dir / row["file"]

        obs = None
        latency_ms = 0.0

        try:
            html = snapshot_path.read_text(
                encoding="utf-8",
                errors="replace",
            )

            key = _cache_key(provider, row, html)

            if key in cache:
                cached = cache[key]
                obs = Observation.from_dict(cached["observation"])
                latency_ms = cached.get("latency_ms", 0.0)
                cache_hits += 1

            else:
                start = time.perf_counter()

                obs = extract_with_llm(
                    provider,
                    row["store"],
                    row["url"],
                    html,
                )

                latency_ms = (time.perf_counter() - start) * 1000

                # Estimate usage for this new provider call.
                prompt_text = (
                    f"Source URL: {row['url']}\n"
                    f"Store: {row['store']}\n"
                    f"{clean_html(html)}"
                )

                output_text = json.dumps(
                    obs.to_dict(),
                    ensure_ascii=False,
                )

                in_tokens = _estimate_tokens(prompt_text)
                out_tokens = _estimate_tokens(output_text)

                input_tokens += in_tokens
                output_tokens += out_tokens

                # Cache successful extractions to avoid repeat API calls.
                cache[key] = {
                    "observation": obs.to_dict(),
                    "latency_ms": round(latency_ms, 2),
                    "input_tokens": in_tokens,
                    "output_tokens": out_tokens,
                }
                _save_cache(cache_path, cache)

        except ProviderTimeout:
            errors["timeout"] += 1

        except (ValueError, json.JSONDecodeError, TypeError):
            errors["malformed_output"] += 1

        except Exception:
            errors["provider_error"] += 1

        latencies.append(latency_ms)

        field_results = _check_fields(obs, expected)

        results.append({
            "id": snapshot_id,
            **field_results,
        })

        # Run the rule-based baseline independently.
        try:
            if "html" not in locals():
                html = snapshot_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

            baseline_obs = _run_baseline(row, html)

        except Exception:
            baseline_obs = None

        baseline_results.append({
            "id": snapshot_id,
            "price_exact": (
                baseline_obs is not None
                and baseline_obs.price_cents == expected.get("price_cents")
            ),
        })

        # Avoid reusing a previous snapshot's HTML if the next read fails.
        if "html" in locals():
            del html

    # Overall metrics.
    overall = _metrics(results)

    # Per-store metrics.
    per_store = {}

    for row in labels:
        store = row["store"]

        if store not in per_store:
            per_store[store] = []

        matching = next(
            result for result in results if result["id"] == row["id"]
        )
        per_store[store].append(matching)

    per_store_report = {
        store: _metrics(store_results)
        for store, store_results in per_store.items()
    }

    # Baseline metrics.
    baseline_price_accuracy = (
        sum(row["price_exact"] for row in baseline_results)
        / len(baseline_results)
        if baseline_results else 0.0
    )

    baseline_per_store = {}

    for row in labels:
        store = row["store"]

        if store not in baseline_per_store:
            baseline_per_store[store] = []

        matching = next(
            result for result in baseline_results if result["id"] == row["id"]
        )
        baseline_per_store[store].append(matching["price_exact"])

    baseline_report = {
        "price_exact": round(baseline_price_accuracy, 4),
        "per_store": {
            store: round(
                sum(values) / len(values) if values else 0.0,
                4,
            )
            for store, values in baseline_per_store.items()
        },
    }

    # Cost is calculated only when the user supplies model pricing.
    input_rate = os.getenv("PRICEWATCH_INPUT_USD_PER_1M")
    output_rate = os.getenv("PRICEWATCH_OUTPUT_USD_PER_1M")

    usd_estimate = None

    if input_rate is not None and output_rate is not None:
        usd_estimate = round(
            (input_tokens * float(input_rate)
             + output_tokens * float(output_rate)) / 1_000_000,
            6,
        )

    report = {
        "provider": provider.name,
        "model": getattr(provider, "model", "unknown"),
        "n": len(labels),
        "overall": overall,
        "per_store": per_store_report,
        "errors": errors,
        "cost": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "usd_estimate": usd_estimate,
            "token_counts_are_estimated": True,
        },
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
        },
        "cache_hits": cache_hits,
        "baseline": baseline_report,
    }

    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    # Do not label model disagreements as ground-truth errors automatically.
    # Label issues must be verified against the original product pages.
    (out_dir / "label_issues.json").write_text(
        json.dumps([], indent=2),
        encoding="utf-8",
    )

    return report