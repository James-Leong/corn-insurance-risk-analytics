"""Immutable, bounded research experiments for the insurance business team."""

from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import math
import statistics
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4
from urllib.parse import urlparse

from fastapi import HTTPException

from app.platform.data import _cutoff, query_data, safe_ratio, validate_trade_rows

MODELS = [
    {"id": "naive_last", "name": "上一观察值基线", "parameters": {}},
    {
        "id": "moving_average",
        "name": "历史移动均值",
        "parameters": {"window": {"min": 2, "max": 60, "default": 5}},
    },
    {"id": "linear_trend", "name": "训练期线性趋势", "parameters": {}},
    {
        "id": "factor_ridge",
        "name": "受控因子岭回归",
        "parameters": {"alpha": {"min": 0.001, "max": 1000, "default": 1}},
    },
]
OPERATORS = [
    {"id": key, "name": name}
    for key, name in (
        ("lag", "滞后"),
        ("return", "变化率"),
        ("rolling_mean", "滚动均值"),
        ("volatility", "滚动变化率波动"),
        ("ratio", "比例"),
        ("diff", "差分"),
    )
]


def now() -> str:
    return datetime.now(UTC).isoformat()


def internal(actor: dict) -> None:
    if actor.get("role") not in {"operator", "reviewer"}:
        raise HTTPException(
            403, detail={"code": "research_forbidden", "message": "研究仅向获授权的业务团队开放"}
        )


@contextmanager
def connection():
    from app.platform.store import connect

    conn = connect()
    try:
        conn.begin("research")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def _insert(conn, kind: str, payload: dict, actor: dict) -> dict:
    item = {
        **payload,
        "id": f"{kind.upper()}-{uuid4().hex[:12]}",
        "version": 1,
        "owner_id": actor["id"],
        "created_at": now(),
    }
    conn.execute(
        "INSERT INTO research_objects (id, kind, payload) VALUES (?, ?, ?)",
        (item["id"], kind, json.dumps(item, ensure_ascii=False, allow_nan=False)),
    )
    return item


def _get(conn, kind: str, item_id: str, actor: dict) -> dict:
    internal(actor)
    row = conn.execute(
        "SELECT payload FROM research_objects WHERE id=? AND kind=?", (item_id, kind)
    ).fetchone()
    if row is None:
        raise HTTPException(
            404, detail={"code": "research_object_missing", "message": "研究对象不存在"}
        )
    item = json.loads(row["payload"])
    project_id = item.get("project_id")
    if project_id and project_id not in actor.get("project_ids", []):
        raise HTTPException(
            403, detail={"code": "research_scope_forbidden", "message": "无此项目研究访问权限"}
        )
    if item.get("share_scope", "private") == "private" and item["owner_id"] != actor["id"]:
        raise HTTPException(403, detail={"code": "research_private", "message": "研究尚未共享"})
    return item


def list_objects(kind: str, actor: dict) -> dict:
    internal(actor)
    with connection() as conn:
        rows = conn.execute(
            "SELECT id FROM research_objects WHERE kind=? ORDER BY sequence_no DESC", (kind,)
        ).fetchall()
        items = []
        for row in rows:
            try:
                item = _get(conn, kind, row["id"], actor)
            except HTTPException as exc:
                if exc.status_code == 403:
                    continue
                raise
            items.append(item)
    return {"items": items}


def get_object(kind: str, item_id: str, actor: dict) -> dict:
    with connection() as conn:
        return _get(conn, kind, item_id, actor)


def get_report(report_id: str, actor: dict) -> dict:
    return get_object("report", report_id, actor)


