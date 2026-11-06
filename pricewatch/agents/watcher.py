# # """Watcher agent: compares new observations against history and raises alerts.

# # History is a list of observations ordered by `observed_at`. Rules come from alerts.yaml.
# # """
# # from __future__ import annotations

# # from collections import defaultdict
# # from typing import Iterable

# # from ..models import Alert, Observation


# # def _key(o: Observation) -> tuple[str, str]:
# #     return (o.store, o.product_id)


# # def _by_product(history: Iterable[Observation]) -> dict[tuple[str, str], list[Observation]]:
# #     out: dict[tuple[str, str], list[Observation]] = defaultdict(list)
# #     for o in history:
# #         out[_key(o)].append(o)
# #     for v in out.values():
# #         v.sort(key=lambda o: o.observed_at)
# #     return out


# # def rule_drop_pct(prev: Observation, cur: Observation, pct: float) -> Alert | None:
# #     if prev.price_cents is None or cur.price_cents is None:
# #         return None
# #     if cur.price_cents >= prev.price_cents:
# #         return None
# #     drop = (prev.price_cents - cur.price_cents) / prev.price_cents * 100
# #     if drop >= pct:
# #         return Alert(store=cur.store, product_id=cur.product_id, rule="drop_pct",
# #                      message=f"{cur.name or cur.product_id}: {prev.price_cents} -> {cur.price_cents} ({drop:.1f}% drop)",
# #                      previous_cents=prev.price_cents, current_cents=cur.price_cents, observed_at=cur.observed_at)
# #     return None


# # def evaluate(history: list[Observation], new: list[Observation], rules: list[dict]) -> list[Alert]:
# #     """Evaluate `rules` for each observation in `new` against `history` (which must not include `new`)."""
# #     alerts: list[Alert] = []
# #     hist = _by_product(history)
# #     for cur in sorted(new, key=lambda o: o.observed_at):
# #         prior = hist.get(_key(cur), [])
# #         prev = prior[-1] if prior else None
# #         for rule in rules:
# #             if rule.get("type") == "drop_pct" and prev is not None:
# #                 a = rule_drop_pct(prev, cur, float(rule.get("pct", 10)))
# #                 if a:
# #                     alerts.append(a)
# #             # TODO(ISSUE-2): below_median rule
# #         hist[_key(cur)] = prior + [cur]
# #     return alerts


# # ---- Changes -----

# """Watcher agent: compares new observations against history and raises alerts.

# History is a list of observations ordered by `observed_at`. Rules come from alerts.yaml.
# """
# from __future__ import annotations

# from collections import defaultdict
# from typing import Iterable, Optional

# from ..models import Alert, Observation


# def _key(o: Observation) -> tuple[str, str]:
#     return (o.store, o.product_id)


# def _by_product(history: Iterable[Observation]) -> dict[tuple[str, str], list[Observation]]:
#     out: dict[tuple[str, str], list[Observation]] = defaultdict(list)
#     for o in history:
#         out[_key(o)].append(o)
#     for v in out.values():
#         v.sort(key=lambda o: o.observed_at)
#     return out


# def _last_priced(prior: list[Observation]) -> Optional[Observation]:
#     """Latest earlier observation that has a real price (skips failed reads)."""
#     for o in reversed(prior):
#         if o.price_cents is not None:
#             return o
#     return None


# def rule_drop_pct(prev: Observation, cur: Observation, pct: float) -> Alert | None:
#     if prev.price_cents is None or cur.price_cents is None:
#         return None
#     if cur.price_cents >= prev.price_cents:
#         return None
#     drop = (prev.price_cents - cur.price_cents) / prev.price_cents * 100
#     if drop >= pct:
#         return Alert(store=cur.store, product_id=cur.product_id, rule="drop_pct",
#                      message=f"{cur.name or cur.product_id}: {prev.price_cents} -> {cur.price_cents} ({drop:.1f}% drop)",
#                      previous_cents=prev.price_cents, current_cents=cur.price_cents, observed_at=cur.observed_at)
#     return None


# def evaluate(history: list[Observation], new: list[Observation], rules: list[dict]) -> list[Alert]:
#     """Evaluate `rules` for each observation in `new` against `history` (which must not include `new`)."""
#     alerts: list[Alert] = []
#     hist = _by_product(history)
#     for cur in sorted(new, key=lambda o: o.observed_at):
#         prior = hist.get(_key(cur), [])
#         prev = _last_priced(prior)  # last real price; None the first time we see a product

#         comparable = prev is not None
#         if comparable and cur.price_cents is not None and prev.currency != cur.currency:
#             # Never compare cents across currencies; flag it and start a new baseline.
#             cur.notes.append(f"currency changed {prev.currency} -> {cur.currency}; not compared")
#             comparable = False

#         for rule in rules:
#             if rule.get("type") == "drop_pct" and comparable:
#                 a = rule_drop_pct(prev, cur, float(rule.get("pct", 10)))
#                 if a:
#                     alerts.append(a)
#             # TODO(ISSUE-2): below_median rule
#         hist[_key(cur)] = prior + [cur]
#     return alerts

