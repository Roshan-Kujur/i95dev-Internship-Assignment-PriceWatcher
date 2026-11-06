import json
import hashlib
from pathlib import Path

labels = json.loads(
    Path("eval/labels.json").read_text(encoding="utf-8")
)

cache = json.loads(
    Path("eval/out/cache.json").read_text(encoding="utf-8")
)

if isinstance(labels, dict):
    labels = list(labels.values())

for row in labels:
    html = (Path("eval/snapshots") / row["file"]).read_text(
        encoding="utf-8",
        errors="replace"
    )

    content = (
        "1"
        + "openai"
        + "gpt-4o-mini"
        + row["url"]
        + hashlib.sha256(html.encode("utf-8")).hexdigest()
    )

    key = hashlib.sha256(content.encode("utf-8")).hexdigest()

    if key not in cache:
        print("CACHE MISSING:", row["id"])
        continue

    actual = cache[key]["observation"]
    expected = row["expected"]

    if actual.get("price_cents") != expected.get("price_cents"):
        print("\nID:", row["id"])
        print("STORE:", row["store"])
        print("PRODUCT:", actual.get("name"))
        print("EXPECTED PRICE:", expected.get("price_cents"))
        print("ACTUAL PRICE:", actual.get("price_cents"))
        print("CURRENCY:", actual.get("currency"))