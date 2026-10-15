"""分析层：把 pandas 计算结果整理成“可视化就绪”的数据结构。

所有函数都接收管道输出的 DataFrame，返回前端可直接渲染的字典
（ECharts 友好的 categories / series / matrix 结构），并附带**等价的 pandas 代码**，
让“图形”与“代码”互相印证。
"""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

from .utils import (
    KIND_BOOLEAN,
    KIND_CATEGORICAL,
    KIND_DATETIME,
    KIND_NUMERIC,
    KIND_TEXT,
    classify_series,
    safe_float,
    to_native,
)

try:  # scipy 提供 KDE / 统计检验，缺失时降级到纯 numpy 实现
    from scipy import stats as _sps
except Exception:  # pragma: no cover - 仅在极简环境触发
    _sps = None

MAX_SCATTER = 3000
MAX_MATRIX_ROWS = 400
MAX_PARALLEL_ROWS = 400
MAX_COLUMNS_FOR_CORR = 16


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def column_kinds(df: pd.DataFrame, meta: dict | None = None) -> dict[str, str]:
    kinds = {str(col): classify_series(df[col]) for col in df.columns}
    return kinds


def describe_columns(df: pd.DataFrame, meta: dict | None = None) -> list[dict]:
    labels = (meta or {}).get("labels") or {}
    value_labels = (meta or {}).get("value_labels") or {}
    out = []
    for col in df.columns:
        name = str(col)
        series = df[col]
        kind = classify_series(series)
        non_null = series.dropna()
        item = {
            "name": name,
            "dtype": str(series.dtype),
            "kind": kind,
            "missing": int(series.isna().sum()),
            "missing_rate": round(float(series.isna().mean()), 4),
            "nunique": int(non_null.nunique()),
            "label": {"zh": name, "en": labels.get(name, name)},
        }
        if name in value_labels:
            item["value_labels"] = value_labels[name]
        out.append(item)
    return out


def numeric_columns(df: pd.DataFrame) -> list[str]:
    return [str(c) for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]


def datetime_columns(df: pd.DataFrame) -> list[str]:
    return [str(c) for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]


def categorical_columns(df: pd.DataFrame, limit: int = 60) -> list[str]:
    out = []
    for col in df.columns:
        series = df[col]
        if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
            continue
        nunique = series.nunique(dropna=True)
        if 1 < nunique <= limit:
            out.append(str(col))
    return out


def series_labels(values) -> list:
    """把类别值转成可展示的字符串（保留原始值用于代码回显）。"""
    return [None if pd.isna(v) else (v.strftime("%Y-%m-%d") if isinstance(v, pd.Timestamp) else v) for v in values]


# ---------------------------------------------------------------------------
# 数据表视图
# ---------------------------------------------------------------------------

def table_page(
    df: pd.DataFrame,
    meta: dict | None = None,
    offset: int = 0,
    limit: int = 50,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    search: str | None = None,
) -> dict:
    work = df
    if search:
        needle = str(search)
        mask = pd.Series(False, index=work.index)
        for col in work.columns:
            mask = mask | work[col].astype("string").str.contains(needle, case=False, na=False, regex=False)
        work = work[mask]
    if sort_by and sort_by in work.columns:
        work = work.sort_values(sort_by, ascending=(sort_dir != "desc"), kind="mergesort")
    total = int(len(work))
    page = work.iloc[offset : offset + limit]
    rows = []
    for _, row in page.iterrows():
        rows.append({str(col): to_native(row[col]) for col in work.columns})
    return {
        "offset": int(offset),
        "limit": int(limit),
        "total": total,
        "rows": rows,
        "columns": describe_columns(work, meta),
        "column_stats": column_stats(work),
        "filtered": int(len(df)),
    }


def column_stats(df: pd.DataFrame) -> list[dict]:
    out = []
    for col in df.columns:
        name = str(col)
        series = df[col]
        nulls = int(series.isna().sum())
        item = {
            "name": name,
            "dtype": str(series.dtype),
            "kind": classify_series(series),
            "missing": nulls,
            "missing_rate": round(float(nulls / max(len(series), 1)), 4),
            "nunique": int(series.nunique(dropna=True)),
        }
        numeric = pd.to_numeric(series, errors="coerce") if not pd.api.types.is_datetime64_any_dtype(series) else None
        if numeric is not None and numeric.notna().any():
            item.update(
                {
                    "min": to_native(numeric.min()),
                    "max": to_native(numeric.max()),
                    "mean": to_native(round(float(numeric.mean()), 4)),
                    "median": to_native(round(float(numeric.median()), 4)),
                    "std": to_native(round(float(numeric.std()), 4)),
                    "sum": to_native(round(float(numeric.sum()), 4)),
                    "zeros": int((numeric == 0).sum()),
                }
            )
        elif pd.api.types.is_datetime64_any_dtype(series):
            item.update(
                {
                    "min": to_native(series.min()),
                    "max": to_native(series.max()),
                    "span_days": to_native((series.max() - series.min()).days if series.notna().any() else None),
                }
            )
        else:
            top = series.value_counts(dropna=True).head(1)
            if len(top):
                item["top"] = {"value": to_native(top.index[0]), "count": int(top.iloc[0])}
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# 数据质量画像
# ---------------------------------------------------------------------------

