"""Only immutable, hash-verified catalog entries may be served."""

import hashlib
import logging
from pathlib import Path
from app.domain.comparison import Bundle, Catalog

logger = logging.getLogger(__name__)


class ComparisonError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


class ComparisonRepository:
    def __init__(self, root: Path, data_mode: str = "measured"):
        self.root = Path(root).absolute()
        self.data_mode = data_mode

    def _read(self, path: Path) -> bytes:
        relative = path.relative_to(self.root)
        current = self.root
        for part in ("", *relative.parts):
            current = current / part
            if current.is_symlink():
                raise ValueError("Symlink report paths are not supported")
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("Report path escapes store")
        if path.stat().st_size > 10_000_000:
            raise ValueError("Report too large")
        return path.read_bytes()

    def all(self) -> list[Bundle]:
        try:
            catalog_path = self.root / "catalog.json"
            if not catalog_path.exists() and not catalog_path.is_symlink():
                return []
            catalog = Catalog.model_validate_json(self._read(catalog_path))
            result = []
            for entry in catalog.runs:
                raw = self._read(self.root / "runs" / entry.run_id / "bundle.json")
                if hashlib.sha256(raw).hexdigest() != entry.sha256:
                    raise ValueError("Report hash mismatch")
                bundle = Bundle.model_validate_json(raw)
                if (bundle.run_id, bundle.comparison_group_id) != (
                    entry.run_id,
                    entry.comparison_group_id,
                ):
                    raise ValueError("Catalog identity mismatch")
                if bundle.source_kind == self.data_mode:
                    result.append(bundle)
            return result
        except Exception as exc:
            logger.warning("Comparison store rejected: %s", type(exc).__name__)
            raise ComparisonError(
                503, "comparison_bundle_invalid", "研究结果文件无法读取或校验失败"
            ) from exc

    def get(self, run_id: str) -> Bundle:
        for bundle in self.all():
            if bundle.run_id == run_id:
                return bundle
        raise ComparisonError(404, "comparison_not_found", "未找到已发布研究结果")