def save_dataset(payload: dict, actor: dict) -> dict:
    internal(actor)
    if payload.get("project_id") and payload["project_id"] not in actor.get("project_ids", []):
        raise HTTPException(403, detail={"code": "project_forbidden", "message": "无此项目权限"})
    if not payload.get("as_of"):
        raise ValueError("必须指定研究截止时点")
    query = {
        key: payload[key]
        for key in ("series_id", "start_date", "end_date", "as_of", "availability_mode")
        if key in payload and payload[key] is not None
    }
    result = query_data(query)
    if not result["observations"]:
        raise ValueError("截止时点内没有可用观察值，不能保存空数据集")
    if len(result["observations"]) > 2500:
        raise ValueError("单次研究最多2500条观察值")
    snapshot = {"query": query, "series": result["series"], "observations": result["observations"]}
    with connection() as conn:
        return _insert(
            conn,
            "dataset",
            {
                **payload,
                **snapshot,
                "row_count": len(result["observations"]),
                "warnings": result["warnings"],
                "content_hash": _hash(snapshot),
                "share_scope": "team",
                "immutable": True,
            },
            actor,
        )


def _period(value) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not float(value).is_integer()
        or not 1 <= value <= 120
    ):
        raise ValueError("因子窗口/滞后必须为1至120的整数")
    return int(value)


