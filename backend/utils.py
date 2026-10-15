"""PandasViz Studio 通用工具：路径常量、JSON 安全序列化、列类型识别。

作者：PandasViz Studio
说明：后端以真实 pandas 为计算内核，所有结果都会经由 ``to_native`` 转成
标准 Python 类型后再返回给前端，避免 numpy 标量 / NaN / Timestamp 造成
``JSON.parse`` 失败。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DATA_DIR = PROJECT_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

#: pandas dtype -> 对前端暴露的统一类型
KIND_NUMERIC = "numeric"
KIND_DATETIME = "datetime"
KIND_CATEGORICAL = "categorical"
KIND_BOOLEAN = "boolean"
KIND_TEXT = "text"


def to_native(obj):
    """把 numpy / pandas 对象递归转换为 JSON 可安全序列化的原生类型。"""
    if obj is None:
        return None
    if isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return None if (math.isnan(value) or math.isinf(value)) else value
    if obj is pd.NaT or obj is pd.NA:
        return None
    if isinstance(obj, (pd.Timestamp, _dt.datetime, _dt.date, _dt.time)):
        if isinstance(obj, pd.Timestamp) and obj is pd.NaT:
            return None
        return obj.isoformat()
    if isinstance(obj, pd.Timedelta):
        return obj.total_seconds()
    if isinstance(obj, np.datetime64):
        ts = pd.Timestamp(obj)
        return None if pd.isna(ts) else ts.isoformat()
    if isinstance(obj, np.timedelta64):
        return float(pd.Timedelta(obj).total_seconds())
    if isinstance(obj, np.ndarray):
        return [to_native(v) for v in obj.tolist()]
    if isinstance(obj, (list, tuple, set)):
        return [to_native(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): to_native(v) for k, v in obj.items()}
    if isinstance(obj, pd.Series):
        return [to_native(v) for v in obj.tolist()]
    if isinstance(obj, pd.DataFrame):
        return {
            "columns": [str(c) for c in obj.columns],
            "rows": [{str(c): to_native(row[c]) for c in obj.columns} for _, row in obj.iterrows()],
        }
    # 兜底：float('nan') 已经在上面处理，其余转字符串
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return str(obj)


def json_safe_dumps(payload) -> str:
    """确保返回体是合法 JSON（不允许 NaN / Infinity 字面量）。"""
    return json.dumps(to_native(payload), ensure_ascii=False, allow_nan=False)


def classify_series(series: pd.Series) -> str:
    """识别列的语义类型，用于前端选择可视化编码通道。"""
    if pd.api.types.is_bool_dtype(series):
        return KIND_BOOLEAN
    if pd.api.types.is_datetime64_any_dtype(series):
        return KIND_DATETIME
    if pd.api.types.is_numeric_dtype(series):
        # 整数型且基数很小（如 0/1 编码）仍按数值处理，但基数极低的整数
        # 在可视化里更适合当类别，这里保留数值语义交给前端再次判断
        return KIND_NUMERIC
    non_null = series.dropna()
    if non_null.empty:
        return KIND_TEXT
    nunique = non_null.nunique()
    ratio = nunique / max(len(non_null), 1)
    if nunique <= max(45, int(0.35 * len(non_null))) or ratio < 0.35:
        return KIND_CATEGORICAL
    return KIND_TEXT


def dtype_name(series: pd.Series) -> str:
    return str(series.dtype)


def safe_float(value, default=None):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(out) or math.isinf(out):
        return default
    return out


def clamp(value, low, high):
    return max(low, min(high, value))


def steps_fingerprint(dataset_id: str, steps) -> str:
    """管道指纹：用于后端结果缓存。"""
    raw = json.dumps(
        {"dataset": dataset_id, "steps": to_native(steps)},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def human_bytes(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def shorten(value, limit: int = 42) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"
