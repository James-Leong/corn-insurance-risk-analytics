"""Load only fixed, trusted deployment artifacts, verifying bytes before deserialization."""

import hashlib
import io
import json
from pathlib import Path

from app.repositories.comparison_repository import ComparisonError

RUN_ID = "corn-2026-v1"
METHOD_IDS = ("glm_hurdle", "xgboost_hurdle")


class ModelRepository:
    def __init__(self, root: Path):
        self.root = Path(root)

    def load(self, expected_report_hash: str):
        try:
            directory = self.root / RUN_ID
            if self.root.is_symlink() or directory.is_symlink():
                raise ValueError("Symlink model directory")

            def read(name):
                path = directory / name
                if path.is_symlink() or path.stat().st_size > 20_000_000:
                    raise ValueError("Invalid model file")
                return path.read_bytes()

            manifest_bytes = read("deployment-manifest.json")
            manifest = json.loads(manifest_bytes)
            if (
                manifest["schema_version"] != "model-deployment-v1"
                or manifest["run_id"] != RUN_ID
                or manifest["report_sha256"] != expected_report_hash
                or manifest["release_state"] != "research_only"
            ):
                raise ValueError("Model/report mismatch")
            verified = {}
            for name in (
                "parameters.json",
                "split-manifest.json",
                *(f"{m}.joblib" for m in METHOD_IDS),
            ):
                raw = read(name)
                if hashlib.sha256(raw).hexdigest() != manifest["files"][name]["sha256"]:
                    raise ValueError("Model checksum mismatch")
                verified[name] = raw
            import joblib

            models = {m: joblib.load(io.BytesIO(verified[f"{m}.joblib"])) for m in METHOD_IDS}
            return (
                models,
                manifest,
                json.loads(verified["parameters.json"]),
                json.loads(verified["split-manifest.json"]),
            )
        except Exception as exc:
            raise ComparisonError(
                503, "analysis_model_unavailable", "已保存模型缺失或校验失败，请挂载可信完整模型包"
            ) from exc