def evaluate_expression(expression: str, fields: dict[str, list]) -> list[float | None]:
    """AST interpreter: no attribute, import, subscript, comprehension or arbitrary calls."""
    if len(expression) > 300 or not fields:
        raise ValueError("表达式过长或缺少输入字段")
    size = len(next(iter(fields.values())))
    try:
        root = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("因子表达式语法错误") from exc
    if len(list(ast.walk(root))) > 70:
        raise ValueError("因子表达式过于复杂")

    def vector(value):
        return value if isinstance(value, list) else [value] * size

    def apply_binary(left, right, operator):
        output = []
        for a, b in zip(vector(left), vector(right), strict=True):
            if a is None or b is None:
                output.append(None)
                continue
            value = None
            if operator == "ratio":
                value, _ = safe_ratio(a, b)
            elif operator == "add":
                value = a + b
            elif operator == "subtract":
                value = a - b
            elif operator == "multiply":
                value = a * b
            output.append(value if value is not None and math.isfinite(value) else None)
        return output

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if (
            isinstance(node, ast.Constant)
            and type(node.value) in {int, float}
            and math.isfinite(node.value)
            and abs(node.value) <= 1e10
        ):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in fields:
            return fields[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            val = visit(node.operand)
            return apply_binary(val, -1 if isinstance(node.op, ast.USub) else 1, "multiply")
        if isinstance(node, ast.BinOp) and type(node.op) in {ast.Add, ast.Sub, ast.Mult, ast.Div}:
            operator = {
                ast.Add: "add",
                ast.Sub: "subtract",
                ast.Mult: "multiply",
                ast.Div: "ratio",
            }[type(node.op)]
            return apply_binary(visit(node.left), visit(node.right), operator)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            fn = node.func.id
            if fn == "ratio" and len(node.args) == 2:
                return apply_binary(visit(node.args[0]), visit(node.args[1]), "ratio")
            if (
                fn not in {"lag", "returns", "rolling_mean", "volatility", "diff"}
                or len(node.args) != 2
            ):
                raise ValueError("只允许注册的因子算子")
            values, period = vector(visit(node.args[0])), _period(visit(node.args[1]))
            shifted = [None] * min(period, size) + values[: max(size - period, 0)]
            if fn == "lag":
                return shifted
            if fn == "diff":
                return apply_binary(values, shifted, "subtract")
            if fn == "returns":
                return apply_binary(apply_binary(values, shifted, "ratio"), 1, "subtract")
            if fn == "volatility":
                values = apply_binary(
                    apply_binary(values, [None] + values[:-1], "ratio"), 1, "subtract"
                )
            output = []
            for i in range(size):
                window = values[max(0, i - period + 1) : i + 1]
                if len(window) < period or any(x is None for x in window):
                    output.append(None)
                else:
                    output.append(
                        statistics.pstdev(window)
                        if fn == "volatility"
                        else statistics.fmean(window)
                    )
            return output
        raise ValueError("不允许的因子语法，仅支持数据字段、常数、四则运算及注册算子")

    return vector(visit(root))


def save_factor(payload: dict, actor: dict) -> dict:
    internal(actor)
    if payload.get("project_id") and payload["project_id"] not in actor.get("project_ids", []):
        raise HTTPException(403, detail={"code": "project_forbidden", "message": "无此项目权限"})
    operator = payload.get("operator", "expression")
    if operator == "expression":
        expression = payload.get("expression", "")
    elif operator == "ratio":
        expression = f"ratio({payload.get('input_field', 'value')},{payload.get('denominator_field', 'value')})"
    elif operator in {item["id"] for item in OPERATORS}:
        period = _period(
            payload.get("lag", 1)
            if operator in {"lag", "return", "diff"}
            else payload.get("window", 5)
        )
        fn = "returns" if operator == "return" else operator
        expression = f"{fn}({payload.get('input_field', 'value')},{period})"
    else:
        raise ValueError("因子算子未注册")
    preview = evaluate_expression(
        expression,
        {
            "value": [100.0 + i for i in range(130)],
            "domestic_consumption": [80.0] * 130,
            "exports_my": [20.0] * 130,
            "ending_stocks": [None] * 130,
        },
    )
    with connection() as conn:
        return _insert(
            conn,
            "factor",
            {
                **payload,
                "expression": expression,
                "methodology_version": "safe-factor-v1",
                "share_scope": "team",
                "preview": preview[-10:],
                "warnings": [
                    "预览为固定合成验算序列，非市场实测；窗口不足、缺失或分母为零返回N/A，只向后取样。"
                ],
            },
            actor,
        )


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    xmean, ymean = statistics.fmean(xs), statistics.fmean(ys)
    denominator = sum((x - xmean) ** 2 for x in xs)
    slope = (
        sum((x - xmean) * (y - ymean) for x, y in zip(xs, ys, strict=True)) / denominator
        if denominator
        else 0
    )
    return ymean - slope * xmean, slope


def _solve(matrix, target):
    size = len(target)
    augmented = [[*row, target[i]] for i, row in enumerate(matrix)]
    for pivot in range(size):
        row = max(range(pivot, size), key=lambda i: abs(augmented[i][pivot]))
        augmented[row], augmented[pivot] = augmented[pivot], augmented[row]
        scale = augmented[pivot][pivot]
        if abs(scale) < 1e-12:
            raise ValueError("因子矩阵无法求解，请调整因子")
        augmented[pivot] = [value / scale for value in augmented[pivot]]
        for index in range(size):
            if index != pivot:
                multiple = augmented[index][pivot]
                augmented[index] = [
                    a - multiple * b
                    for a, b in zip(augmented[index], augmented[pivot], strict=True)
                ]
    return [row[-1] for row in augmented]


def _metrics(rows: list[dict], key: str) -> dict:
    if not rows:
        return {"sample_count": 0, "mae": None, "rmse": None, "bias": None}
    errors = [row[key] - row["actual"] for row in rows]
    return {
        "sample_count": len(rows),
        "mae": statistics.fmean(abs(x) for x in errors),
        "rmse": math.sqrt(statistics.fmean(x * x for x in errors)),
        "bias": statistics.fmean(errors),
    }


def run_experiment(payload: dict, actor: dict) -> dict:
    internal(actor)
    if payload.get("project_id") and payload["project_id"] not in actor.get("project_ids", []):
        raise HTTPException(403, detail={"code": "project_forbidden", "message": "无此项目权限"})
    with connection() as conn:
        dataset = _get(conn, "dataset", payload["dataset_id"], actor)
        if (
            payload.get("project_id")
            and dataset.get("project_id")
            and payload["project_id"] != dataset["project_id"]
        ):
            raise ValueError("实验与研究快照项目不一致")
        factor_ids = payload.get("factor_ids", [])
        if len(factor_ids) > 6:
            raise ValueError("单次研究最多6个因子")
        factors = [_get(conn, "factor", factor_id, actor) for factor_id in factor_ids]
        model = payload.get("model_id", "naive_last")
        if model not in {item["id"] for item in MODELS}:
            raise ValueError("模型未注册")
        target = payload.get("target", "price")
        if target not in {"price", "payout"}:
            raise ValueError("本期支持价格参考和赔款金额情景目标")
        params = payload.get("parameters", {})
        allowed = {"moving_average": {"window"}, "factor_ridge": {"alpha"}}.get(model, set())
        if set(params) - allowed:
            raise ValueError("模型包含未注册参数")
        window = _period(params.get("window", 5))
        if not 2 <= window <= 60:
            raise ValueError("模型均值窗口须为2至60")
        alpha = float(params.get("alpha", 1))
        if not math.isfinite(alpha) or not 0.001 <= alpha <= 1000:
            raise ValueError("正则系数须为0.001至1000")
        if model == "factor_ridge" and not factors:
            raise ValueError("因子岭回归至少选择一个因子")
        terms = payload.get("policy_terms") or {}
        strike, quantity = float(terms.get("strike", 0)), float(terms.get("quantity", 0))
        if target == "payout" and (
            not math.isfinite(strike + quantity) or strike <= 0 or quantity <= 0 or quantity > 1e8
        ):
            raise ValueError("赔款情景须填写正数保障价和数量，数量不超过1亿吨")
        base = {
            **payload,
            "dataset_snapshot": dataset,
            "factor_snapshots": factors,
            "project_id": dataset.get("project_id"),
            "model_version": "registered-research-v1",
            "share_scope": "team",
            "execution_mode": "research_only",
            "predictions": [],
            "metrics": {},
            "warnings": dataset["warnings"]
            + [
                "本结果仅用于承保和风险转移研究，不构成核赔、期权估值或资金投资指令。",
                "验证与测试为逐日一步预测，仅用上一观察点及已披露可得时点假设；训练段为拟合诊断，不计入样本外指标。",
            ],
            "unit": "元/吨" if target == "price" else "元",
            "target_definition": "下一观察日价格"
            if target == "price"
            else "单观察日价格假设下max(保障价-价格,0)×数量；非正式保单采价赔款",
            "validation": {"test_reused": False, "independent_test": False},
        }
        observations = dataset["observations"]
        if dataset["series"]["kind"] != "market" or len(observations) < 16:
            return _insert(
                conn,
                "run",
                {
                    **base,
                    "status": "insufficient_data",
                    "message": "研究至少需要16条可用日行情；单期供需快照不具备时间序列验证样本。",
                },
                actor,
            )
        if any(row["value"] is None for row in observations):
            return _insert(
                conn,
                "run",
                {**base, "status": "failed", "message": "输入含缺失值，未静默补零或删除"},
                actor,
            )
        dates = [row["date"] for row in observations]
        if len(set(dates)) != len(dates) or dates != sorted(dates):
            raise ValueError("研究日行情必须按日期升序且唯一")
        values = [float(row["value"]) for row in observations]
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError("研究输入必须为有限正数")
        if dataset["series"]["field"] not in {"settlePrice", "closePrice"}:
            raise ValueError("价格与赔款目标只能使用明确的收盘价或结算价")
        train_end = payload.get("train_end") or dates[int(len(dates) * 0.6)]
        validation_end = payload.get("validation_end") or dates[int(len(dates) * 0.8)]
        test_end = payload.get("test_end") or dates[-1]
        if not dates[0] <= train_end < validation_end < test_end <= dates[-1]:
            raise ValueError("时间切分须满足样本起点≤训练截止<验证截止<测试截止≤样本终点")
        feature_series = [
            evaluate_expression(factor["expression"], {"value": values}) for factor in factors
        ]
        samples = []
        for index in range(1, len(values)):
            if dates[index] > test_end:
                continue
            # Every feature is shifted one full observation, including raw price.
            feature = [column[index - 1] for column in feature_series]
            if model == "factor_ridge" and any(value is None for value in feature):
                continue
            split = (
                "train"
                if dates[index] <= train_end
                else "validation"
                if dates[index] <= validation_end
                else "test"
            )
            samples.append({"index": index, "features": feature, "split": split})
        counts = {
            key: sum(row["split"] == key for row in samples)
            for key in ("train", "validation", "test")
        }
        base["splits"] = {
            "train_end": train_end,
            "validation_end": validation_end,
            "test_end": test_end,
            "counts": counts,
        }
        if counts["train"] < 8 or counts["validation"] < 3 or counts["test"] < 3:
            return _insert(
                conn,
                "run",
                {
                    **base,
                    "status": "insufficient_data",
                    "message": "训练/验证/测试可用样本至少8/3/3条；因子窗口可能消耗样本。",
                },
                actor,
            )
        train = [row for row in samples if row["split"] == "train"]
        intercept, slope = _linear_fit(
            [row["index"] for row in train], [values[row["index"]] for row in train]
        )
        weights, means, scales = [], [], []
        if model == "factor_ridge":
            means = [
                statistics.fmean(row["features"][j] for row in train) for j in range(len(factors))
            ]
            scales = [
                statistics.pstdev(row["features"][j] for row in train) or 1
                for j in range(len(factors))
            ]
            xrows = [
                [1, *[(value - means[j]) / scales[j] for j, value in enumerate(row["features"])]]
                for row in train
            ]
            size = len(factors) + 1
            matrix = [
                [
                    sum(row[i] * row[j] for row in xrows) + (alpha if i == j and i else 0)
                    for j in range(size)
                ]
                for i in range(size)
            ]
            target_vector = [
                sum(x[i] * values[row["index"]] for x, row in zip(xrows, train, strict=True))
                for i in range(size)
            ]
            weights = _solve(matrix, target_vector)
            base["fitted_transform"] = {
                "means": means,
                "scales": scales,
                "fit_scope": "train_only",
                "weights": weights,
            }
        for row in samples:
            index = row["index"]
            baseline = values[index - 1]
            forecast = baseline
            if model == "moving_average":
                forecast = statistics.fmean(values[max(0, index - window) : index])
            elif model == "linear_trend":
                forecast = intercept + slope * index
            elif model == "factor_ridge":
                x = [
                    1,
                    *[(value - means[j]) / scales[j] for j, value in enumerate(row["features"])],
                ]
                forecast = sum(a * b for a, b in zip(x, weights, strict=True))
            actual = values[index]
            if target == "payout":
                actual, forecast, baseline = [
                    max(strike - price, 0) * quantity for price in (actual, forecast, baseline)
                ]
            base["predictions"].append(
                {
                    "date": dates[index],
                    "actual": actual,
                    "predicted": forecast,
                    "baseline": baseline,
                    "split": row["split"],
                    "feature_cutoff": dates[index - 1],
                }
            )
        evaluated = [row for row in base["predictions"] if row["split"] == "test"]
        base["metrics"] = {
            "model": _metrics(evaluated, "predicted"),
            "baseline": _metrics(evaluated, "baseline"),
            "by_split": {
                split: _metrics(
                    [row for row in base["predictions"] if row["split"] == split], "predicted"
                )
                for split in counts
            },
        }
        # The response exposes test results. Any subsequent candidate using these same
        # underlying data and test dates must be labelled reused, even with a new dataset id.
        signatures = [
            _hash({"series_id": dataset["series"]["id"], "test_date": row["date"]})
            for row in evaluated
        ]
        exposures = [
            conn.execute(
                "SELECT run_id FROM research_test_exposures WHERE signature=?", (signature,)
            ).fetchone()
            for signature in signatures
        ]
        existed = next((item for item in exposures if item is not None), None)
        base["validation"] = {
            "test_reused": bool(existed),
            "independent_test": not bool(existed),
            "previous_run_id": existed["run_id"] if existed else None,
            "previously_exposed_count": sum(item is not None for item in exposures),
            "notice": "测试已被查看，本次属于重复评估，不再声明独立验证。"
            if existed
            else "本次首次解封此测试区间；后续同区间实验将标记重复评估。",
            "candidate_locked_before_test": True,
            "protocol": "chronological-one-step-v1",
        }
        result = _insert(
            conn,
            "run",
            {**base, "status": "succeeded", "message": "研究完成；结果仅供人工复核参考"},
            actor,
        )
        for signature in signatures:
            conn.execute(
                "INSERT IGNORE INTO research_test_exposures VALUES (?, ?, ?)",
                (signature, result["id"], now()),
            )
        return result


def save_report(payload: dict, actor: dict) -> dict:
    internal(actor)
    project_id = payload.get("project_id")
    if project_id and project_id not in actor.get("project_ids", []):
        raise HTTPException(403, detail={"code": "project_forbidden", "message": "无此项目权限"})
    if payload.get("share_scope", "private") not in {"private", "team"}:
        raise ValueError("报告共享范围仅支持private或team")
    with connection() as conn:
        run = _get(conn, "run", payload["run_id"], actor)
        if project_id and run.get("project_id") and project_id != run["project_id"]:
            raise ValueError("报告与来源实验项目不一致")
        if run["status"] != "succeeded":
            raise ValueError("仅成功实验可生成正式研究报告")
        return _insert(
            conn,
            "report",
            {
                **payload,
                "run_snapshot": run,
                "input_hash": _hash(run),
                "project_id": project_id or run.get("project_id"),
                "share_scope": payload.get("share_scope", "private"),
                "immutable": True,
                "limitations": run["warnings"],
                "purpose": "承保、赔付与风险转移研究；不得直接替代核赔、交易或付款审批",
            },
            actor,
        )


def imported_data() -> list[dict]:
    with connection() as conn:
        return [
            json.loads(row["payload"])["data"]
            for row in conn.execute(
                "SELECT payload FROM research_objects WHERE kind='data_import' ORDER BY sequence_no"
            )
        ]


def import_data(payload: dict, actor: dict) -> dict:
    """Content-only import: never fetch arbitrary URLs or execute spreadsheet formulas."""
    internal(actor)
    source_uri = payload["source_uri"]
    if urlparse(source_uri).scheme not in {"https", "http"} or not urlparse(source_uri).netloc:
        raise ValueError("原文链接必须为有效HTTP(S)地址")
    _cutoff(payload["source_published_at"])
    rows = payload.get("rows") or []
    if payload.get("csv_content"):
        if rows:
            raise ValueError("JSON记录与CSV内容只能选择一种")
        if len(payload["csv_content"]) > 2_000_000:
            raise ValueError("CSV内容不能超过2MB")
        rows = list(csv.DictReader(io.StringIO(payload["csv_content"])))
    if not 1 <= len(rows) <= 5000:
        raise ValueError("每批导入1至5000条记录")
    if payload["kind"] == "trade" and payload["period_type"] not in {
        "calendar_month",
        "calendar_year",
    }:
        raise ValueError("贸易数据必须明确自然月或自然年，不能混作市场年度")
    if payload["kind"] == "supply_demand" and payload["period_type"] not in {"MY", "TY"}:
        raise ValueError("供需数据必须明确MY或TY")
    normalized, seen = [], set()
    for index, raw in enumerate(rows, 1):
        row = dict(raw)
        try:
            value = float(row["value"])
            if not math.isfinite(value):
                raise ValueError("数值不是有限数")
            if value < 0 and row.get("metric") != "stock_change":
                raise ValueError("数量、金额和库存不能为负；仅结余变化允许负数")
            period_start = str(row["period_start"])
            period_end = str(row["period_end"])
            _cutoff(period_start)
            _cutoff(period_end)
            if period_start > period_end:
                raise ValueError("统计起点晚于终点")
            unit = str(row.get("unit", payload["unit"]))
            if unit != payload["unit"]:
                raise ValueError("同一批次不能混合单位")
            if payload["kind"] == "trade":
                for key in ("reporter", "partner", "flow", "hs_code", "hs_revision"):
                    if not row.get(key):
                        raise ValueError(f"缺少{key}")
                if str(row["hs_code"]) not in {"1005", "100510", "100590"}:
                    raise ValueError("首期仅支持HS1005及100510/100590玉米原粮")
                if row["flow"] not in {"import", "export", "reimport", "reexport"}:
                    raise ValueError("未知贸易流向")
                row["period"] = f"{period_start}/{period_end}"
                series_key = ".".join(
                    str(row[key])
                    for key in ("reporter", "partner", "flow", "hs_revision", "hs_code")
                )
                name = f"{row['reporter']} {row['flow']} {row['partner']} HS{row['hs_code']}"
            else:
                for key in ("entity_code", "metric"):
                    if not row.get(key):
                        raise ValueError(f"缺少{key}")
                if row["metric"] not in {
                    "production",
                    "imports_my",
                    "exports_my",
                    "imports_ty",
                    "exports_ty",
                    "domestic_consumption",
                    "ending_stocks",
                    "beginning_stocks",
                    "stock_change",
                    "feed_use",
                    "food_use",
                    "industrial_use",
                }:
                    raise ValueError("供需指标不在首期字段清单")
                if (
                    payload["period_type"] == "MY"
                    and row["metric"] in {"imports_ty", "exports_ty"}
                    or payload["period_type"] == "TY"
                    and row["metric"] not in {"imports_ty", "exports_ty"}
                ):
                    raise ValueError("指标与MY/TY口径不一致")
                if not row.get("marketing_year"):
                    raise ValueError("供需数据缺少市场/贸易年度标签")
                series_key = f"{row['entity_code']}.{row['metric']}"
                name = f"{row['entity_code']} {row['metric']}"
            identity = (series_key, period_start, period_end)
            if identity in seen:
                raise ValueError("同批次有重复观察业务键")
            seen.add(identity)
            normalized.append(
                {
                    **row,
                    "value": value,
                    "unit": unit,
                    "date": period_start,
                    "period_start": period_start,
                    "period_end": period_end,
                    "series_key": series_key,
                    "series_name": name,
                }
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"第{index}行：{exc}") from exc
    if payload["kind"] == "trade":
        validate_trade_rows(normalized)
    elif payload["unit"] not in {"吨", "千吨", "万吨", "kg"}:
        raise ValueError("供需数量必须使用重量单位，不能混入金额")
    identity = {
        key: payload[key]
        for key in (
            "source_id",
            "source_revision",
            "source_published_at",
            "kind",
            "period_type",
            "unit",
        )
    }
    identity["is_fixture"] = bool(payload.get("is_fixture", False))
    content_hash = _hash({"identity": identity, "rows": normalized})
    with connection() as conn:
        previous = conn.execute(
            "SELECT payload FROM research_objects WHERE kind='data_import'"
        ).fetchall()
        for item in previous:
            existing = json.loads(item["payload"])
            if existing["release_identity"] == identity:
                if existing["content_hash"] == content_hash:
                    return {**existing, "duplicate": True}
                raise ValueError("相同发布版本已存在不同内容；须使用新修订号，不得覆盖")
        preview = {
            "status": "preview",
            "row_count": len(normalized),
            "content_hash": content_hash,
            "release_identity": identity,
            "rows": normalized[:20],
            "warnings": ["人工提供的外部数据；未由平台向原发布机构核验。确认后生成不可变版本。"],
        }
        if payload.get("mode", "preview") == "preview":
            return preview
        source_id = f"manual.{payload['source_id']}.{uuid4().hex[:8]}"
        ingested_at = now()
        source = {
            "id": source_id,
            "name": payload["name"],
            "status": "fixture" if payload.get("is_fixture") else "manual_import",
            "source_uri": source_uri,
            "note": "合成验收样例，不代表真实国家或贸易数据"
            if payload.get("is_fixture")
            else "人工导入，原始文件真实性未由平台核验；版本不可覆盖",
        }
        series_by_id, observations = {}, []
        for row in normalized:
            series_id = f"{source_id}.{row['series_key']}"
            series_by_id[series_id] = {
                "id": series_id,
                "name": row["series_name"],
                "unit": payload["unit"],
                "source_id": source_id,
                "status": "available",
                "kind": payload["kind"],
                "definition": f"人工导入；{payload['period_type']}；{payload['source_revision']}",
                "entity_code": row.get("entity_code", row.get("reporter")),
                "verification_status": "unverified",
                "is_fixture": bool(payload.get("is_fixture", False)),
            }
            observations.append(
                {
                    **row,
                    "series_id": series_id,
                    "source_uri": source_uri,
                    "source_published_at": payload["source_published_at"],
                    "first_seen_at": ingested_at,
                    "release_id": payload["source_revision"],
                    "period_type": payload["period_type"],
                    "quality_flag": "fixture" if payload.get("is_fixture") else "manual_unverified",
                }
            )
        if payload["kind"] == "supply_demand" and payload["period_type"] == "MY":
            groups = {}
            for row in normalized:
                key = (
                    row["entity_code"],
                    row["period_start"],
                    row["period_end"],
                    row["marketing_year"],
                )
                groups.setdefault(key, {})[row["metric"]] = row
            for (entity, _, _, _), fields in groups.items():
                if "domestic_consumption" not in fields or "exports_my" not in fields:
                    continue
                consumption, exports = (
                    fields["domestic_consumption"]["value"],
                    fields["exports_my"]["value"],
                )
                for metric, numerator, formula in (
                    ("domestic_share", consumption, "C/(C+X)"),
                    ("export_share", exports, "X/(C+X)"),
                    ("stocks_to_use", fields.get("ending_stocks", {}).get("value"), "E/(C+X)"),
                ):
                    value, reason = safe_ratio(numerator, consumption + exports)
                    series_id = f"{source_id}.{entity}.{metric}"
                    series_by_id[series_id] = {
                        "id": series_id,
                        "name": f"{entity} {metric}",
                        "unit": "比例",
                        "source_id": source_id,
                        "status": "available",
                        "kind": "supply_demand",
                        "definition": formula,
                        "entity_code": entity,
                        "verification_status": "unverified",
                        "is_fixture": bool(payload.get("is_fixture", False)),
                    }
                    observations.append(
                        {
                            **fields["domestic_consumption"],
                            "series_id": series_id,
                            "value": value,
                            "unit": "比例",
                            "formula": formula,
                            "components": {
                                "domestic_consumption": consumption,
                                "exports_my": exports,
                                "ending_stocks": fields.get("ending_stocks", {}).get("value"),
                            },
                            "components_unit": payload["unit"],
                            "source_uri": source_uri,
                            "source_published_at": payload["source_published_at"],
                            "first_seen_at": ingested_at,
                            "release_id": payload["source_revision"],
                            "period_type": "MY",
                            "quality_flag": (
                                "fixture" if payload.get("is_fixture") else "manual_unverified"
                            )
                            if value is not None
                            else "not_provided",
                            "unavailable_reason": reason,
                        }
                    )
        return _insert(
            conn,
            "data_import",
            {
                "name": payload["name"],
                "share_scope": "team",
                "content_hash": content_hash,
                "release_identity": identity,
                "row_count": len(normalized),
                "immutable": True,
                "status": "confirmed",
                "data": {
                    "source": source,
                    "series": list(series_by_id.values()),
                    "observations": observations,
                },
            },
            actor,
        )