# Remodified Watcher Module -



"""Watcher agent: compares new observations against history and raises alerts."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Iterable, Optional

from ..models import Alert, Observation


def _key(o: Observation) -> tuple[str, str]:
    return (o.store, o.product_id)


def _parse_time(value: str) -> datetime:
    """Parse ISO timestamps and normalize them to UTC."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _by_product(history: Iterable[Observation]) -> dict[tuple[str, str], list[Observation]]:
    out: dict[tuple[str, str], list[Observation]] = defaultdict(list)

    for o in history:
        out[_key(o)].append(o)

    for observations in out.values():
        observations.sort(key=lambda o: _parse_time(o.observed_at))

    return out


def _last_priced(prior: list[Observation]) -> Optional[Observation]:
    """Latest earlier observation that has a real price."""
    for o in reversed(prior):
        if o.price_cents is not None:
            return o
    return None


def _add_note(cur: Observation, note: str) -> None:
    if note not in cur.notes:
        cur.notes.append(note)


def rule_drop_pct(prev: Observation, cur: Observation, pct: float) -> Alert | None:
    if prev.price_cents is None or cur.price_cents is None:
        return None

    if cur.price_cents >= prev.price_cents:
        return None

    drop = (prev.price_cents - cur.price_cents) / prev.price_cents * 100

    if drop >= pct:
        return Alert(
            store=cur.store,
            product_id=cur.product_id,
            rule="drop_pct",
            message=f"{cur.name or cur.product_id}: {prev.price_cents} -> {cur.price_cents} ({drop:.1f}% drop)",
            previous_cents=prev.price_cents,
            current_cents=cur.price_cents,
            observed_at=cur.observed_at,
        )

    return None


def rule_below_median(
    prior: list[Observation],
    cur: Observation,
    pct: float,
    window_days: int,
) -> Alert | None:
    """Compare current price against all valid prior observations in a time window."""

    if cur.price_cents is None:
        return None

    current_time = _parse_time(cur.observed_at)
    window_start = current_time - timedelta(days=window_days)

    # Only observations inside the trailing window and strictly before current.
    window = [
        o for o in prior
        if o.price_cents is not None
        and window_start <= _parse_time(o.observed_at) < current_time
    ]

    # Do not compare prices across different currencies.
    currencies = {o.currency for o in window}
    if window and (len(currencies) > 1 or cur.currency not in currencies):
        previous_currencies = ", ".join(sorted(currencies))
        _add_note(
            cur,
            f"currency changed within {window_days}-day window "
            f"({previous_currencies} -> {cur.currency}); not compared",
        )
        return None

    # Require at least three valid historical observations.
    if len(window) < 3:
        return None

    historical_median = median(o.price_cents for o in window)

    threshold = historical_median * (1 - pct / 100)

    if cur.price_cents <= threshold:
        median_cents = int(round(historical_median))

        return Alert(
            store=cur.store,
            product_id=cur.product_id,
            rule="below_median",
            message=(
                f"{cur.name or cur.product_id}: current price "
                f"{cur.price_cents} is {pct}% or more below "
                f"historical median {median_cents}"
            ),
            previous_cents=median_cents,
            current_cents=cur.price_cents,
            observed_at=cur.observed_at,
        )

    return None


def evaluate(
    history: list[Observation],
    new: list[Observation],
    rules: list[dict],
) -> list[Alert]:
    """Evaluate alert rules, returning at most one alert per product."""

    hist = _by_product(history)
    selected_alerts: dict[tuple[str, str], Alert] = {}

    for cur in sorted(new, key=lambda o: _parse_time(o.observed_at)):
        key = _key(cur)
        prior = hist.get(key, [])

        prev = _last_priced(prior)

        comparable = prev is not None

        if comparable and cur.price_cents is not None and prev.currency != cur.currency:
            _add_note(
                cur,
                f"currency changed {prev.currency} -> {cur.currency}; not compared",
            )
            comparable = False

        drop_alert = None
        median_alert = None

        for rule in rules:
            rule_type = rule.get("type")

            if rule_type == "drop_pct" and comparable:
                drop_alert = rule_drop_pct(
                    prev, cur, float(rule.get("pct", 10))
                )

            elif rule_type == "below_median":
                median_alert = rule_below_median(
                    prior,
                    cur,
                    float(rule.get("pct", 15)),
                    int(rule.get("window_days", 30)),
                )

        # below_median always wins over drop_pct.
        candidate = median_alert or drop_alert

        if candidate:
            existing = selected_alerts.get(key)

            if existing is None or (
                candidate.rule == "below_median"
                and existing.rule != "below_median"
            ):
                selected_alerts[key] = candidate

        # Include this observation for subsequent observations.
        hist[key] = prior + [cur]

    return list(selected_alerts.values())
