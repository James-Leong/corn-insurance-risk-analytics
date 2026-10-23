import csv
import io
from app.domain.comparison import Bundle
from app.repositories.comparison_repository import ComparisonError, ComparisonRepository


def released(bundle: Bundle, partition: str) -> bool:
    return partition in bundle.released_partitions and (
        partition != "test" or (bundle.selection.frozen and bundle.test_review.approved)
    )


def metadata(bundle: Bundle) -> dict:
    # Explicit allowlist: unrestricted metadata extensions must not leak sealed test scores.
    keys = (
        "schema_version",
        "run_id",
        "comparison_group_id",
        "title",
        "created_at",
        "source_kind",
        "label_kind",
        "run_status",
        "data_start",
        "data_end",
        "warnings",
    )
    dumped = bundle.model_dump()
    result = {key: dumped[key] for key in keys}
    result["protocol"] = {
        key: bundle.protocol[key]
        for key in (
            "task",
            "window_trading_days",
            "data_version",
            "rule_version",
            "split_version",
            "sample_hash",
            "price_field",
            "contract_ids",
            "lookback_trading_days",
            "feature_schema_version",
            "weighting",
            "seed",
            "terms",
            "parameters",
        )
        if key in bundle.protocol
    }
    result["selection"] = bundle.selection.model_dump(
        include={"frozen", "selected_method_id", "reason_code"}
    )
    result["test_review"] = {"approved": bundle.test_review.approved}
    result["released_partitions"] = [p for p in bundle.released_partitions if released(bundle, p)]
    return result


class ComparisonService:
    def __init__(self, repository: ComparisonRepository):
        self.repository = repository

    def groups(self):
        groups = {}
        for bundle in self.repository.all():
            group = groups.setdefault(
                bundle.comparison_group_id,
                {
                    "comparison_group_id": bundle.comparison_group_id,
                    "title": bundle.title,
                    "run_count": 0,
                },
            )
            group["run_count"] += 1
        return {
            "schema_version": "comparison-v1",
            "data_mode": self.repository.data_mode,
            "items": list(groups.values()),
            "default_group_id": next(iter(groups), None),
            "empty_reason": None if groups else "no_published_results",
        }

    def runs(self, group_id):
        items = [
            metadata(bundle)
            for bundle in self.repository.all()
            if bundle.comparison_group_id == group_id
        ]
        if not items:
            raise ComparisonError(404, "comparison_not_found", "未找到比较组")
        return {"items": items}

    def bundle(self, run_id, partition):
        bundle = self.repository.get(run_id)
        if not released(bundle, partition):
            raise ComparisonError(409, "partition_not_released", "该评估分区尚未获准发布")
        return bundle

    def metrics(self, bundle, partition):
        sample = bundle.partitions[partition]
        return {
            "schema_version": bundle.schema_version,
            "run_id": bundle.run_id,
            "comparison_group_id": bundle.comparison_group_id,
            "source_kind": bundle.source_kind,
            "label_kind": bundle.label_kind,
            "partition": partition,
            "selection": metadata(bundle)["selection"],
            "sample_count": sample.sample_count,
            "date_count": sample.date_count,
            "models": [model.model_dump() for model in sample.models],
        }

    def export(self, bundle, partition, format):
        payload = {
            "metadata": metadata(bundle),
            "partition": partition,
            "metrics": self.metrics(bundle, partition),
            "evidence": bundle.partitions[partition].evidence.model_dump(),
            "cases": [case.model_dump() for case in bundle.partitions[partition].cases],
        }
        if format == "json":
            return payload
        stream = io.StringIO(newline="")
        fields = [
            "run_id",
            "comparison_group_id",
            "source_kind",
            "label_kind",
            "partition",
            "data_start",
            "data_end",
            "warnings",
            "method_id",
            "release_state",
            "coverage",
            "metric_id",
            "value",
            "unit",
            "direction",
            "missing_reason",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()

        def safe(value):
            # Keep exported text from becoming spreadsheet formulas.
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
                return "'" + value
            return value

        for model in bundle.partitions[partition].models:
            for metric in model.metrics:
                row = {
                    key: getattr(bundle, key)
                    for key in (
                        "run_id",
                        "comparison_group_id",
                        "source_kind",
                        "label_kind",
                        "data_start",
                        "data_end",
                    )
                }
                row.update(
                    partition=partition,
                    warnings="; ".join(bundle.warnings),
                    method_id=model.method_id,
                    release_state=model.release_state,
                    coverage=model.coverage,
                )
                row.update(
                    metric.model_dump(
                        include={"metric_id", "value", "unit", "direction", "missing_reason"}
                    )
                )
                writer.writerow({key: safe(value) for key, value in row.items()})
        return stream.getvalue()
