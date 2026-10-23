"""Validated, data-only research reports; never model serialization."""

from typing import Annotated, Literal
import math
from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]


class Document(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)

    @model_validator(mode="after")
    def finite_tree(self):
        def check(value):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Nonfinite number")
            if isinstance(value, dict):
                for child in value.values():
                    check(child)
            if isinstance(value, list):
                for child in value:
                    check(child)

        check(self.model_dump())
        return self


class Metric(Document):
    metric_id: str
    value: float | None
    unit: str
    direction: Literal["lower_is_better", "higher_is_better", "neutral", "closer_to_zero"]
    missing_reason: str | None = None

    @model_validator(mode="after")
    def missing_explained(self):
        if self.value is None and not self.missing_reason:
            raise ValueError("Missing metrics need a reason")
        return self


class Method(Document):
    method_id: Literal[
        "historical_blocks", "glm_hurdle", "xgboost_hurdle", "price_last", "price_ma20"
    ]
    task: Literal["payout_risk", "price_reference"] = "payout_risk"
    model_version: str | None = None
    release_state: Literal["research_only", "eligible_for_pilot", "rejected", "not_evaluated"]
    coverage: float = Field(ge=0, le=1)
    failure_count: int = Field(ge=0)
    metrics: list[Metric]

    @model_validator(mode="after")
    def reference_separate(self):
        if self.method_id.startswith("price_") and self.task != "price_reference":
            raise ValueError("Price reference is a separate task")
        return self


class CaseOutput(Document):
    method_id: str
    claim_probability: float | None = Field(default=None, ge=0, le=1)
    expected_payout: float | None = Field(default=None, ge=0)
    conditional_mean_payout: float | None = Field(default=None, ge=0)
    p90_payout: float | None = Field(default=None, ge=0)
    scenario_payout: float | None = Field(default=None, ge=0)
    p90_status: str = "unsupported"

    @model_validator(mode="after")
    def p90_gate(self):
        if self.p90_payout is not None and self.p90_status != "validated":
            raise ValueError("Unvalidated P90 must be null")
        if self.method_id.startswith("price_") and (
            self.expected_payout is not None or self.claim_probability is not None
        ):
            raise ValueError("Price references cannot claim expected loss or probability")
        return self


class Case(Document):
    case_id: Identifier
    outputs: list[CaseOutput]
    observed_payout: float | None = Field(default=None, ge=0)


class Evidence(Document):
    calibration: list[dict] = Field(default_factory=list, max_length=2000)
    error_slices: list[dict] = Field(default_factory=list, max_length=2000)
    data_quality: list[dict] = Field(default_factory=list, max_length=2000)


class Partition(Document):
    sample_count: int = Field(ge=0)
    date_count: int = Field(ge=0)
    models: list[Method]
    evidence: Evidence = Field(default_factory=Evidence)
    cases: list[Case] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def unique_ids(self):
        for identifiers in ([m.method_id for m in self.models], [c.case_id for c in self.cases]):
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("Duplicate identifier")
        return self


class Selection(Document):
    frozen: bool = False
    selected_method_id: str | None = None
    reason_code: str = "not_evaluated"


class TestReview(Document):
    approved: bool = False


class Bundle(Document):
    schema_version: Literal["comparison-v1"]
    run_id: Identifier
    comparison_group_id: Identifier
    title: str
    created_at: str
    source_kind: Literal["measured", "schema_fixture"]
    label_kind: Literal["rule_generated", "authorized_claim"]
    run_status: Literal["completed", "incomplete", "failed"]
    data_start: Literal["2025-12-31"]
    data_end: Literal["2026-10-23"]
    warnings: list[str]
    protocol: dict
    selection: Selection = Field(default_factory=Selection)
    test_review: TestReview = Field(default_factory=TestReview)
    released_partitions: list[Literal["validation", "test"]]
    partitions: dict[Literal["validation", "test"], Partition]

    @model_validator(mode="after")
    def release_rules(self):
        if any(key not in self.partitions for key in self.released_partitions):
            raise ValueError("Released partition is absent")
        if "test" in self.released_partitions and not (
            self.selection.frozen and self.test_review.approved
        ):
            raise ValueError("Test release requires frozen selection and completed review")
        if self.source_kind == "schema_fixture":
            if self.selection.selected_method_id is not None:
                raise ValueError("Fixtures cannot select a winner")
            for partition in self.partitions.values():
                if partition.cases or any(
                    metric.value is not None
                    for model in partition.models
                    for metric in model.metrics
                ):
                    raise ValueError("Fixtures cannot present measured results")
        return self


class CatalogEntry(Document):
    run_id: Identifier
    comparison_group_id: Identifier
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Catalog(Document):
    schema_version: Literal["comparison-v1"]
    runs: list[CatalogEntry]

    @model_validator(mode="after")
    def unique_runs(self):
        if len({run.run_id for run in self.runs}) != len(self.runs):
            raise ValueError("Duplicate run")
        return self
