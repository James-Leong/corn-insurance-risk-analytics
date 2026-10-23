"""Append-only immutable bundles with an atomically replaced catalog."""

import hashlib
import json
import os
import re
from pathlib import Path
from research.export import encode


def publish(bundle: dict, output: Path) -> Path:
    from app.domain.comparison import Bundle, Catalog

    # JSON normalization also rejects NaN before the API schema is checked.
    Bundle.model_validate(json.loads(encode(bundle)))
    run_id = bundle["run_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id):
        raise ValueError("Invalid run ID")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "runs" / run_id
    if destination.exists():
        raise ValueError("Existing runs are immutable; choose a new run ID")
    data = encode(bundle)
    if len(data) > 10_000_000:
        raise ValueError("Bundle exceeds API size limit")
    catalog_path = output / "catalog.json"
    catalog = (
        json.loads(catalog_path.read_text())
        if catalog_path.exists()
        else {"schema_version": "comparison-v1", "runs": []}
    )
    catalog["runs"].append(
        {
            "run_id": run_id,
            "comparison_group_id": bundle["comparison_group_id"],
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    )
    Catalog.model_validate(catalog)
    destination.mkdir(parents=True)
    (destination / "bundle.json").write_bytes(data)
    temporary = output / ".catalog.tmp"
    temporary.write_bytes(encode(catalog))
    os.replace(temporary, catalog_path)
    return destination / "bundle.json"