def profile_dataset(df: pd.DataFrame, meta: dict | None = None) -> dict:
    kinds = column_kinds(df, meta)
    kind_counts: dict[str, int] = {}
    for kind in kinds.values():
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    cells = max(len(df) * max(df.shape[1], 1), 1)
    missing_cells = int(df.isna().sum().sum())
    duplicated = int(df.duplicated().sum())
    memory = int(df.memory_usage(deep=True).sum())

    columns = []
    for col in df.columns:
        name = str(col)
        series = df[col]
        kind = kinds[name]
        non_null = series.dropna()
        entry = {
            "name": name,
            "kind": kind,
            "dtype": str(series.dtype),
            "missing": int(series.isna().sum()),
            "missing_rate": round(float(series.isna().mean()), 4),
            "nunique": int(non_null.nunique()),
            "zeros": int((pd.to_numeric(non_null, errors="coerce") == 0).sum()) if kind == KIND_NUMERIC else 0,
            "label": {"zh": name, "en": ((meta or {}).get("labels") or {}).get(name, name)},
        }
        if kind == KIND_NUMERIC:
            values = pd.to_numeric(non_null, errors="coerce").dropna()
            if len(values):
                entry["stats"] = {
                    "count": int(len(values)),
                    "mean": to_native(round(float(values.mean()), 4)),
                    "std": to_native(round(float(values.std()), 4)),
                    "min": to_native(values.min()),
                    "q1": to_native(values.quantile(0.25)),
                    "median": to_native(values.median()),
                    "q3": to_native(values.quantile(0.75)),
                    "max": to_native(values.max()),
                    "skew": to_native(round(float(values.skew()), 4)) if len(values) > 2 else None,
                    "kurtosis": to_native(round(float(values.kurtosis()), 4)) if len(values) > 3 else None,
                    "cv": to_native(round(float(values.std() / values.mean()), 4)) if values.mean() else None,
                }
                entry["histogram"] = histogram_data(values, bins=24)
        elif kind == KIND_DATETIME:
            valid = pd.to_datetime(non_null, errors="coerce").dropna()
            if len(valid):
                entry["stats"] = {
                    "min": to_native(valid.min()),
                    "max": to_native(valid.max()),
                    "span_days": to_native((valid.max() - valid.min()).days),
                }
        else:
            counts = series.value_counts(dropna=False).head(12)
            entry["top_values"] = [
                {
                    "value": None if pd.isna(idx) else to_native(idx),
                    "label": {"zh": "缺失" if pd.isna(idx) else str(idx), "en": "Missing" if pd.isna(idx) else str(idx)},
                    "count": int(val),
                    "rate": round(float(val / max(len(series), 1)), 4),
                }
                for idx, val in counts.items()
            ]
            if len(non_null):
                entry["balance"] = to_native(round(float(non_null.value_counts(normalize=True).min()), 4))
        columns.append(entry)

    missing_bar = sorted(
        (
            {
                "name": str(col),
                "label": {"zh": str(col), "en": ((meta or {}).get("labels") or {}).get(str(col), str(col))},
                "missing": int(df[col].isna().sum()),
                "rate": round(float(df[col].isna().mean()), 4),
            }
            for col in df.columns
        ),
        key=lambda item: item["rate"],
        reverse=True,
    )

    # 缺失矩阵：行列都做采样，保证图可读
    matrix_cols = [str(c) for c in df.columns][:48]
    sample = df[matrix_cols]
    row_limit = 220
    if len(sample) > row_limit:
        step = max(len(sample) // row_limit, 1)
        sample = sample.iloc[::step].head(row_limit)
    missing_points = []
    for y, (_, row) in enumerate(sample.iterrows()):
        for x, col in enumerate(matrix_cols):
            if pd.isna(row[col]):
                missing_points.append([x, y])
    row_missing_rate = [
        {
            "row": int(i),
            "rate": round(float(sample.iloc[i].isna().mean()), 4),
        }
        for i in range(len(sample))
    ]

    quality = 100.0
    quality -= min(45.0, float(missing_cells / cells) * 400)
    quality -= min(20.0, float(duplicated / max(len(df), 1)) * 100)
    quality -= min(10.0, float(len(numeric_columns(df)) == 0) * 10)
    quality = max(0.0, min(100.0, quality))
    if quality >= 90:
        grade = {"zh": "优秀", "en": "Excellent"}
    elif quality >= 75:
        grade = {"zh": "良好", "en": "Good"}
    elif quality >= 55:
        grade = {"zh": "一般", "en": "Fair"}
    else:
        grade = {"zh": "需要清洗", "en": "Needs Cleaning"}

    return {
        "summary": {
            "rows": int(len(df)),
            "cols": int(df.shape[1]),
            "cells": int(cells),
            "missing_cells": missing_cells,
            "missing_rate": round(float(missing_cells / cells), 4),
            "duplicated_rows": duplicated,
            "duplicated_rate": round(float(duplicated / max(len(df), 1)), 4),
            "memory_bytes": memory,
            "numeric_cols": len(numeric_columns(df)),
            "datetime_cols": len(datetime_columns(df)),
            "categorical_cols": len([k for k in kinds.values() if k in (KIND_CATEGORICAL, KIND_BOOLEAN)]),
            "quality_score": round(quality, 1),
            "quality_grade": grade,
            "kind_counts": kind_counts,
        },
        "columns": columns,
        "missing_bar": missing_bar,
        "missing_matrix": {
            "columns": matrix_cols,
            "rows": int(len(sample)),
            "points": missing_points,
            "row_rates": row_missing_rate,
        },
        "code": (
            "# 数据质量画像\n"
            "df.info()\n"
            "df.isna().sum().sort_values(ascending=False)\n"
            "df.describe(include='all').T\n"
            "df.duplicated().sum()"
        ),
    }


def histogram_data(values: pd.Series, bins: int = 24) -> dict:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return {"edges": [], "counts": [], "labels": []}
    counts, edges = np.histogram(values.to_numpy(dtype=float), bins=bins)
    labels = [
        f"{_fmt(edges[i])}~{_fmt(edges[i + 1])}" for i in range(len(edges) - 1)
    ]
    return {
        "edges": [to_native(e) for e in edges],
        "counts": [int(c) for c in counts],
        "labels": labels,
    }


def _fmt(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


# ---------------------------------------------------------------------------
# 相关性
# ---------------------------------------------------------------------------

def correlation_view(df: pd.DataFrame, meta: dict | None = None, method: str = "pearson", columns: list[str] | None = None) -> dict:
    numeric = numeric_columns(df)
    numeric = [c for c in numeric if df[c].notna().sum() >= 3]
    if columns:
        numeric = [c for c in numeric if c in columns]
    if len(numeric) < 2:
        return {"labels": [], "labels_i18n": [], "matrix": [], "pairs": [], "method": method, "code": "# 至少需要两个数值列"}
    numeric = numeric[:MAX_COLUMNS_FOR_CORR]
    work = df[numeric].apply(pd.to_numeric, errors="coerce")
    cormat = work.corr(method=method if method in ("pearson", "spearman", "kendall") else "pearson")
    labels = [str(c) for c in numeric]
    labels_i18n = [{"zh": label, "en": ((meta or {}).get("labels") or {}).get(label, label)} for label in labels]
    matrix = []
    for i, row_label in enumerate(labels):
        for j, col_label in enumerate(labels):
            value = cormat.iloc[i, j]
            matrix.append([j, i, to_native(round(float(value), 4)) if pd.notna(value) else None])

    pairs = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            value = cormat.iloc[i, j]
            if pd.isna(value):
                continue
            pairs.append({"x": labels[i], "y": labels[j], "r": float(value), "abs_r": abs(float(value))})
    pairs.sort(key=lambda item: item["abs_r"], reverse=True)

    return {
        "labels": labels,
        "labels_i18n": labels_i18n,
        "matrix": matrix,
        "pairs": to_native(pairs[:12]),
        "method": method,
        "sampled_rows": int(len(work)),
        "code": (
            f"corr = df[{labels!r}].corr(method={method!r})\n"
            "import seaborn as sns  # 或使用 ECharts 热力图渲染 corr\n"
            "# sns.heatmap(corr, annot=True, cmap='RdBu_r', center=0)"
        ),
    }


# ---------------------------------------------------------------------------
# 通用聚合（图表底座）
# ---------------------------------------------------------------------------

def _agg_series(df: pd.DataFrame, x: str | None, y: str | None, series_col: str | None, agg: str, top_n: int, sort_mode: str):
    """返回 (categories, [{name, data}], warnings)。"""
    warnings: list[str] = []
    if x is None and series_col:
        x, series_col = series_col, None
    # 同一列不能既当分类轴又当分色：否则 groupby 会出现重复分组键（pandas 会直接抛错）
    if series_col and series_col == x:
        warnings.append("X 轴与分色选了同一列，已自动忽略分色 / color channel ignored (same column as X)")
        series_col = None
    if series_col and series_col == y:
        warnings.append("Y 轴与分色选了同一列，已自动忽略分色 / color channel ignored (same column as Y)")
        series_col = None
    group_cols = [c for c in [x, series_col] if c and c in df.columns]
    use_count = (not y) or y not in df.columns or agg == "size"
    if not group_cols:
        if use_count:
            total = float(len(df))
            name = "行数"
        else:
            total = float(pd.to_numeric(df[y], errors="coerce").agg(agg))
            name = str(y)
        # 明确告诉用户“为什么只有一根柱子”，而不是默默画一个“全部”
        if x and x not in df.columns:
            available = ", ".join(str(c) for c in df.columns[:8])
            warnings.append(
                f"X 轴字段「{x}」不在当前管道结果里（可能被前面的聚合/筛选去掉了），已退化成“全部”合计一根柱子。"
                f"请在 X 轴换一个字段；当前可用的字段有：{available} … / X column not in the pipeline result"
            )
        elif series_col and series_col not in df.columns:
            warnings.append("分色字段不在当前管道结果里，已忽略分色 / color column not in the pipeline result")
        return ["全部"], [{"name": name, "data": [to_native(round(total, 4))]}], warnings

    frame = pd.DataFrame(index=df.index)
    for col in group_cols:
        frame[col] = df[col].values
    if use_count:
        value_col = "行数"
        frame[value_col] = 1.0
        grouped = frame.groupby(group_cols, dropna=False, observed=True)[value_col].sum().reset_index()
    else:
        value_col = str(y)
        frame[value_col] = pd.to_numeric(df[y], errors="coerce").values
        grouped = frame.groupby(group_cols, dropna=False, observed=True)[value_col].agg(agg).reset_index()
    grouped[value_col] = pd.to_numeric(grouped[value_col], errors="coerce")

    if x is not None and top_n and not series_col:
        direction = sort_mode == "asc"
        grouped = grouped.sort_values(value_col, ascending=direction).head(int(top_n))
    elif x is not None and top_n and series_col:
        order = grouped.groupby(x, observed=True)[value_col].sum().sort_values(ascending=(sort_mode == "asc"))
        keep = list(order.head(int(top_n)).index)
        grouped = grouped[grouped[x].isin(keep)]

    axis_col = x if x else group_cols[0]
    categories = []
    for value in grouped[axis_col].tolist():
        if isinstance(value, pd.Timestamp):
            categories.append(value.strftime("%Y-%m-%d"))
        elif pd.isna(value):
            categories.append("(缺失)")
        else:
            categories.append(value)
    categories = list(dict.fromkeys(categories))

    if series_col:
        wide = grouped.pivot_table(index=axis_col, columns=series_col, values=value_col, aggfunc="sum", observed=True)
        wide = wide.reindex([c for c in categories])
        wide.columns = ["(缺失)" if pd.isna(c) else c for c in wide.columns]
        series_list = [
            {"name": str(name), "data": [to_native(None if pd.isna(v) else round(float(v), 4)) for v in wide[name].tolist()]}
            for name in wide.columns
        ]
    else:
        lookup = dict(zip(categories, grouped.set_index(axis_col)[value_col].tolist()))
        series_list = [{"name": value_col, "data": [to_native(None if cat not in lookup or pd.isna(lookup[cat]) else round(float(lookup[cat]), 4)) for cat in categories]}]

    if sort_mode == "none" and not series_col:
        mapping = dict(zip(categories, series_list[0]["data"]))
        order = sorted(mapping, key=lambda k: (mapping[k] is None, mapping[k]))
        categories = order
        series_list[0]["data"] = [mapping[k] for k in order]
    return categories, series_list, warnings


def _agg_code(df: pd.DataFrame, x, y, series_col, agg, top_n) -> str:
    target = y if y else "行数"
    by = ", ".join(repr(c) for c in [x, series_col] if c)
    if y is None:
        line = f"g = df.groupby([{by}], dropna=False, observed=True).size().reset_index(name='行数')"
    else:
        line = f"g = df.groupby([{by}], dropna=False, observed=True)[{y!r}].agg({agg!r}).reset_index()"
    if series_col:
        line += f"\ng = g.pivot_table(index={x!r}, columns={series_col!r}, values={target!r}, aggfunc='sum')"
    else:
        line += f"\ng = g.sort_values({target!r}, ascending=False)"
    if top_n:
        line += f".head({top_n})"
    return line


# ---------------------------------------------------------------------------
# 图表数据装配
# ---------------------------------------------------------------------------

CHART_TYPES = [
    "bar", "hbar", "line", "area", "stacked_bar", "stacked_area", "percent_bar",
    "pie", "donut", "rose", "scatter", "bubble", "histogram", "density", "ecdf",
    "boxplot", "violin", "heatmap", "treemap", "radar", "parallel", "funnel", "scatter_matrix",
]


def build_chart(df: pd.DataFrame, spec: dict, meta: dict | None = None) -> dict:
    chart_type = (spec or {}).get("type") or "bar"
    builder = {
        "bar": _chart_bar,
        "hbar": _chart_bar,
        "line": _chart_bar,
        "area": _chart_bar,
        "stacked_bar": _chart_bar,
        "stacked_area": _chart_bar,
        "percent_bar": _chart_bar,
        "pie": _chart_pie,
        "donut": _chart_pie,
        "rose": _chart_pie,
        "funnel": _chart_pie,
        "treemap": _chart_pie,
        "scatter": _chart_scatter,
        "bubble": _chart_scatter,
        "histogram": _chart_histogram,
        "density": _chart_density,
        "ecdf": _chart_ecdf,
        "boxplot": _chart_boxplot,
        "violin": _chart_violin,
        "heatmap": _chart_heatmap,
        "radar": _chart_radar,
        "parallel": _chart_parallel,
        "scatter_matrix": _chart_scatter_matrix,
    }.get(chart_type, _chart_bar)
    try:
        payload = builder(df, spec or {}, meta or {})
    except Exception as exc:  # noqa: BLE001 - 单个图形渲染失败不应影响整个响应
        message = f"{type(exc).__name__}: {exc}"
        payload = {
            "categories": [],
            "series": [],
            "cells": [],
            "row_labels": [],
            "warnings": [
                f"该字段组合无法绘制这张图：{message} / cannot render this chart with the selected fields"
            ],
            "code": f"# 该字段组合无法绘制：{message}",
        }
    payload["type"] = chart_type
    payload["spec"] = to_native(spec or {})
    return payload


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce")


def _chart_bar(df: pd.DataFrame, spec: dict, meta: dict) -> dict:
    x, y = spec.get("x"), spec.get("y") or None
    series_col = spec.get("series") or None
    agg = spec.get("agg") or ("count" if not y else "sum")
    top_n = int(spec.get("topN") or 0)
    sort_mode = spec.get("sort") or "desc"
    categories, series_list, warnings = _agg_series(df, x, y, series_col, agg, top_n, sort_mode)
    if not y and agg == "sum":
        agg = "count"
    total = sum(v for s in series_list for v in s["data"] if isinstance(v, (int, float)))
    return {
        "categories": to_native(categories),
        "series": to_native(series_list),
        "stacked": bool(spec.get("stacked")) or spec.get("type") in ("stacked_bar", "stacked_area", "percent_bar"),
        "percent": spec.get("type") == "percent_bar" or bool(spec.get("percent")),
        "smooth": bool(spec.get("smooth")),
        "categories_n": len(categories),
        "total": to_native(round(total, 4)),
        "axis": {"x": x, "y": y or "行数", "agg": agg, "series": series_col},
        "code": _agg_code(df, x, y, series_col, agg, top_n),
        "warnings": warnings,
    }


def _chart_pie(df: pd.DataFrame, spec: dict, meta: dict) -> dict:
    x = spec.get("x")
    y = spec.get("y") or None
    agg = spec.get("agg") or ("count" if not y else "sum")
    top_n = int(spec.get("topN") or 10)
    categories, series_list, _ = _agg_series(df, x, y, None, agg, top_n, "desc")
    data = series_list[0]["data"] if series_list else []
    return {
        "categories": to_native(categories),
        "series": [{"name": y or "行数", "data": to_native(data)}],
        "axis": {"x": x, "y": y or "行数", "agg": agg},
        "code": _agg_code(df, x, y, None, agg, top_n),
        "warnings": [],
    }


def _chart_scatter(df: pd.DataFrame, spec: dict, meta: dict) -> dict:
    x, y = spec.get("x"), spec.get("y")
    size_col = spec.get("size") or None
    color_col = spec.get("series") or None
    if x not in df.columns or y not in df.columns:
        return {"categories": [], "series": [], "code": "# 请选择 X / Y 数值列", "warnings": []}
    work = pd.DataFrame({"x": _num(df, x), "y": _num(df, y)})
    if size_col and size_col in df.columns:
        work["size"] = _num(df, size_col)
    if color_col and color_col in df.columns:
        work["color"] = df[color_col].astype("string").fillna("(缺失)")
    work = work.dropna(subset=["x", "y"])
    sampled = False
    if len(work) > MAX_SCATTER:
        work = work.sample(MAX_SCATTER, random_state=42)
        sampled = True
    groups = [(None, work)] 
    if "color" in work.columns:
        groups = [(name, part) for name, part in work.groupby("color", observed=True)]
    series_list = []
    for name, part in groups:
        points = []
        for _, row in part.iterrows():
            point = [to_native(round(float(row["x"]), 5)), to_native(round(float(row["y"]), 5))]
            if "size" in part.columns and pd.notna(row.get("size")):
                point.append(to_native(round(float(row["size"]), 5)))
            points.append(point)
        series_list.append({"name": "(全部)" if name is None else str(name), "data": points})
    trend = None
    if spec.get("fit") and len(work) >= 3:
        slope, intercept = np.polyfit(work["x"].to_numpy(dtype=float), work["y"].to_numpy(dtype=float), 1)
        xmin, xmax = float(work["x"].min()), float(work["x"].max())
        trend = [[xmin, to_native(round(float(slope * xmin + intercept), 5))], [xmax, to_native(round(float(slope * xmax + intercept), 5))]]
        corr = float(work["x"].corr(work["y"]))
    else:
        corr = float(work["x"].corr(work["y"])) if len(work) > 2 else None
    return {
        "categories": [],
        "series": to_native(series_list),
        "points_n": int(len(work)),
        "sampled": sampled,
        "trend": trend,
        "corr": to_native(None if corr is None or math.isnan(corr) else round(corr, 4)),
        "axis": {"x": x, "y": y, "size": size_col, "color": color_col},
        "code": (
            f"df.plot.scatter(x={x!r}, y={y!r}"
            + (f", s=df[{size_col!r}] / df[{size_col!r}].max() * 200" if size_col else "")
            + (f", c={color_col!r}, cmap='tab10'" if color_col else "")
            + ")\n"
            + (f"# 线性拟合：np.polyfit(df[{x!r}], df[{y!r}], 1) → 相关系数 r = {round(corr, 3) if corr is not None and not math.isnan(corr) else 'n/a'}"
               if spec.get("fit") else f"df[[{x!r}, {y!r}]].corr()")
        ),
        "warnings": ["散点已随机抽样至 3,000 点以保证渲染性能"] if sampled else [],
    }


def _chart_histogram(df: pd.DataFrame, spec: dict, meta: dict) -> dict:
    column = spec.get("y") or spec.get("x")
    bins = int(spec.get("bins") or 30)
    series_col = spec.get("series") or None
    if column not in df.columns:
        return {"categories": [], "series": [], "code": "# 请选择数值列", "warnings": []}
    if series_col and series_col in df.columns:
        series_list = []
        edges = None
        for name, part in df.groupby(series_col, dropna=False, observed=True):
            hist = histogram_data(part[column], bins=bins)
            if edges is None:
                edges = hist["edges"]
            series_list.append({"name": "(缺失)" if pd.isna(name) else str(name), "data": hist["counts"]})
        labels = [f"{_fmt(edges[i])}~{_fmt(edges[i + 1])}" for i in range(len(edges) - 1)]
    else:
        hist = histogram_data(df[column], bins=bins)
        labels = hist["labels"]
        series_list = [{"name": column, "data": hist["counts"]}]
    return {
        "categories": to_native(labels),
        "series": to_native(series_list),
        "stacked": True,
        "axis": {"x": column, "agg": "count"},
        "code": (
            f"df[{column!r}].plot.hist(bins={bins}"
            + (f", by={series_col!r}" if series_col else "")
            + ", alpha=0.75, edgecolor='white')"
        ),
        "warnings": [],
    }


def _kde(values: np.ndarray, grid_size: int = 128):
    values = values[np.isfinite(values)]
    if len(values) < 3:
        return None
    if _sps is not None and np.std(values) > 0:
        kde = _sps.gaussian_kde(values)
        grid = np.linspace(values.min(), values.max(), grid_size)
        return grid, kde(grid)
    std = float(np.std(values)) or 1.0
    grid = np.linspace(values.min(), values.max(), grid_size)
    bandwidth = 1.06 * std * len(values) ** (-1 / 5)
    diff = (grid[:, None] - values[None, :]) / bandwidth
    density = np.exp(-0.5 * diff ** 2).sum(axis=1) / (len(values) * bandwidth * math.sqrt(2 * math.pi))
    return grid, density


def _chart_density(df: pd.DataFrame, spec: dict, meta: dict) -> dict:
    column = spec.get("y") or spec.get("x")
    series_col = spec.get("series") or None
    if column not in df.columns:
        return {"categories": [], "series": [], "code": "# 请选择数值列", "warnings": []}
    series_list = []
    groups = df.groupby(series_col, dropna=False, observed=True) if (series_col and series_col in df.columns) else [("(全部)", df)]
    for name, part in groups:
        values = _num(part, column).dropna().to_numpy(dtype=float)
        kde = _kde(values)
        if kde is None:
            continue
        grid, density = kde
        points = [[to_native(round(float(g), 5)), to_native(round(float(d), 8))] for g, d in zip(grid, density)]
        series_list.append({"name": "(缺失)" if pd.isna(name) else str(name), "data": points})
    return {
        "categories": [],
        "series": to_native(series_list),
        "axis": {"x": column, "series": series_col},
        "code": (
            f"import numpy as np, matplotlib.pyplot as plt\n"
            f"import scipy.stats as st\n"
            f"values = df[{column!r}].dropna()\n"
            f"kde = st.gaussian_kde(values)\n"
            f"grid = np.linspace(values.min(), values.max(), 128)\n"
            f"plt.plot(grid, kde(grid))"
        ),
        "warnings": [] if _sps is not None else ["未检测到 scipy，已使用 numpy 高斯核近似"],
    }


def _chart_ecdf(df: pd.DataFrame, spec: dict, meta: dict) -> dict:
    column = spec.get("y") or spec.get("x")
    series_col = spec.get("series") or None
    if column not in df.columns:
        return {"categories": [], "series": [], "code": "# 请选择数值列", "warnings": []}
    series_list = []
    groups = df.groupby(series_col, dropna=False, observed=True) if (series_col and series_col in df.columns) else [("(全部)", df)]
    for name, part in groups:
        values = np.sort(_num(part, column).dropna().to_numpy(dtype=float))
        if len(values) == 0:
            continue
        ys = np.arange(1, len(values) + 1) / len(values)
        step = max(len(values) // 400, 1)
        points = [[to_native(round(float(v), 5)), to_native(round(float(y), 5))] for v, y in zip(values[::step], ys[::step])]
        series_list.append({"name": "(缺失)" if pd.isna(name) else str(name), "data": points})
    return {
        "categories": [],
        "series": to_native(series_list),
        "axis": {"x": column, "series": series_col},
        "code": (
            f"import numpy as np, matplotlib.pyplot as plt\n"
            f"values = np.sort(df[{column!r}].dropna())\n"
            f"y = np.arange(1, len(values) + 1) / len(values)\n"
            f"plt.step(values, y, where='post')  # 经验累积分布函数"
        ),
        "warnings": [],
    }


def _box_stats(values: pd.Series) -> dict | None:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return None
    q1, median, q3 = (float(values.quantile(q)) for q in (0.25, 0.5, 0.75))
    iqr = q3 - q1
    low_bound, high_bound = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = values[(values >= low_bound) & (values <= high_bound)]
    low = float(inside.min()) if len(inside) else float(values.min())
    high = float(inside.max()) if len(inside) else float(values.max())
    outliers = values[(values < low_bound) | (values > high_bound)]
    return {
        "low": low,
        "q1": q1,
        "median": median,
        "q3": q3,
        "high": high,
        "mean": float(values.mean()),
        "n": int(len(values)),
        "outliers": [to_native(round(float(v), 5)) for v in outliers.head(400).tolist()],
        "outlier_count": int(len(outliers)),
    }


def _chart_boxplot(df: pd.DataFrame, spec: dict, meta: dict) -> dict:
    x = spec.get("x")
    y = spec.get("y")
    if not x or not y or x not in df.columns or y not in df.columns:
        return {"categories": [], "series": [], "code": "# 请选择分组列与数值列", "warnings": []}
    order = df.groupby(x, dropna=False, observed=True)[y].median().sort_values(ascending=False).index.tolist()
    categories, boxes, outliers, means = [], [], [], []
    for name in order[: int(spec.get("topN") or 30)]:
        part = df[df[x].isna()] if pd.isna(name) else df[df[x] == name]
        stats = _box_stats(part[y])
        if stats is None:
            continue
        categories.append("(缺失)" if pd.isna(name) else (name.strftime("%Y-%m-%d") if isinstance(name, pd.Timestamp) else name))
        boxes.append([to_native(round(v, 5)) for v in (stats["low"], stats["q1"], stats["median"], stats["q3"], stats["high"])])
        outliers.append([to_native(round(v, 5)) for v in stats["outliers"]])
        means.append(to_native(round(stats["mean"], 5)))
    return {
        "categories": to_native(categories),
        "boxes": to_native(boxes),
        "outliers": to_native(outliers),
        "means": to_native(means),
        "series": [{"name": f"{y} 分布", "data": to_native(boxes)}],
        "axis": {"x": x, "y": y},
        "code": (
            f"df.boxplot(column={y!r}, by={x!r}, rot=45, grid=False)\n"
            f"# 或 seaborn: sns.boxplot(data=df, x={x!r}, y={y!r})"
        ),
        "warnings": [],
    }


def _chart_violin(df: pd.DataFrame, spec: dict, meta: dict) -> dict:
    x, y = spec.get("x"), spec.get("y")
    if not x or not y or x not in df.columns or y not in df.columns:
        return {"categories": [], "series": [], "code": "# 请选择分组列与数值列", "warnings": []}
    order = df.groupby(x, dropna=False, observed=True)[y].median().sort_values(ascending=False).index.tolist()[: int(spec.get("topN") or 12)]
    violins, medians, categories = [], [], []
    for offset, name in enumerate(order):
        part = df[df[x].isna()] if pd.isna(name) else df[df[x] == name]
        values = _num(part, y).dropna().to_numpy(dtype=float)
        kde = _kde(values, grid_size=64)
        label = "(缺失)" if pd.isna(name) else (name.strftime("%Y-%m-%d") if isinstance(name, pd.Timestamp) else name)
        categories.append(label)
        if kde is None:
            medians.append([offset, None])
            continue
        grid, density = kde
        peak = float(np.max(density)) or 1.0
        points = [
            [to_native(round(float(g), 5)), to_native(round(float(offset + 0.42 * d / peak), 5))]
            for g, d in zip(grid, density)
        ]
        violins.append({"name": label, "offset": offset, "points": points})
        medians.append([to_native(round(float(pd.Series(values).median()), 5)), to_native(round(float(offset), 5))])
    return {
        "categories": to_native(categories),
        "violins": to_native(violins),
        "medians": to_native(medians),
        "series": to_native([{"name": v["name"], "data": v["points"]} for v in violins]),
        "axis": {"x": y, "y": x},
        "code": (
            f"import seaborn as sns\n"
            f"sns.violinplot(data=df, x={y!r}, y={x!r}, inner='quartile')"
        ),
        "warnings": [],
    }


def _chart_heatmap(df: pd.DataFrame, spec: dict, meta: dict) -> dict:
    x, y = spec.get("x"), spec.get("y")
    value_col = spec.get("values") or spec.get("value") or None
    if not x or not y or x not in df.columns or y not in df.columns:
        return {"categories": [], "series": [], "cells": [], "code": "# 请选择行 / 列维度", "warnings": []}
    if x == y:
        return {
            "categories": [], "series": [], "cells": [], "row_labels": [],
            "code": "# 行维度与列维度不能是同一列（同一字段无法与自己交叉）",
            "warnings": ["行维度与列维度选了同一列，无法交叉；请把其中一个换成别的字段 / row and column dimensions must differ"],
        }
    if value_col and value_col in (x, y):
        return {
            "categories": [], "series": [], "cells": [], "row_labels": [],
            "code": "# 数值字段不能与行 / 列维度相同",
            "warnings": ["数值字段与行 / 列维度选了同一列；请换一个字段作为数值 / value column must differ from row & column dimensions"],
        }
    agg = spec.get("agg") or ("count" if not value_col else "mean")
    normalize = spec.get("normalize") or "none"
    if value_col and value_col in df.columns:
        table = pd.pivot_table(df, index=y, columns=x, values=value_col, aggfunc=agg, observed=True)
        code = f"table = df.pivot_table(index={y!r}, columns={x!r}, values={value_col!r}, aggfunc={agg!r})"
    else:
        table = pd.crosstab(df[y], df[x])
        code = f"table = pd.crosstab(df[{y!r}], df[{x!r}])  # 计数热力图"
        if normalize == "row":
            table = table.div(table.sum(axis=1), axis=0)
            code += f"\ntable = table.div(table.sum(axis=1), axis=0)  # 按行归一化"
        elif normalize == "col":
            table = table.div(table.sum(axis=0), axis=1)
            code += f"\ntable = table.div(table.sum(axis=0), axis=1)  # 按列归一化"
    table = table.iloc[:24, :18]
    row_labels = ["(缺失)" if pd.isna(i) else (i.strftime("%Y-%m-%d") if isinstance(i, pd.Timestamp) else i) for i in table.index]
    col_labels = ["(缺失)" if pd.isna(i) else (i.strftime("%Y-%m-%d") if isinstance(i, pd.Timestamp) else i) for i in table.columns]
    cells = []
    for i, row_label in enumerate(row_labels):
        for j, col_label in enumerate(col_labels):
            value = table.iloc[i, j]
            cells.append([j, i, to_native(None if pd.isna(value) else round(float(value), 4))])
    return {
        "categories": to_native(col_labels),
        "row_labels": to_native(row_labels),
        "cells": to_native(cells),
        "series": [],
        "axis": {"x": x, "y": y, "value": value_col, "agg": agg},
        "code": code + "\n# sns.heatmap(table, annot=True, fmt='.1f', cmap='YlGnBu')",
        "warnings": [],
    }


def _chart_radar(df: pd.DataFrame, spec: dict, meta: dict) -> dict:
    dims = [c for c in (spec.get("dims") or []) if c in df.columns]
    if not dims:
        dims = numeric_columns(df)[:6]
    group = spec.get("series")
    if not dims:
        return {"categories": [], "series": [], "code": "# 至少需要一个数值维度", "warnings": []}
    numeric_frame = df[dims].apply(pd.to_numeric, errors="coerce")
    if not group or group not in df.columns:
        means = numeric_frame.mean()
        series_list = [{"name": "(全部均值)", "data": [to_native(round(float(v), 4)) for v in means.tolist()]}]
        code = f"df[{dims!r}].mean()"
    else:
        numeric_frame = numeric_frame.assign(__group=df[group].values)
        means = numeric_frame.groupby("__group", dropna=False, observed=True)[dims].mean()
        series_list = [
            {"name": "(缺失)" if pd.isna(name) else str(name), "data": [to_native(round(float(v), 4)) for v in row.tolist()]}
            for name, row in means.iterrows()
        ]
        code = f"df.groupby({group!r})[{dims!r}].mean()"
    return {
        "categories": to_native(dims),
        "series": to_native(series_list),
        "axis": {"dims": dims, "series": group},
        "code": code + "\n# 雷达图：各维度按最大值归一到 0-1 后更易比较",
        "warnings": [],
    }


def _chart_parallel(df: pd.DataFrame, spec: dict, meta: dict) -> dict:
    dims = [c for c in (spec.get("dims") or []) if c in df.columns] or numeric_columns(df)[:6]
    if len(dims) < 2:
        return {"categories": [], "series": [], "code": "# 至少需要两个数值维度", "warnings": []}
    group = spec.get("series") if spec.get("series") in df.columns else None
    work = df[[c for c in [*dims, group] if c]].copy()
    for col in dims:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=dims)
    sampled = False
    if len(work) > MAX_PARALLEL_ROWS:
        work = work.sample(MAX_PARALLEL_ROWS, random_state=42)
        sampled = True
    dim_meta = []
    for col in dims:
        dim_meta.append(
            {
                "name": col,
                "label": {"zh": col, "en": (meta.get("labels") or {}).get(col, col)},
                "min": to_native(float(work[col].min())),
                "max": to_native(float(work[col].max())),
            }
        )
    series_list = []
    if group:
        for name, part in work.groupby(group, observed=True):
            series_list.append({"name": str(name), "data": [[to_native(round(float(v), 5)) for v in row] for row in part[dims].to_numpy()]})
    else:
        series_list.append({"name": "(全部)", "data": [[to_native(round(float(v), 5)) for v in row] for row in work[dims].to_numpy()]})
    dim_names = ", ".join(repr(d) for d in dims)
    class_column = repr(group) if group else "'_class'"
    dim_list = f"[{dim_names}" + (f", {group!r}" if group else "") + "]"
    return {
        "categories": to_native(dims),
        "dims": to_native(dim_meta),
        "series": to_native(series_list),
        "axis": {"dims": dims, "series": group},
        "sampled": sampled,
        "code": (
            "from pandas.plotting import parallel_coordinates\n"
            f"parallel_coordinates(df{dim_list}, class_column={class_column}, colormap='tab10')"
        ),
        "warnings": ["平行坐标已抽样至 400 行"] if sampled else [],
    }


def _chart_scatter_matrix(df: pd.DataFrame, spec: dict, meta: dict) -> dict:
    dims = [c for c in (spec.get("dims") or []) if c in df.columns] or numeric_columns(df)[:4]
    dims = dims[:5]
    if len(dims) < 2:
        return {"categories": [], "series": [], "code": "# 至少需要两个数值列", "warnings": []}
    color = spec.get("series") if spec.get("series") in df.columns else None
    work = df[[c for c in [*dims, color] if c]].copy()
    for col in dims:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=dims)
    sampled = False
    if len(work) > MAX_SCATTER // 4:
        work = work.sample(MAX_SCATTER // 4, random_state=42)
        sampled = True
    groups = [(None, work)] if not color else list(work.groupby(color, observed=True))
    cells = []
    for i, yi in enumerate(dims):
        for j, xj in enumerate(dims):
            if i == j:
                continue
            entry = {"x": j, "y": i, "varX": xj, "varY": yi, "series": []}
            for name, part in groups:
                points = [
                    [to_native(round(float(a), 5)), to_native(round(float(b), 5))]
                    for a, b in zip(part[xj].tolist(), part[yi].tolist())
                ]
                entry["series"].append({"name": "(全部)" if name is None else str(name), "data": points})
            cells.append(entry)
    return {
        "categories": to_native(dims),
        "dims": to_native(dims),
        "cells": to_native(cells),
        "series": [],
        "axis": {"dims": dims, "color": color},
        "sampled": sampled,
        "code": (
            "from pandas.plotting import scatter_matrix\n"
            f"scatter_matrix(df[{dims!r}]"
            + (f", c=pd.factorize(df[{color!r}])[0]" if color else "")
            + ", figsize=(11, 11), alpha=0.6, diagonal='kde')"
        ),
        "warnings": ["散点矩阵已抽样至 750 行"] if sampled else [],
    }


# ---------------------------------------------------------------------------
# 透视 / 时间序列 / 统计检验
# ---------------------------------------------------------------------------

def pivot_view(df: pd.DataFrame, params: dict, meta: dict | None = None) -> dict:
    index = params.get("index")
    columns = params.get("columns")
    values = params.get("values")
    agg = params.get("agg") or "mean"
    normalize = params.get("normalize") or "none"
    if index and index in df.columns and columns and columns in df.columns and values in df.columns and values is not None:
        table = pd.pivot_table(df, index=index, columns=columns, values=values, aggfunc=agg, observed=True)
    elif index and index in df.columns and columns and columns in df.columns:
        table = pd.crosstab(df[index], df[columns])
        agg = "count"
    else:
        return {"row_labels": [], "col_labels": [], "cells": [], "code": "# 请选择行/列/值字段"}
    if normalize == "row":
        table = table.div(table.sum(axis=1), axis=0)
    elif normalize == "col":
        table = table.div(table.sum(axis=0), axis=1)
    table = table.iloc[:30, :24]
    row_labels = ["(缺失)" if pd.isna(i) else (i.strftime("%Y-%m-%d") if isinstance(i, pd.Timestamp) else i) for i in table.index]
    col_labels = ["(缺失)" if pd.isna(i) else (i.strftime("%Y-%m-%d") if isinstance(i, pd.Timestamp) else i) for i in table.columns]
    cells = []
    for i in range(len(row_labels)):
        for j in range(len(col_labels)):
            value = table.iloc[i, j]
            cells.append([j, i, to_native(None if pd.isna(value) else round(float(value), 4))])
    return {
        "row_labels": to_native(row_labels),
        "col_labels": to_native(col_labels),
        "cells": to_native(cells),
        "agg": agg,
        "normalize": normalize,
        "shape": [len(row_labels), len(col_labels)],
        "code": (
            f"table = df.pivot_table(index={index!r}, columns={columns!r}, values={values!r}, aggfunc={agg!r})\n"
            + (f"table = table.div(table.sum(axis={'1' if normalize == 'row' else '0'}), "
               f"axis={'0' if normalize == 'row' else '1'})  # 归一化\n" if normalize != "none" else "")
            + "# sns.heatmap(table, annot=True, fmt='.2f', cmap='RdYlBu_r')"
        ),
    }


def timeseries_view(df: pd.DataFrame, params: dict, meta: dict | None = None) -> dict:
    date_col = params.get("date")
    value_col = params.get("value")
    freq = params.get("freq") or "D"
    agg = params.get("agg") or "mean"
    group = params.get("group") if params.get("group") in df.columns else None
    rolling_window = int(params.get("rolling") or 0)
    if date_col not in df.columns or value_col not in df.columns:
        return {"categories": [], "series": [], "code": "# 请选择时间列与数值列"}
    work = df[[c for c in [date_col, value_col, group] if c]].copy()
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce")
    work = work.dropna(subset=[date_col])
    # 选到的列根本不是日期（例如「区域」）：给出明确提示，而不是让 pandas 抛 cannot assemble...
    if work.empty:
        return {
            "categories": [],
            "series": [],
            "freq": freq,
            "agg": agg,
            "rows": 0,
            "error": {
                "zh": f"「{date_col}」不是日期列——解析后没有任何有效日期，无法做时间序列。请把「时间列」换成真正的时间字段"
                      f"（例如 订单日期）；如果当前管道结果里已经没有时间列，点左侧「清空」回到原始数据即可。",
                "en": f"'{date_col}' is not a datetime column — no valid dates after parsing, so a time series cannot be built. "
                      f"Pick a real datetime column (e.g. Order Date), or clear the pipeline to go back to the raw data.",
            },
            "code": f"# 「{date_col}」不是日期列，无法重采样 / not a datetime column",
        }
    pandas_freq = {"M": "ME", "Q": "QE", "Y": "YE"}.get(freq, freq)
    indexed = work.set_index(date_col)
    if group:
        table = indexed.groupby(group, observed=True).resample(pandas_freq)[value_col].agg(agg).unstack(0)
    else:
        table = indexed.resample(pandas_freq)[value_col].agg(agg).to_frame(name=value_col)
    table = table.iloc[-600:]
    categories = [idx.strftime("%Y-%m-%d") if isinstance(idx, pd.Timestamp) else str(idx) for idx in table.index]
    series_list = []
    for col in table.columns:
        values = table[col]
        entry = {
            "name": "(缺失)" if pd.isna(col) else str(col),
            "data": [to_native(None if pd.isna(v) else round(float(v), 5)) for v in values.tolist()],
        }
        if rolling_window > 1:
            entry["rolling"] = [
                to_native(None if pd.isna(v) else round(float(v), 5))
                for v in values.rolling(rolling_window, min_periods=1).mean().tolist()
            ]
            entry["rollingWindow"] = rolling_window
        series_list.append(entry)
    trend = None
    primary = table[table.columns[0]].dropna()
    if len(primary) >= 4:
        x = np.arange(len(primary), dtype=float)
        slope, intercept = np.polyfit(x, primary.to_numpy(dtype=float), 1)
        trend = {
            "slope": to_native(round(float(slope), 5)),
            "direction": {"zh": "上升" if slope > 0 else "下降", "en": "Upward" if slope > 0 else "Downward"},
            "change_rate": to_native(round(float(slope / (primary.mean() or 1)), 4)),
            "points": [[to_native(categories[0]), to_native(round(float(intercept), 5))], [to_native(categories[-1]), to_native(round(float(intercept + slope * (len(primary) - 1)), 5))]],
        }
    code = (
        f"df[{date_col!r}] = pd.to_datetime(df[{date_col!r}])\n"
        f"ts = df.set_index({date_col!r})"
        + (f".groupby({group!r})" if group else "")
        + f"[{value_col!r}].resample({pandas_freq!r}).{agg}()\n"
        + (f"ts = ts.rolling({rolling_window}, min_periods=1).mean()  # 滚动均值\n" if rolling_window > 1 else "")
        + "ts.plot()"
    )
    return {
        "categories": to_native(categories),
        "series": to_native(series_list),
        "trend": to_native(trend),
        "freq": freq,
        "agg": agg,
        "rows": int(len(table)),
        "code": code,
    }


def stats_view(df: pd.DataFrame, params: dict, meta: dict | None = None) -> dict:
    test = params.get("test") or "ttest"
    value_col = params.get("value")
    group_col = params.get("group")
    result: dict = {"test": test, "groups": [], "chart": None}

    if test in ("ttest", "anova"):
        if value_col not in df.columns or group_col not in df.columns:
            return {**result, "error": {"zh": "请选择数值列与分组列", "en": "Pick a value and a group column"}, "code": "# 请选择数值列与分组列"}
        work = pd.DataFrame({"value": pd.to_numeric(df[value_col], errors="coerce"), "group": df[group_col]})
        work = work.dropna(subset=["value", "group"])
        counts = work.groupby("group", observed=True)["value"].count().sort_values(ascending=False)
        keys = list(counts[counts >= 2].index)[:6]
        groups = []
        for key in keys:
            values = work[work["group"] == key]["value"]
            groups.append(
                {
                    "name": str(key),
                    "n": int(len(values)),
                    "mean": to_native(round(float(values.mean()), 4)),
                    "std": to_native(round(float(values.std()), 4)),
                    "median": to_native(round(float(values.median()), 4)),
                    "q1": to_native(round(float(values.quantile(0.25)), 4)),
                    "q3": to_native(round(float(values.quantile(0.75)), 4)),
                }
            )
        result["groups"] = groups
        samples = [work[work["group"] == key]["value"].to_numpy(dtype=float) for key in keys]
        if len(samples) < 2 or _sps is None:
            result["error"] = {"zh": "至少需要两个各含 2 条以上记录的组（且需安装 scipy）", "en": "Need 2+ groups with 2+ rows (and scipy)"}
        elif len(samples) == 2:
            stat, p = _sps.ttest_ind(samples[0], samples[1], equal_var=False)
            pooled = math.sqrt((samples[0].var(ddof=1) + samples[1].var(ddof=1)) / 2) or 1.0
            d = (samples[0].mean() - samples[1].mean()) / pooled
            result.update(
                {
                    "name": {"zh": "Welch 双样本 t 检验", "en": "Welch two-sample t-test"},
                    "stat": to_native(round(float(stat), 5)),
                    "p": to_native(float(p)),
                    "effect": {"label": {"zh": "Cohen's d 效应量", "en": "Cohen's d"}, "value": to_native(round(float(d), 4))},
                    "code": (
                        "from scipy import stats\n"
                        f"a = df.loc[df[{group_col!r}] == {keys[0]!r}, {value_col!r}].dropna()\n"
                        f"b = df.loc[df[{group_col!r}] == {keys[1]!r}, {value_col!r}].dropna()\n"
                        f"stats.ttest_ind(a, b, equal_var=False)"
                    ),
                }
            )
        else:
            stat, p = _sps.f_oneway(*samples)
            result.update(
                {
                    "name": {"zh": "单因素方差分析 (ANOVA)", "en": "One-way ANOVA"},
                    "stat": to_native(round(float(stat), 5)),
                    "p": to_native(float(p)),
                    "effect": {"label": {"zh": "组数", "en": "Groups"}, "value": len(samples)},
                    "code": (
                        "from scipy import stats\n"
                        f"samples = [g[{value_col!r}].dropna() for _, g in df.groupby({group_col!r})]\n"
                        "stats.f_oneway(*samples)"
                    ),
                }
            )
        result["chart"] = _group_distribution_chart(df, value_col, group_col, keys)
        result.setdefault("p_label", {"zh": "p 值", "en": "p-value"})
        result["conclusion"] = _significance_conclusion(result.get("p"))
        return result

    if test == "chi2":
        if value_col not in df.columns or group_col not in df.columns:
            return {**result, "error": {"zh": "请选择两个类别列", "en": "Pick two categorical columns"}, "code": "# 请选择两个类别列"}
        table = pd.crosstab(df[value_col], df[group_col])
        if table.shape[0] < 2 or table.shape[1] < 2:
            return {**result, "error": {"zh": "需要至少 2×2 的列联表", "en": "Need at least a 2x2 table"}}
        stat, p, dof, expected = _sps.chi2_contingency(table.to_numpy(dtype=float))
        v = math.sqrt(float(stat) / (table.to_numpy().sum() * min(table.shape[0] - 1, table.shape[1] - 1) or 1))
        row_labels = [str(i) for i in table.index][:20]
        col_labels = [str(j) for j in table.columns][:20]
        cells = []
        for i in range(len(row_labels)):
            for j in range(len(col_labels)):
                cells.append([j, i, int(table.iloc[i, j])])
        result.update(
            {
                "name": {"zh": "卡方独立性检验", "en": "Chi-square test of independence"},
                "stat": to_native(round(float(stat), 5)),
                "p": to_native(float(p)),
                "dof": int(dof),
                "effect": {"label": {"zh": "Cramér's V", "en": "Cramér's V"}, "value": to_native(round(v, 4))},
                "contingency": {"row_labels": row_labels, "col_labels": col_labels, "cells": to_native(cells)},
                "chart": {"type": "heatmap", "row_labels": row_labels, "col_labels": col_labels, "cells": to_native(cells)},
                "code": (
                    "from scipy import stats\n"
                    f"table = pd.crosstab(df[{value_col!r}], df[{group_col!r}])\n"
                    "stats.chi2_contingency(table)"
                ),
                "conclusion": _significance_conclusion(p),
            }
        )
        return result

    # 正态性 / 描述性统计
    if value_col not in df.columns:
        return {**result, "error": {"zh": "请选择数值列", "en": "Pick a numeric column"}}
    values = pd.to_numeric(df[value_col], errors="coerce").dropna()
    if len(values) < 8:
        return {**result, "error": {"zh": "样本量太少", "en": "Not enough samples"}}
    sample = values.sample(min(len(values), 5000), random_state=42)
    stat, p = _sps.shapiro(sample.to_numpy(dtype=float)) if _sps is not None else (float("nan"), float("nan"))
    result.update(
        {
            "name": {"zh": "Shapiro-Wilk 正态性检验", "en": "Shapiro-Wilk normality test"},
            "stat": to_native(round(float(stat), 5)),
            "p": to_native(float(p)),
            "effect": {"label": {"zh": "偏度", "en": "Skewness"}, "value": to_native(round(float(values.skew()), 4))},
            "groups": [
                {
                    "name": value_col,
                    "n": int(len(values)),
                    "mean": to_native(round(float(values.mean()), 4)),
                    "std": to_native(round(float(values.std()), 4)),
                    "median": to_native(round(float(values.median()), 4)),
                    "q1": to_native(round(float(values.quantile(0.25)), 4)),
                    "q3": to_native(round(float(values.quantile(0.75)), 4)),
                }
            ],
            "chart": {"type": "density", **(_chart_density(df, {"y": value_col}, meta) if value_col in df.columns else {})},
            "code": (
                "from scipy import stats\n"
                f"stats.shapiro(df[{value_col!r}].dropna().sample(5000, random_state=42))"
            ),
            "conclusion": _significance_conclusion(p, invert=True),
        }
    )
    return result


def _significance_conclusion(p) -> dict:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return {"zh": "无法计算", "en": "Not available"}
    if p < 0.001:
        return {"zh": "差异极显著 (p < 0.001)，组间差异不太可能来自随机波动", "en": "Highly significant (p < 0.001) — group differences are unlikely due to chance"}
    if p < 0.05:
        return {"zh": "差异显著 (p < 0.05)，可以认为组间存在真实差异", "en": "Significant (p < 0.05) — a real difference is likely"}
    return {"zh": "差异不显著 (p ≥ 0.05)，暂无证据表明组间存在差异", "en": "Not significant (p ≥ 0.05) — no evidence of a difference"}


def _group_distribution_chart(df: pd.DataFrame, value_col: str, group_col: str, keys: list) -> dict:
    """为 t 检验 / ANOVA 生成“分布对比图”数据（KDE 曲线 + 均值点）。"""
    curves, summaries, categories = [], [], []
    for key in keys:
        part = df[df[group_col] == key]
        values = pd.to_numeric(part[value_col], errors="coerce").dropna().to_numpy(dtype=float)
        kde = _kde(values, grid_size=64)
        categories.append(str(key))
        if kde is None:
            continue
        grid, density = kde
        curves.append({"name": str(key), "data": [[to_native(round(float(g), 5)), to_native(round(float(d), 8))] for g, d in zip(grid, density)]})
        summaries.append(
            {
                "name": str(key),
                "mean": to_native(round(float(np.mean(values)), 4)),
                "median": to_native(round(float(np.median(values)), 4)),
                "std": to_native(round(float(np.std(values, ddof=1)), 4)),
                "n": int(len(values)),
            }
        )
    return {"type": "density", "series": to_native(curves), "summaries": to_native(summaries), "categories": to_native(categories)}


# ---------------------------------------------------------------------------
# 自动洞察
# ---------------------------------------------------------------------------

def auto_insights(df: pd.DataFrame, meta: dict | None = None) -> dict:
    labels = (meta or {}).get("labels") or {}
    insights: list[dict] = []
    rows = len(df)

    def label(col: str) -> str:
        return col  # 中文名直接展示，英文由前端 localize 值标签

    if rows == 0:
        return {
            "insights": [
                {
                    "id": "empty",
                    "level": "warn",
                    "title": {"zh": "当前管道没有剩余数据", "en": "The pipeline returned no rows"},
                    "detail": {"zh": "请检查筛选条件是否过严，或撤销上一步操作。", "en": "Loosen the filters or undo the last step."},
                }
            ],
            "score": 0,
        }

    missing = df.isna().mean().sort_values(ascending=False)
    missing = missing[missing > 0]
    if len(missing):
        worst = missing.head(3)
        detail_zh = "、".join(f"{col}({rate:.1%})" for col, rate in worst.items())
        detail_en = ", ".join(f"{col} ({rate:.1%})" for col, rate in worst.items())
        insights.append(
            {
                "id": "missing",
                "level": "warn" if missing.iloc[0] > 0.15 else "info",
                "title": {"zh": f"{len(missing)} 个字段存在缺失值", "en": f"{len(missing)} column(s) contain missing values"},
                "detail": {"zh": f"缺失最严重的字段：{detail_zh}。建议用中位数/均值填充，或对关键列执行 dropna。", "en": f"Most affected: {detail_en}. Fill with median/mean or dropna on key columns."},
                "action": {"view": "profile"},
            }
        )
    else:
        insights.append(
            {
                "id": "missing-none",
                "level": "good",
                "title": {"zh": "没有缺失值", "en": "No missing values"},
                "detail": {"zh": "当前数据完整，可以直接进入聚合与建模分析。", "en": "Data is complete — ready for aggregation and modelling."},
                "action": {"view": "profile"},
            }
        )

    duplicated = int(df.duplicated().sum())
    if duplicated:
        insights.append(
            {
                "id": "duplicates",
                "level": "warn",
                "title": {"zh": f"检测到 {duplicated:,} 行重复记录", "en": f"{duplicated:,} duplicated rows detected"},
                "detail": {"zh": "重复行会放大聚合结果，建议使用“删除重复行”算子处理。", "en": "Duplicates inflate aggregations — add the Drop Duplicates step."},
                "action": {"view": "pipeline", "op": "drop_duplicates"},
            }
        )

    numeric = numeric_columns(df)
    skew_candidates: list[tuple] = []
    outlier_candidates: list[tuple] = []
    for col in numeric[:14]:
        values = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(values) < 8:
            continue
        skew = float(values.skew())
        if abs(skew) > 1.2:
            skew_candidates.append((abs(skew), col, skew))
        stats = _box_stats(values)
        if stats and stats["outlier_count"] > 0 and stats["outlier_count"] / max(stats["n"], 1) > 0.01:
            outlier_candidates.append((stats["outlier_count"] / max(stats["n"], 1), col, stats))

    # 只保留最显著的几条，避免洞察列表被同类问题淹没
    for _, col, skew in sorted(skew_candidates, key=lambda item: item[0], reverse=True)[:3]:
        insights.append(
            {
                "id": f"skew-{col}",
                "level": "info",
                "title": {"zh": f"「{col}」分布明显偏斜 (偏度 {skew:.2f})", "en": f"'{col}' is strongly skewed (skew {skew:.2f})"},
                "detail": {
                    "zh": "偏斜数据用均值概括会失真，建议改看中位数，或先做对数变换再看分布。",
                    "en": "Mean is misleading for skewed data — use the median, or log-transform before plotting.",
                },
                "action": {"view": "chart", "chart": "histogram", "y": col},
            }
        )
    for ratio, col, stats in sorted(outlier_candidates, key=lambda item: item[0], reverse=True)[:3]:
        insights.append(
            {
                "id": f"outlier-{col}",
                "level": "info",
                "title": {"zh": f"「{col}」存在 {stats['outlier_count']:,} 个 IQR 异常值（{ratio:.1%}）", "en": f"'{col}' has {stats['outlier_count']:,} IQR outliers ({ratio:.1%})"},
                "detail": {
                    "zh": f"正常区间约为 [{_fmt(stats['low'])}, {_fmt(stats['high'])}]，超出部分可能是真实极值也可能是录入错误。",
                    "en": f"Expected range ≈ [{_fmt(stats['low'])}, {_fmt(stats['high'])}]; extremes may be real or data-entry errors.",
                },
                "action": {"view": "chart", "chart": "boxplot", "y": col},
            }
        )

    if len(numeric) >= 2:
        corr = df[numeric[:12]].apply(pd.to_numeric, errors="coerce").corr(numeric_only=True)
        pairs = []
        for i, a in enumerate(corr.columns):
            for b in corr.columns[i + 1 :]:
                value = corr.loc[a, b]
                if pd.notna(value):
                    pairs.append((a, b, float(value)))
        pairs.sort(key=lambda item: abs(item[2]), reverse=True)
        for a, b, r in pairs[:3]:
            if abs(r) < 0.55:
                continue
            level = "good"
            insights.append(
                {
                    "id": f"corr-{a}-{b}",
                    "level": level,
                    "title": {"zh": f"「{a}」与「{b}」强相关 r = {r:.2f}", "en": f"'{a}' vs '{b}' correlate at r = {r:.2f}"},
                    "detail": {
                        "zh": "相关不等于因果，但值得进一步用散点图观察结构（是否非线性 / 是否由分组造成）。",
                        "en": "Correlation is not causation, but it is worth checking the scatter for non-linearity or group effects.",
                    },
                    "action": {"view": "chart", "chart": "scatter", "x": a, "y": b, "fit": True},
                }
            )

    categorical = categorical_columns(df)
    for col in categorical[:6]:
        counts = df[col].value_counts(normalize=True, dropna=True)
        if len(counts) >= 2 and counts.iloc[-1] < 0.02 and len(counts) > 5:
            insights.append(
                {
                    "id": f"imbalance-{col}",
                    "level": "info",
                    "title": {"zh": f"「{col}」类别分布不均衡", "en": f"'{col}' is imbalanced"},
                    "detail": {
                        "zh": f"共有 {len(counts)} 个类别，最小类别仅占 {counts.iloc[-1]:.1%}，做分组对比时需注意样本量。",
                        "en": f"{len(counts)} categories, the smallest only {counts.iloc[-1]:.1%} — watch out for tiny groups.",
                    },
                    "action": {"view": "chart", "chart": "bar", "x": col},
                }
            )
        high_card = df[col].nunique(dropna=True)
        if high_card > 30:
            insights.append(
                {
                    "id": f"cardinality-{col}",
                    "level": "info",
                    "title": {"zh": f"「{col}」基数较高（{high_card} 个取值）", "en": f"'{col}' has high cardinality ({high_card} values)"},
                    "detail": {
                        "zh": "直接画条形图会很碎，建议先取 Top N 或按数值分箱再可视化。",
                        "en": "Bars will be fragmented — take Top N or bin the values before plotting.",
                    },
                    "action": {"view": "chart", "chart": "bar", "x": col, "topN": 12},
                }
            )

    date_cols = datetime_columns(df) or [c for c in df.columns if df[c].dtype == object and _looks_like_date(df[c])]
    if date_cols and numeric:
        date_col, value_col = date_cols[0], numeric[0]
        parsed = pd.to_datetime(df[date_col], errors="coerce")
        if parsed.notna().sum() > 5:
            ordered = df.assign(__date=parsed).dropna(subset=["__date"]).sort_values("__date")
            y = pd.to_numeric(ordered[value_col], errors="coerce")
            if y.notna().sum() > 5:
                x = np.arange(len(y), dtype=float)
                mask = y.notna()
                slope = np.polyfit(x[mask.to_numpy()], y[mask].to_numpy(dtype=float), 1)[0]
                direction = {"zh": "上升", "en": "upward"} if slope > 0 else {"zh": "下降", "en": "downward"}
                insights.append(
                    {
                        "id": f"trend-{value_col}",
                        "level": "info",
                        "title": {"zh": f"「{value_col}」随时间呈{direction['zh']}趋势", "en": f"'{value_col}' trends {'up' if slope > 0 else 'down'} over time"},
                        "detail": {
                            "zh": f"时间列为「{date_col}」，建议用重采样 + 滚动均值查看季节性与周期。",
                            "en": f"Time column is '{date_col}'. Try resampling with a rolling mean to expose seasonality.",
                        },
                        "action": {"view": "timeseries", "date": date_col, "value": value_col},
                    }
                )

    if numeric and categorical:
        value_col = numeric[0]
        best = None
        for col in categorical[:5]:
            groups = [g[value_col].dropna() for _, g in df.groupby(col, observed=True)]
            groups = [g for g in groups if len(g) >= 3][:6]
            if len(groups) >= 2 and _sps is not None:
                try:
                    _, p = _sps.f_oneway(*[g.to_numpy(dtype=float) for g in groups])
                except Exception:
                    continue
                spread = float(np.std([g.mean() for g in groups]) / (pd.to_numeric(df[value_col], errors="coerce").std() or 1))
                score = (1 - p) * spread
                if best is None or score > best[0]:
                    best = (score, col, p)
        if best and best[2] < 0.05:
            insights.append(
                {
                    "id": f"groupdiff-{best[1]}",
                    "level": "good",
                    "title": {"zh": f"按「{best[1]}」分组时「{value_col}」差异显著", "en": f"'{value_col}' differs significantly across '{best[1]}'"},
                    "detail": {
                        "zh": f"ANOVA p = {best[2]:.2g}，可视化上用分组箱线图 / 小提琴图最能体现差异。",
                        "en": f"ANOVA p = {best[2]:.2g}. Use grouped boxplots or violins to show it best.",
                    },
                    "action": {"view": "chart", "chart": "boxplot", "x": best[1], "y": value_col},
                }
            )

    level_weight = {"warn": 5, "info": 1, "good": 0}
    penalty = sum(level_weight[i["level"]] for i in insights)
    score = max(30, 100 - penalty)
    return {"insights": to_native(insights), "score": int(score)}


def _looks_like_date(series: pd.Series) -> bool:
    sample = series.dropna().head(20).astype(str)
    if sample.empty:
        return False
    return bool(sample.str.match(r"^\d{4}[-/]\d{1,2}([-/]\d{1,2})?").mean() > 0.8)
