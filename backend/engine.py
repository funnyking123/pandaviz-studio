"""pandas 操作管道引擎。

设计：前端把用户的可视化操作记录成一串 **算子步骤（steps）**，后端逐步在真实
pandas DataFrame 上执行，并同步生成**与该操作等价的 pandas 代码**。这样：

* 每一步都是真 pandas 计算（groupby / pivot_table / resample / rolling / merge ...）
* 每一步都能看到自己的行数变化（管道漏斗可视化）与代码（可复制、可导出脚本）
* 出错时能精确定位到具体步骤，并把 pandas 的报错原文回传
"""
from __future__ import annotations

import re
import time
from typing import Callable

import numpy as np
import pandas as pd

from .utils import classify_series, safe_float, to_native

# ---------------------------------------------------------------------------
# 常量与工具
# ---------------------------------------------------------------------------

AGG_FUNCS = ["sum", "mean", "count", "size", "median", "min", "max", "std", "var", "nunique", "first", "last"]

AGG_LABELS = {
    "sum": {"zh": "求和", "en": "Sum"},
    "mean": {"zh": "平均值", "en": "Mean"},
    "count": {"zh": "计数", "en": "Count"},
    "size": {"zh": "行数", "en": "Size"},
    "median": {"zh": "中位数", "en": "Median"},
    "min": {"zh": "最小值", "en": "Min"},
    "max": {"zh": "最大值", "en": "Max"},
    "std": {"zh": "标准差", "en": "Std"},
    "var": {"zh": "方差", "en": "Variance"},
    "nunique": {"zh": "去重计数", "en": "Nunique"},
    "first": {"zh": "首个值", "en": "First"},
    "last": {"zh": "末个值", "en": "Last"},
}

COMPARISON_OPS = [
    {"value": ">", "label": {"zh": "大于 >", "en": "Greater than >"}},
    {"value": ">=", "label": {"zh": "大于等于 ≥", "en": "Greater or equal >="}},
    {"value": "<", "label": {"zh": "小于 <", "en": "Less than <"}},
    {"value": "<=", "label": {"zh": "小于等于 ≤", "en": "Less or equal <="}},
    {"value": "==", "label": {"zh": "等于 =", "en": "Equal to =="}},
    {"value": "!=", "label": {"zh": "不等于 ≠", "en": "Not equal !="}},
    {"value": "between", "label": {"zh": "区间范围内", "en": "Between"}},
    {"value": "in", "label": {"zh": "属于集合", "en": "In list"}},
    {"value": "not_in", "label": {"zh": "不属于集合", "en": "Not in list"}},
    {"value": "contains", "label": {"zh": "包含文本", "en": "Contains text"}},
    {"value": "not_contains", "label": {"zh": "不包含文本", "en": "Not contains"}},
    {"value": "startswith", "label": {"zh": "以...开头", "en": "Starts with"}},
    {"value": "regex", "label": {"zh": "正则匹配", "en": "Regex match"}},
    {"value": "isna", "label": {"zh": "为空 (isna)", "en": "Is missing"}},
    {"value": "notna", "label": {"zh": "非空 (notna)", "en": "Not missing"}},
]

DATE_PARTS = [
    {"value": "year", "label": {"zh": "年", "en": "Year"}},
    {"value": "quarter", "label": {"zh": "季度", "en": "Quarter"}},
    {"value": "month", "label": {"zh": "月", "en": "Month"}},
    {"value": "month_name", "label": {"zh": "月份名称", "en": "Month name"}},
    {"value": "week", "label": {"zh": "周序号", "en": "Week"}},
    {"value": "day", "label": {"zh": "日", "en": "Day"}},
    {"value": "weekday", "label": {"zh": "星期(数字)", "en": "Weekday (int)"}},
    {"value": "weekday_name", "label": {"zh": "星期名称", "en": "Weekday name"}},
    {"value": "hour", "label": {"zh": "小时", "en": "Hour"}},
    {"value": "dayofyear", "label": {"zh": "年内第几天", "en": "Day of year"}},
]

RESAMPLE_FREQS = [
    {"value": "D", "label": {"zh": "按天", "en": "Daily"}},
    {"value": "W", "label": {"zh": "按周", "en": "Weekly"}},
    {"value": "M", "label": {"zh": "按月", "en": "Monthly"}},
    {"value": "Q", "label": {"zh": "按季度", "en": "Quarterly"}},
    {"value": "Y", "label": {"zh": "按年", "en": "Yearly"}},
]

_FREQ_ALIAS = {"M": "ME", "Q": "QE", "Y": "YE"}

_BANNED_EXPR = re.compile(
    r"(__|\bimport\b|\blambda\b|\bexec\b|\beval\b|\bopen\b|\bos\.|\bsys\.|subprocess|globals\(|locals\(|"
    r"getattr|setattr|\.system|\.apply|\.map\(|read_|to_csv|to_pickle|pickle|socket|urllib|requests|@)",
    re.IGNORECASE,
)


class PipelineError(Exception):
    """管道执行错误，包含出错步骤序号（0 起）。"""

    def __init__(self, step_index: int, message: str):
        super().__init__(message)
        self.step_index = step_index
        self.message = message


def quote(value) -> str:
    """生成 Python 字面量字符串，用于代码回显。"""
    if value is None:
        return "None"
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (float, np.floating)):
        return repr(float(value))
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


def qlist(values) -> str:
    return "[" + ", ".join(quote(v) for v in values) + "]"


def check_expression(expr: str, field: str = "expression") -> str:
    """拒绝危险表达式，保证 ``df.eval`` / ``df.query`` 只在数据上运算。"""
    expr = (expr or "").strip()
    if not expr:
        raise ValueError(f"empty {field}")
    if _BANNED_EXPR.search(expr):
        raise ValueError(f"unsafe {field}: only column arithmetic is allowed")
    return expr


def require(condition, message_zh: str, message_en: str):
    if not condition:
        raise ValueError(f"{message_zh} ｜ {message_en}")


def as_identifier(name: str) -> bool:
    return bool(re.match(r"^[^\W\d]\w*$", str(name), re.UNICODE))


def cast_scalar(series: pd.Series, raw):
    """把表单里的字符串按列类型转换，避免 '100' > 9 的字符串比较陷阱。"""
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None
    if isinstance(raw, bool):
        return raw
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return safe_float(raw, None)
    if pd.api.types.is_bool_dtype(series):
        return str(raw).strip().lower() in ("1", "true", "yes", "y", "是", "真")
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(raw, errors="coerce")
    return str(raw).strip()


def cast_list(series: pd.Series, raw) -> list:
    if isinstance(raw, (list, tuple)):
        items = [str(v) for v in raw]
    else:
        items = re.split(r"[,，;；\n]", str(raw or ""))
    items = [item.strip() for item in items if item.strip()]
    out = []
    for item in items:
        casted = cast_scalar(series, item)
        out.append(item if casted is None and not pd.api.types.is_numeric_dtype(series) else casted)
    return out


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            "_".join(str(part) for part in col if str(part) not in ("", "nan")) for col in df.columns
        ]
    df.columns = [str(c) for c in df.columns]
    return df


def _rename_clash(df: pd.DataFrame, old: str, new: str) -> pd.DataFrame:
    if new in df.columns and new != old:
        df = df.drop(columns=[new])
    return df


# ---------------------------------------------------------------------------
# 算子注册
# ---------------------------------------------------------------------------

OP_SPECS: dict[str, dict] = {}
OP_GROUPS = [
    {"id": "filter", "label": {"zh": "筛选与采样", "en": "Filter & Sample"}, "hint": {"zh": "缩小数据范围", "en": "Narrow down rows"}},
    {"id": "clean", "label": {"zh": "清洗与类型", "en": "Clean & Types"}, "hint": {"zh": "缺失值、重复值、类型转换", "en": "Missing, duplicates, dtypes"}},
    {"id": "shape", "label": {"zh": "重塑与派生", "en": "Reshape & Derive"}, "hint": {"zh": "计算列、分箱、编码", "en": "Assign, bin, encode"}},
    {"id": "group", "label": {"zh": "分组与聚合", "en": "Group & Aggregate"}, "hint": {"zh": "groupby / pivot / crosstab", "en": "groupby / pivot / crosstab"}},
    {"id": "time", "label": {"zh": "时间序列", "en": "Time Series"}, "hint": {"zh": "重采样、滚动窗口", "en": "Resample, rolling"}},
    {"id": "combine", "label": {"zh": "多表合并", "en": "Combine Tables"}, "hint": {"zh": "merge / concat", "en": "merge / concat"}},
    {"id": "visual", "label": {"zh": "图形筛选", "en": "Visual Filter"}, "hint": {"zh": "由图表点击 / 刷选自动生成", "en": "Generated by chart click / brush"}},
]


def register(op_id: str, label_zh: str, label_en: str, group: str, params: list[dict], hint_zh: str = "", hint_en: str = ""):
    def decorator(fn: Callable):
        OP_SPECS[op_id] = {
            "id": op_id,
            "label": {"zh": label_zh, "en": label_en},
            "group": group,
            "hint": {"zh": hint_zh or label_zh, "en": hint_en or label_en},
            "params": params,
            "fn": fn,
        }
        return fn

    return decorator


def P(name: str, ptype: str, label_zh: str, label_en: str, **extra) -> dict:
    spec = {"name": name, "type": ptype, "label": {"zh": label_zh, "en": label_en}}
    spec.update(extra)
    return spec


COLUMN_PARAM = lambda name="column", **kw: P(name, "column", "列", "Column", **kw)  # noqa: E731

# ------------------------------ 筛选与采样 --------------------------------

@register(
    "filter_row",
    "条件筛选",
    "Row Filter",
    "filter",
    [
        COLUMN_PARAM(required=True),
        P("operator", "select", "运算符", "Operator", options=COMPARISON_OPS, default=">"),
        # 「值」除了 isna / notna 之外都需要填；「值2」只在“区间范围内”时才需要
        P("value", "text", "值", "Value", false_ops=["isna", "notna"]),
        P("value2", "text", "值2（区间上界）", "Value 2 (upper bound)", ops=["between"]),
    ],
    hint_zh="等价于 df = df[df['列'] 条件 值]",
    hint_en="Equivalent to df = df[df['col'] cond value]",
)
def _op_filter_row(df, p, ctx):
    column = p.get("column")
    require(column in df.columns, f"列 {column} 不存在", f"column {column} not found")
    series = df[column]
    op = p.get("operator") or "=="
    value, value2 = p.get("value"), p.get("value2")
    col_code = f"df[{quote(column)}]"

    if op == "isna":
        mask, code = series.isna(), f"df = df[{col_code}.isna()]"
    elif op == "notna":
        mask, code = series.notna(), f"df = df[{col_code}.notna()]"
    elif op in (">", ">=", "<", "<=", "==", "!="):
        casted = cast_scalar(series, value)
        require(casted is not None, "请填写用于比较的值", "please provide a comparison value")
        if op == "==":
            mask = series == casted
        elif op == "!=":
            mask = series != casted
        elif op == ">":
            mask = series > casted
        elif op == ">=":
            mask = series >= casted
        elif op == "<":
            mask = series < casted
        else:
            mask = series <= casted
        code = f"df = df[{col_code} {op} {quote(casted)}]"
    elif op == "between":
        low, high = cast_scalar(series, value), cast_scalar(series, value2)
        require(low is not None and high is not None, "请填写区间上下界", "please provide both bounds")
        if low > high:
            low, high = high, low
        mask, code = series.between(low, high), f"df = df[{col_code}.between({quote(low)}, {quote(high)})]"
    elif op in ("in", "not_in"):
        values = cast_list(series, value)
        require(values, "请填写集合元素（逗号分隔）", "please provide list values")
        mask = series.isin(values)
        if op == "not_in":
            mask = ~mask
        fname = "isin" if op == "in" else "isin"
        prefix = "" if op == "in" else "~"
        code = f"df = df[{prefix}{col_code}.{fname}({qlist(values)})]"
    elif op in ("contains", "not_contains", "startswith", "regex"):
        text = str(value if value is not None else "")
        require(text != "", "请填写文本", "please provide text")
        if op == "contains":
            mask, code = series.astype("string").str.contains(text, case=False, na=False), f"df = df[{col_code}.str.contains({quote(text)}, case=False, na=False)]"
        elif op == "not_contains":
            mask, code = ~series.astype("string").str.contains(text, case=False, na=False), f"df = df[~{col_code}.str.contains({quote(text)}, case=False, na=False)]"
        elif op == "startswith":
            mask, code = series.astype("string").str.startswith(text, na=False), f"df = df[{col_code}.str.startswith({quote(text)}, na=False)]"
        else:
            check_expression(text, "regex")
            mask, code = series.astype("string").str.contains(text, regex=True, na=False), f"df = df[{col_code}.str.contains({quote(text)}, regex=True, na=False)]"
    else:
        raise ValueError(f"unknown operator {op}")

    out = df[mask.fillna(False)].copy()
    return out, code


@register(
    "filter_query",
    "表达式筛选 (query)",
    "Query Filter",
    "filter",
    [P("expr", "textarea", "查询表达式", "Query expression", placeholder="销售额 > 5000 and 品类 == '电子产品'")],
    hint_zh="直接使用 pandas.query 语法，支持 and / or / in / between",
    hint_en="Use pandas.query syntax with and / or / in / between",
)
def _op_filter_query(df, p, ctx):
    expr = check_expression(p.get("expr"), "query")
    out = df.query(expr, engine="python").copy()
    return out, f"df = df.query({quote(expr)})"


@register(
    "sample_rows",
    "随机抽样",
    "Random Sample",
    "filter",
    [
        P("n", "number", "抽样行数", "Rows to sample", default=300, min=1),
        P("random_state", "number", "随机种子", "Random seed", default=42),
        P("replace", "bool", "允许重复抽样", "With replacement", default=False),
    ],
    hint_zh="等价于 df.sample(n=..., random_state=...)",
    hint_en="Equivalent to df.sample(n=..., random_state=...)",
)
def _op_sample(df, p, ctx):
    n = int(p.get("n") or 300)
    seed = int(p.get("random_state") or 42)
    replace = bool(p.get("replace"))
    effective = n if replace else min(n, len(df))
    out = df.sample(n=effective, random_state=seed, replace=replace).reset_index(drop=True)
    return out, f"df = df.sample(n={effective}, random_state={seed}, replace={str(replace)})"


@register(
    "head_rows",
    "取前 N 行 / 后 N 行",
    "Head / Tail",
    "filter",
    [
        P("mode", "select", "方向", "Direction", options=[{"value": "head", "label": {"zh": "前 N 行", "en": "First N"}}, {"value": "tail", "label": {"zh": "后 N 行", "en": "Last N"}}], default="head"),
        P("n", "number", "行数", "Rows", default=100, min=1),
    ],
)
def _op_head(df, p, ctx):
    n = int(p.get("n") or 100)
    mode = p.get("mode") or "head"
    out = (df.head(n) if mode == "head" else df.tail(n)).reset_index(drop=True)
    return out, f"df = df.{mode}({n})"


# ------------------------------ 清洗与类型 --------------------------------

@register(
    "dropna",
    "删除缺失值",
    "Drop Missing",
    "clean",
    [
        P("subset", "columns", "检查的列", "Columns to check", allow_empty=True),
        P("how", "select", "判定方式", "How", options=[{"value": "any", "label": {"zh": "任一为空即删", "en": "Drop if any null"}}, {"value": "all", "label": {"zh": "全部为空才删", "en": "Drop if all null"}}], default="any"),
    ],
)
def _op_dropna(df, p, ctx):
    subset = [c for c in (p.get("subset") or []) if c in df.columns] or None
    how = p.get("how") or "any"
    out = df.dropna(subset=subset, how=how).reset_index(drop=True)
    subset_code = "None" if subset is None else qlist(subset)
    return out, f"df = df.dropna(subset={subset_code}, how={quote(how)})"


@register(
    "fillna",
    "填充缺失值",
    "Fill Missing",
    "clean",
    [
        COLUMN_PARAM(required=True),
        P(
            "method",
            "select",
            "填充方式",
            "Method",
            options=[
                {"value": "value", "label": {"zh": "固定值", "en": "Fixed value"}},
                {"value": "mean", "label": {"zh": "均值", "en": "Mean"}},
                {"value": "median", "label": {"zh": "中位数", "en": "Median"}},
                {"value": "mode", "label": {"zh": "众数", "en": "Mode"}},
                {"value": "ffill", "label": {"zh": "前向填充", "en": "Forward fill"}},
                {"value": "bfill", "label": {"zh": "后向填充", "en": "Backward fill"}},
                {"value": "interpolate", "label": {"zh": "线性插值", "en": "Interpolate"}},
            ],
            default="mean",
        ),
        P("value", "text", "固定值", "Fixed value", depends={"method": ["value"]}),
    ],
)
def _op_fillna(df, p, ctx):
    column, method = p.get("column"), p.get("method") or "mean"
    require(column in df.columns, f"列 {column} 不存在", f"column {column} not found")
    series = df[column]
    if method in ("mean", "median"):
        require(
            pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series),
            "均值/中位数填充只适用于数值列，请改用众数或前向填充",
            "mean/median fill needs a numeric column — use mode/ffill instead",
        )
    out = df.copy()
    if method == "value":
        raw = p.get("value")
        if pd.api.types.is_numeric_dtype(series):
            value = safe_float(raw, 0.0)
        else:
            value = "" if raw is None else str(raw)
        out[column] = series.fillna(value)
        code = f"df[{quote(column)}] = df[{quote(column)}].fillna({quote(value)})"
    elif method == "mode":
        mode = series.mode(dropna=True)
        value = mode.iloc[0] if len(mode) else None
        out[column] = series.fillna(value)
        code = f"df[{quote(column)}] = df[{quote(column)}].fillna(df[{quote(column)}].mode().iloc[0])"
    else:
        fname = {"mean": "mean", "median": "median", "ffill": "ffill", "bfill": "bfill", "interpolate": "interpolate"}[method]
        filled = series.ffill() if method == "ffill" else series.bfill() if method == "bfill" else series.interpolate(limit_direction="both")
        if method in ("mean", "median"):
            filled = series.fillna(getattr(series, method)())
            code = f"df[{quote(column)}] = df[{quote(column)}].fillna(df[{quote(column)}].{method}())"
        else:
            code = f"df[{quote(column)}] = df[{quote(column)}].{fname}()"
        out[column] = filled
    return out, code


@register(
    "drop_duplicates",
    "删除重复行",
    "Drop Duplicates",
    "clean",
    [
        P("subset", "columns", "判重依据列", "Subset columns", allow_empty=True),
        P("keep", "select", "保留策略", "Keep", options=[{"value": "first", "label": {"zh": "保留第一条", "en": "First"}}, {"value": "last", "label": {"zh": "保留最后一条", "en": "Last"}}, {"value": False, "label": {"zh": "全部删除", "en": "Drop all"}}], default="first"),
    ],
)
def _op_drop_duplicates(df, p, ctx):
    subset = [c for c in (p.get("subset") or []) if c in df.columns] or None
    keep = p.get("keep", "first")
    if keep in ("false", "False", False):
        keep = False
    elif keep == "last":
        keep = "last"
    else:
        keep = "first"
    out = df.drop_duplicates(subset=subset, keep=keep).reset_index(drop=True)
    subset_code = "None" if subset is None else qlist(subset)
    return out, f"df = df.drop_duplicates(subset={subset_code}, keep={quote(keep)})"


@register(
    "astype",
    "类型转换 (astype)",
    "Cast Type",
    "clean",
    [
        COLUMN_PARAM(required=True),
        P(
            "dtype",
            "select",
            "目标类型",
            "Target dtype",
            options=[
                {"value": "float", "label": {"zh": "浮点数 float", "en": "float"}},
                {"value": "int", "label": {"zh": "整数 Int64", "en": "Int64"}},
                {"value": "str", "label": {"zh": "文本 string", "en": "string"}},
                {"value": "category", "label": {"zh": "类别 category", "en": "category"}},
                {"value": "bool", "label": {"zh": "布尔 boolean", "en": "boolean"}},
                {"value": "datetime", "label": {"zh": "日期时间 datetime", "en": "datetime"}},
            ],
            default="str",
        ),
    ],
)
def _op_astype(df, p, ctx):
    column, dtype = p.get("column"), p.get("dtype") or "str"
    require(column in df.columns, f"列 {column} 不存在", f"column {column} not found")
    out = df.copy()
    if dtype == "float":
        out[column] = pd.to_numeric(out[column], errors="coerce").astype("float64")
        code = f"df[{quote(column)}] = pd.to_numeric(df[{quote(column)}], errors='coerce')"
    elif dtype == "int":
        out[column] = pd.to_numeric(out[column], errors="coerce").round().astype("Int64")
        code = f"df[{quote(column)}] = pd.to_numeric(df[{quote(column)}], errors='coerce').round().astype('Int64')"
    elif dtype == "category":
        out[column] = out[column].astype("category")
        code = f"df[{quote(column)}] = df[{quote(column)}].astype('category')"
    elif dtype == "bool":
        out[column] = out[column].astype(str).str.strip().str.lower().isin(["1", "true", "yes", "是", "真"])
        code = f"df[{quote(column)}] = df[{quote(column)}].astype(str).isin(['1', 'true', 'yes'])"
    elif dtype == "datetime":
        out[column] = pd.to_datetime(out[column], errors="coerce")
        code = f"df[{quote(column)}] = pd.to_datetime(df[{quote(column)}], errors='coerce')"
    else:
        out[column] = out[column].astype("string")
        code = f"df[{quote(column)}] = df[{quote(column)}].astype('string')"
    return out, code


@register(
    "outlier",
    "异常值处理",
    "Outlier Handling",
    "clean",
    [
        COLUMN_PARAM(required=True, kinds=["numeric"]),
        P("method", "select", "检测方法", "Method", options=[{"value": "iqr", "label": {"zh": "IQR 四分位法", "en": "IQR rule"}}, {"value": "zscore", "label": {"zh": "Z-Score (±3σ)", "en": "Z-Score (±3σ)"}}, {"value": "quantile", "label": {"zh": "分位数裁剪", "en": "Quantile clip"}}], default="iqr"),
        P("action", "select", "处理方式", "Action", options=[{"value": "remove", "label": {"zh": "删除异常行", "en": "Remove rows"}}, {"value": "clip", "label": {"zh": "截断到边界", "en": "Clip to bounds"}}], default="remove"),
        P("k", "number", "阈值倍数 k", "Threshold k", default=1.5),
    ],
)
def _op_outlier(df, p, ctx):
    column = p.get("column")
    method = p.get("method") or "iqr"
    action = p.get("action") or "remove"
    k = safe_float(p.get("k"), 1.5) or 1.5
    series = pd.to_numeric(df[column], errors="coerce")
    if method == "iqr":
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        low, high = q1 - k * iqr, q3 + k * iqr
        code_head = (
            f"_q1, _q3 = df[{quote(column)}].quantile(0.25), df[{quote(column)}].quantile(0.75)\n"
            f"_iqr = _q3 - _q1\n"
            f"_low, _high = _q1 - {k} * _iqr, _q3 + {k} * _iqr"
        )
    elif method == "zscore":
        mean, std = series.mean(), series.std()
        low, high = mean - k * std, mean + k * std
        code_head = (
            f"_mean, _std = df[{quote(column)}].mean(), df[{quote(column)}].std()\n"
            f"_low, _high = _mean - {k} * _std, _mean + {k} * _std"
        )
    else:
        q = safe_float(p.get("k"), 0.01) or 0.01
        low, high = series.quantile(q), series.quantile(1 - q)
        code_head = f"_low, _high = df[{quote(column)}].quantile({q}), df[{quote(column)}].quantile({1 - q})"

    low = 0.0 if pd.isna(low) else float(low)
    high = 0.0 if pd.isna(high) else float(high)
    if action == "clip":
        out = df.copy()
        out[column] = series.clip(low, high)
        code = f"{code_head}\ndf[{quote(column)}] = df[{quote(column)}].clip(_low, _high)"
    else:
        out = df[series.between(low, high)].copy()
        code = f"{code_head}\ndf = df[df[{quote(column)}].between(_low, _high)]"
    return out, code


# ------------------------------ 重塑与派生 --------------------------------

@register(
    "assign_expr",
    "计算新列 (assign)",
    "Assign New Column",
    "shape",
    [
        P("name", "text", "新列名", "New column", required=True),
        P("expr", "textarea", "计算表达式", "Expression", placeholder="利润 / 销售额 * 100", required=True),
    ],
    hint_zh="使用 df.eval 逐行计算，支持 + - * / 与列名",
    hint_en="Row-wise maths via df.eval, supports + - * / and column names",
)
def _op_assign(df, p, ctx):
    name = str(p.get("name") or "").strip()
    require(name, "请填写新列名", "please provide a new column name")
    expr = check_expression(p.get("expr"), "expression")
    if as_identifier(name):
        out = _flatten_columns(pd.DataFrame(df.eval(f"{name} = {expr}", engine="python")))
        code = f"df = df.eval({quote(f'{name} = {expr}')}, engine='python')"
    else:
        out = df.copy()
        out[name] = df.eval(expr, engine="python")
        code = f"df[{quote(name)}] = df.eval({quote(expr)}, engine='python')"
    return out, code


@register(
    "bin_numeric",
    "数值分箱 (cut / qcut)",
    "Numeric Binning",
    "shape",
    [
        COLUMN_PARAM(required=True, kinds=["numeric"]),
        P("method", "select", "分箱方式", "Method", options=[{"value": "equal_width", "label": {"zh": "等宽分箱 cut", "en": "Equal width (cut)"}}, {"value": "quantile", "label": {"zh": "等频分箱 qcut", "en": "Equal frequency (qcut)"}}], default="equal_width"),
        P("bins", "number", "箱数", "Bins", default=4, min=2),
        P("new_name", "text", "新列名", "New column", placeholder="留空自动命名"),
    ],
)
def _op_bin(df, p, ctx):
    column = p.get("column")
    bins = int(p.get("bins") or 4)
    method = p.get("method") or "equal_width"
    new_name = str(p.get("new_name") or "").strip() or f"{column}_分箱"
    out = df.copy()
    if method == "quantile":
        binned = pd.qcut(pd.to_numeric(out[column], errors="coerce"), q=bins, duplicates="drop")
        code = f"df[{quote(new_name)}] = pd.qcut(df[{quote(column)}], q={bins}, duplicates='drop')"
    else:
        binned = pd.cut(pd.to_numeric(out[column], errors="coerce"), bins=bins)
        code = f"df[{quote(new_name)}] = pd.cut(df[{quote(column)}], bins={bins})"
    out[new_name] = binned.astype(str)
    return out, code


@register(
    "extract_datetime",
    "日期特征提取",
    "Extract Date Parts",
    "shape",
    [
        COLUMN_PARAM(required=True, kinds=["datetime"]),
        P("parts", "multi_select", "提取字段", "Parts", options=DATE_PARTS, default=["year", "month", "weekday_name"]),
    ],
)
def _op_extract_dt(df, p, ctx):
    column = p.get("column")
    parts = p.get("parts") or ["year", "month"]
    part_names = {
        "year": "年",
        "month": "月",
        "week": "周",
        "day": "日",
        "hour": "小时",
        "quarter": "季度",
        "weekday": "星期序号",
        "dayofyear": "年内序",
    }
    out = df.copy()
    dt = pd.to_datetime(out[column], errors="coerce")
    lines = []
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for part in parts:
        if part == "month_name":
            new_col = f"{column}_月份"
            out[new_col] = dt.dt.month
            lines.append(f"df[{quote(new_col)}] = df[{quote(column)}].dt.month")
        elif part == "weekday_name":
            new_col = f"{column}_星期"
            out[new_col] = dt.dt.weekday.map(lambda i: weekday_names[int(i)] if pd.notna(i) else None)
            lines.append(
                f"df[{quote(new_col)}] = df[{quote(column)}].dt.weekday.map(lambda i: "
                f"{qlist(weekday_names)}[int(i)])"
            )
        elif part in part_names:
            new_col = f"{column}_{part_names[part]}"
            out[new_col] = getattr(dt.dt, part)
            lines.append(f"df[{quote(new_col)}] = df[{quote(column)}].dt.{part}")
    return out, "\n".join(lines) if lines else "# 未选择任何日期字段"


@register(
    "select_columns",
    "选择 / 删除列",
    "Select / Drop Columns",
    "shape",
    [
        P("columns", "columns", "涉及的列", "Columns", required=True),
        P("mode", "select", "操作", "Mode", options=[{"value": "keep", "label": {"zh": "只保留这些列", "en": "Keep only"}}, {"value": "drop", "label": {"zh": "删除这些列", "en": "Drop"}}], default="keep"),
    ],
)
def _op_select_columns(df, p, ctx):
    columns = [c for c in (p.get("columns") or []) if c in df.columns]
    require(columns, "请至少选择一列", "please select at least one column")
    mode = p.get("mode") or "keep"
    if mode == "drop":
        out = df.drop(columns=columns)
        code = f"df = df.drop(columns={qlist(columns)})"
    else:
        out = df[columns].copy()
        code = f"df = df[{qlist(columns)}].copy()"
    return out, code


@register(
    "rename_columns",
    "列重命名",
    "Rename Columns",
    "shape",
    [P("old", "column", "原列名", "Old name", required=True), P("new", "text", "新列名", "New name", required=True)],
)
def _op_rename(df, p, ctx):
    old, new = p.get("old"), str(p.get("new") or "").strip()
    require(old in df.columns and new, "请填写原列名与新列名", "please provide both names")
    out = df.rename(columns={old: new})
    return out, f"df = df.rename(columns={{{quote(old)}: {quote(new)}}})"


@register(
    "sort_values",
    "排序",
    "Sort Values",
    "shape",
    [
        P("by", "columns", "排序列", "Sort by", required=True),
        P("ascending", "bool", "升序", "Ascending", default=False),
        P("rank_col", "text", "生成排序列名", "Rank column name", placeholder="留空不生成排名列"),
        P("rank_method", "select", "排名方法", "Rank method", options=[{"value": "dense", "label": {"zh": "密集排名 dense", "en": "Dense"}}, {"value": "min", "label": {"zh": "并列最小 min", "en": "Min"}}, {"value": "average", "label": {"zh": "并列取平均 average", "en": "Average"}}, {"value": "first", "label": {"zh": "按出现顺序 first", "en": "First"}}], default="dense"),
    ],
)
def _op_sort(df, p, ctx):
    by = [c for c in (p.get("by") or []) if c in df.columns]
    require(by, "请选择排序列", "please select sort columns")
    ascending = bool(p.get("ascending"))
    out = df.sort_values(by=by, ascending=ascending).reset_index(drop=True)
    code = f"df = df.sort_values(by={qlist(by)}, ascending={str(ascending)}).reset_index(drop=True)"
    rank_col = str(p.get("rank_col") or "").strip()
    if rank_col and len(by) == 1:
        method = p.get("rank_method") or "dense"
        out[rank_col] = out[by[0]].rank(ascending=ascending, method=method)
        code += f"\ndf[{quote(rank_col)}] = df[{quote(by[0])}].rank(ascending={str(ascending)}, method={quote(method)})"
    return out, code


@register(
    "standardize",
    "标准化 / 归一化",
    "Standardize / Normalize",
    "shape",
    [
        P("columns", "columns", "数值列", "Numeric columns", required=True, kinds=["numeric"]),
        P("method", "select", "方法", "Method", options=[{"value": "zscore", "label": {"zh": "Z-Score 标准化", "en": "Z-Score"}}, {"value": "minmax", "label": {"zh": "Min-Max 归一化", "en": "Min-Max"}}], default="zscore"),
        P("suffix", "text", "新列后缀", "Suffix", default="_标准化"),
    ],
)
def _op_standardize(df, p, ctx):
    columns = [c for c in (p.get("columns") or []) if c in df.columns]
    require(columns, "请选择数值列", "please select numeric columns")
    method = p.get("method") or "zscore"
    suffix = str(p.get("suffix") or ("_标准化" if method == "zscore" else "_归一化"))
    out = df.copy()
    lines = []
    for col in columns:
        series = pd.to_numeric(out[col], errors="coerce")
        if method == "zscore":
            std = series.std()
            out[f"{col}{suffix}"] = (series - series.mean()) / (std if std and not pd.isna(std) else 1)
            lines.append(f"df[{quote(col + suffix)}] = (df[{quote(col)}] - df[{quote(col)}].mean()) / df[{quote(col)}].std()")
        else:
            span = series.max() - series.min()
            out[f"{col}{suffix}"] = (series - series.min()) / (span if span and not pd.isna(span) else 1)
            lines.append(f"df[{quote(col + suffix)}] = (df[{quote(col)}] - df[{quote(col)}].min()) / (df[{quote(col)}].max() - df[{quote(col)}].min())")
    return out, "\n".join(lines)


@register(
    "one_hot",
    "独热编码 (get_dummies)",
    "One-Hot Encode",
    "shape",
    [
        P("columns", "columns", "类别列", "Categorical columns", required=True),
        P("max_levels", "number", "最多保留类别数", "Max levels", default=20, min=2),
        P("drop_first", "bool", "丢弃第一个哑变量", "Drop first", default=False),
    ],
)
def _op_one_hot(df, p, ctx):
    columns = [c for c in (p.get("columns") or []) if c in df.columns]
    require(columns, "请选择类别列", "please select categorical columns")
    max_levels = int(p.get("max_levels") or 20)
    drop_first = bool(p.get("drop_first"))
    frames = [df]
    lines = []
    for col in columns:
        dummies = pd.get_dummies(df[col].astype("string"), prefix=col, dtype=int)
        if dummies.shape[1] > max_levels:
            dummies = dummies.iloc[:, :max_levels]
        if drop_first and dummies.shape[1] > 1:
            dummies = dummies.iloc[:, 1:]
        frames.append(dummies)
        lines.append(
            f"df = pd.concat([df, pd.get_dummies(df[{quote(col)}], prefix={quote(col)}, dtype=int)], axis=1)"
        )
    out = pd.concat(frames, axis=1)
    out = out.loc[:, ~out.columns.duplicated()]
    return out, "\n".join(lines)


@register(
    "melt_wide",
    "宽表转长表 (melt)",
    "Melt Wide to Long",
    "shape",
    [
        P("id_vars", "columns", "标识列", "Identifier columns", required=True),
        P("value_vars", "columns", "数值列", "Value columns", allow_empty=True, kinds=["numeric"]),
        P("var_name", "text", "指标列名", "Variable name", default="指标"),
        P("value_name", "text", "数值列名", "Value name", default="数值"),
    ],
)
def _op_melt(df, p, ctx):
    id_vars = [c for c in (p.get("id_vars") or []) if c in df.columns]
    require(id_vars, "请选择标识列", "please select identifier columns")
    value_vars = [c for c in (p.get("value_vars") or []) if c in df.columns] or [c for c in df.columns if c not in id_vars]
    var_name = str(p.get("var_name") or "指标")
    value_name = str(p.get("value_name") or "数值")
    out = df.melt(id_vars=id_vars, value_vars=value_vars, var_name=var_name, value_name=value_name)
    return out, (
        f"df = df.melt(id_vars={qlist(id_vars)}, value_vars={qlist(value_vars)}, "
        f"var_name={quote(var_name)}, value_name={quote(value_name)})"
    )


# ------------------------------ 分组与聚合 --------------------------------

@register(
    "groupby_agg",
    "分组聚合 (groupby.agg)",
    "Group & Aggregate",
    "group",
    [
        P("by", "columns", "分组列", "Group by", required=True),
        P("aggs", "agg_list", "聚合指标", "Aggregations", required=True),
    ],
    hint_zh="groupby + agg，是最常用的 pandas 分析动作",
    hint_en="groupby + agg — the workhorse of pandas analysis",
)
def _op_groupby(df, p, ctx):
    by = [c for c in (p.get("by") or []) if c in df.columns]
    require(by, "请选择分组列", "please select group columns")
    aggs = [a for a in (p.get("aggs") or []) if a.get("column") in df.columns or a.get("how") == "size"]
    require(aggs, "请至少配置一个聚合指标", "please configure at least one aggregation")
    spec: dict[str, tuple] = {}
    for item in aggs:
        how = item.get("how") or "sum"
        if how not in AGG_FUNCS:
            raise ValueError(f"unsupported aggregation {how}")
        alias = str(item.get("new_name") or "").strip() or (
            f"{item.get('column')}_{how}" if how != "size" else "行数"
        )
        spec[alias] = (item.get("column"), how) if how != "size" else (by[0], "size")
    out = df.groupby(by, dropna=False, as_index=False, observed=True).agg(**spec)
    out = _flatten_columns(out)
    kw = ", ".join(
        f"{alias}=({quote(pair[0])}, {quote(pair[1])})" if as_identifier(alias) else f"**{{{quote(alias)}: ({quote(pair[0])}, {quote(pair[1])})}}"
        for alias, pair in spec.items()
    )
    if all(as_identifier(alias) for alias in spec):
        code = f"df = df.groupby({qlist(by)}, dropna=False, as_index=False).agg({kw})"
    else:
        dict_repr = ", ".join(f"{quote(alias)}: ({quote(pair[0])}, {quote(pair[1])})" for alias, pair in spec.items())
        code = f"df = df.groupby({qlist(by)}, dropna=False, as_index=False).agg(**{{{dict_repr}}})"
    return out, code


@register(
    "pivot_table",
    "透视表 (pivot_table)",
    "Pivot Table",
    "group",
    [
        P("index", "columns", "行索引", "Index", required=True),
        P("columns", "column", "列字段", "Columns", allow_empty=True),
        P("values", "column", "数值字段", "Values", required=True),
        P("aggfunc", "select", "聚合函数", "Aggfunc", options=[{"value": k, "label": v} for k, v in AGG_LABELS.items()], default="sum"),
        P("fill_value", "number", "缺失填充值", "Fill value", default=0),
        P("margins", "bool", "显示总计", "Show margins", default=False),
    ],
)
def _op_pivot(df, p, ctx):
    index = [c for c in (p.get("index") or []) if c in df.columns]
    require(index, "请选择行索引列", "please select index columns")
    columns = p.get("columns") or None
    values = p.get("values")
    require(values in df.columns, "请选择数值字段", "please select a value column")
    require(columns not in index, "列字段不能与行索引字段重复", "columns must differ from the index fields")
    require(values not in index, "数值字段不能与行索引字段重复", "values must differ from the index fields")
    aggfunc = p.get("aggfunc") or "sum"
    fill_value = safe_float(p.get("fill_value"), 0)
    margins = bool(p.get("margins"))
    out = pd.pivot_table(
        df,
        index=index,
        columns=columns,
        values=values,
        aggfunc=aggfunc,
        fill_value=fill_value,
        margins=margins,
        observed=True,
    )
    out = _flatten_columns(out.reset_index())
    code = (
        f"df = df.pivot_table(index={qlist(index)}, columns={quote(columns) if columns else 'None'}, "
        f"values={quote(values)}, aggfunc={quote(aggfunc)}, fill_value={fill_value}, "
        f"margins={str(margins)}).reset_index()"
    )
    return out, code


@register(
    "crosstab",
    "交叉表 (crosstab)",
    "Crosstab",
    "group",
    [
        P("index", "column", "行变量", "Row variable", required=True),
        P("columns", "column", "列变量", "Column variable", required=True),
        P("normalize", "select", "归一化", "Normalize", options=[{"value": "none", "label": {"zh": "计数", "en": "Counts"}}, {"value": "index", "label": {"zh": "按行占比", "en": "Row %"}}, {"value": "columns", "label": {"zh": "按列占比", "en": "Column %"}}, {"value": "all", "label": {"zh": "总体占比", "en": "Overall %"}}], default="none"),
        P("values", "column", "数值列(可选)", "Values (optional)", allow_empty=True, kinds=["numeric"]),
        P("aggfunc", "select", "聚合函数", "Aggfunc", options=[{"value": "mean", "label": AGG_LABELS["mean"]}, {"value": "sum", "label": AGG_LABELS["sum"]}, {"value": "count", "label": AGG_LABELS["count"]}], default="mean"),
    ],
)
def _op_crosstab(df, p, ctx):
    index, columns = p.get("index"), p.get("columns")
    require(index in df.columns and columns in df.columns, "请选择行/列变量", "please select row/column variables")
    require(index != columns, "行变量与列变量不能相同", "row and column variables must differ")
    norm = p.get("normalize") or "none"
    normalize = False if norm == "none" else norm
    values = p.get("values") if p.get("values") in df.columns else None
    aggfunc = p.get("aggfunc") or "mean"
    out = pd.crosstab(
        df[index],
        df[columns],
        values=df[values] if values else None,
        aggfunc=aggfunc if values else None,
        normalize=normalize,
    )
    out = _flatten_columns(out.reset_index())
    if values:
        code = (
            f"df = pd.crosstab(df[{quote(index)}], df[{quote(columns)}], values=df[{quote(values)}], "
            f"aggfunc={quote(aggfunc)}, normalize={quote(normalize)}).reset_index()"
        )
    else:
        code = (
            f"df = pd.crosstab(df[{quote(index)}], df[{quote(columns)}], "
            f"normalize={quote(normalize)}).reset_index()"
        )
    return out, code


@register(
    "value_counts",
    "频次统计 (value_counts)",
    "Frequency Count",
    "group",
    [
        COLUMN_PARAM(required=True),
        P("normalize", "bool", "输出占比", "Return proportions", default=False),
        P("dropna", "bool", "统计缺失值", "Include missing", default=False),
        P("top_n", "number", "仅保留前 N 项", "Top N", default=0),
    ],
)
def _op_value_counts(df, p, ctx):
    column = p.get("column")
    require(column in df.columns, f"列 {column} 不存在", f"column {column} not found")
    normalize = bool(p.get("normalize"))
    dropna = bool(p.get("dropna"))
    vc = df[column].value_counts(normalize=normalize, dropna=not dropna)
    top_n = int(p.get("top_n") or 0)
    if top_n > 0:
        vc = vc.head(top_n)
    out = vc.rename_axis(column).reset_index(name="占比" if normalize else "计数")
    code = f"df = df[{quote(column)}].value_counts(normalize={str(normalize)}, dropna={str(not dropna)}).reset_index(name={quote('占比' if normalize else '计数')})"
    if top_n > 0:
        code += f".head({top_n})"
    return out, code


# -------------------------------- 时间序列 --------------------------------

@register(
    "resample",
    "时间重采样 (resample)",
    "Resample Time Series",
    "time",
    [
        P("column", "column", "日期列", "Date column", required=True, kinds=["datetime"]),
        P("freq", "select", "频率", "Frequency", options=RESAMPLE_FREQS, default="M"),
        P("group_by", "column", "分组列(可选)", "Group by (optional)", allow_empty=True),
        P("aggs", "agg_list", "聚合指标", "Aggregations", required=True),
    ],
)
def _op_resample(df, p, ctx):
    column = p.get("column")
    require(column in df.columns, f"列 {column} 不存在", f"column {column} not found")
    freq = p.get("freq") or "M"
    group_col = p.get("group_by") or None
    aggs = [a for a in (p.get("aggs") or []) if a.get("column") in df.columns]
    require(aggs, "请配置聚合指标", "please configure aggregations")
    working = df.copy()
    working[column] = pd.to_datetime(working[column], errors="coerce")
    working = working.dropna(subset=[column])
    spec = {}
    for item in aggs:
        how = item.get("how") or "mean"
        alias = str(item.get("new_name") or "").strip() or f"{item.get('column')}_{how}"
        spec[alias] = (item.get("column"), how)
    pandas_freq = _FREQ_ALIAS.get(freq, freq)
    indexed = working.set_index(column)
    agg_repr = ", ".join(
        f"{quote(alias)}: ({quote(pair[0])}, {quote(pair[1])})" for alias, pair in spec.items()
    )
    if group_col and group_col in working.columns:
        out = (
            working.groupby([group_col, pd.Grouper(key=column, freq=pandas_freq)], observed=True)
            .agg(**spec)
            .reset_index()
        )
        out = _flatten_columns(out)
        code = (
            f"df = (df.groupby([{quote(group_col)}, pd.Grouper(key={quote(column)}, freq={quote(pandas_freq)})]\n"
            f"       , observed=True)\n"
            f"       .agg(**{{{agg_repr}}})\n"
            f"       .reset_index())"
        )
    else:
        out = indexed.resample(pandas_freq).agg(**spec).reset_index()
        code = (
            f"df = (df.set_index({quote(column)}).resample({quote(pandas_freq)})\n"
            f"       .agg(**{{{agg_repr}}})\n"
            f"       .reset_index())"
        )
    return out, code


@register(
    "rolling_window",
    "滚动窗口 (rolling)",
    "Rolling Window",
    "time",
    [
        COLUMN_PARAM(required=True, kinds=["numeric"]),
        P("window", "number", "窗口大小", "Window", default=7, min=2),
        P("how", "select", "窗口统计量", "Statistic", options=[{"value": k, "label": v} for k, v in AGG_LABELS.items() if k in ("mean", "sum", "std", "median", "min", "max")], default="mean"),
        P("group_by", "column", "分组列(可选)", "Group by (optional)", allow_empty=True),
        P("min_periods", "number", "最小样本数", "Min periods", default=1),
        P("center", "bool", "居中窗口", "Center window", default=False),
    ],
)
def _op_rolling(df, p, ctx):
    column = p.get("column")
    require(column in df.columns, f"列 {column} 不存在", f"column {column} not found")
    window = int(p.get("window") or 7)
    how = p.get("how") or "mean"
    min_periods = int(p.get("min_periods") or 1)
    center = bool(p.get("center"))
    group_col = p.get("group_by") or None
    new_name = f"{column}_滚动{how}{window}"
    out = df.copy()
    has_group = bool(group_col) and group_col in out.columns
    if has_group:
        out[new_name] = out.groupby(group_col, observed=True)[column].transform(
            lambda s: s.rolling(window, min_periods=min_periods, center=center).agg(how)
        )
        code = (
            f"df[{quote(new_name)}] = (df.groupby({quote(group_col)})[{quote(column)}]\n"
            f"    .transform(lambda s: s.rolling({window}, min_periods={min_periods}, center={str(center)}).{how}()))"
        )
    else:
        out[new_name] = out[column].rolling(window, min_periods=min_periods, center=center).agg(how)
        code = (
            f"df[{quote(new_name)}] = df[{quote(column)}].rolling({window}, min_periods={min_periods}, "
            f"center={str(center)}).{how}()"
        )
    return out, code


@register(
    "diff_period",
    "环比 / 同比 (shift + pct_change)",
    "Period over Period",
    "time",
    [
        P("column", "column", "数值列", "Value column", required=True, kinds=["numeric"]),
        P("date_column", "column", "时间列", "Date column", required=True, kinds=["datetime"]),
        P("group_by", "column", "分组列(可选)", "Group by (optional)", allow_empty=True),
        P("periods", "number", "滞后期数", "Periods", default=1, min=1),
    ],
)
def _op_diff_period(df, p, ctx):
    column = p.get("column")
    date_column = p.get("date_column")
    group_col = p.get("group_by") or None
    periods = int(p.get("periods") or 1)
    working = df.copy()
    working[date_column] = pd.to_datetime(working[date_column], errors="coerce")
    working = working.sort_values(date_column)
    differ = f"{column}_环比变化"
    rate = f"{column}_环比"
    grouped = working.groupby(group_col, observed=True)[column] if group_col and group_col in working.columns else working[column]
    working[differ] = grouped.diff(periods)
    working[rate] = grouped.pct_change(periods)
    group_part = f".groupby({quote(group_col)})" if group_col and group_col in df.columns else ""
    code = (
        f"df = df.sort_values({quote(date_column)})\n"
        f"df[{quote(differ)}] = df{group_part}[{quote(column)}].diff({periods})\n"
        f"df[{quote(rate)}] = df{group_part}[{quote(column)}].pct_change({periods})"
    )
    return working, code


# -------------------------------- 多表合并 --------------------------------

@register(
    "merge",
    "合并两张表 (merge)",
    "Merge Two Tables",
    "combine",
    [
        P("right_dataset", "dataset", "右表数据集", "Right dataset", required=True),
        P("how", "select", "连接方式", "Join type", options=[
            {"value": "inner", "label": {"zh": "内连接 inner", "en": "Inner"}},
            {"value": "left", "label": {"zh": "左连接 left", "en": "Left"}},
            {"value": "right", "label": {"zh": "右连接 right", "en": "Right"}},
            {"value": "outer", "label": {"zh": "外连接 outer", "en": "Outer"}},
            {"value": "cross", "label": {"zh": "笛卡尔积 cross", "en": "Cross"}},
        ], default="left"),
        P("left_on", "columns", "左表连接键", "Left keys", required=True),
        P("right_on", "columns", "右表连接键", "Right keys", required=True),
        P("indicator", "bool", "显示合并来源 indicator", "Add merge indicator", default=False),
    ],
)
def _op_merge(df, p, ctx):
    right_id = p.get("right_dataset")
    right = ctx["frames"].get(right_id)
    require(right is not None, "右表数据集不存在", "right dataset not found")
    left_on = [c for c in (p.get("left_on") or []) if c in df.columns]
    right_on = [c for c in (p.get("right_on") or []) if c in right.columns]
    require(left_on and right_on, "请选择两表的连接键", "please select join keys")
    how = p.get("how") or "left"
    indicator = bool(p.get("indicator"))
    out = df.merge(right, how=how, left_on=left_on, right_on=right_on, suffixes=("", "_右表"), indicator=indicator)
    right_name = (ctx.get("meta", {}).get(right_id) or {}).get("zh") or right_id
    code = (
        f"# 右表数据集：{right_name}\n"
        f"other = pd.read_csv('data/{right_id}.csv')  # 替换为你的右表数据源\n"
        f"df = df.merge(other, how={quote(how)}, left_on={qlist(left_on)}, right_on={qlist(right_on)}, "
        f"suffixes=('', '_右表'), indicator={str(indicator)})"
    )
    return out, code


@register(
    "concat",
    "纵向/横向拼接 (concat)",
    "Concat Tables",
    "combine",
    [
        P("with_dataset", "dataset", "另一数据集", "Other dataset", required=True),
        P("axis", "select", "拼接方向", "Axis", options=[{"value": "0", "label": {"zh": "纵向堆叠 (axis=0)", "en": "Vertical (axis=0)"}}, {"value": "1", "label": {"zh": "横向拼接 (axis=1)", "en": "Horizontal (axis=1)"}}], default="0"),
        P("mode", "select", "对齐方式", "Alignment", options=[{"value": "aligned", "label": {"zh": "按列名对齐 (concat)", "en": "Align by name"}}, {"value": "types", "label": {"zh": "忽略列名按位置 (concat ignore_index)", "en": "Ignore names"}}], default="aligned"),
    ],
)
def _op_concat(df, p, ctx):
    other_id = p.get("with_dataset")
    other = ctx["frames"].get(other_id)
    require(other is not None, "数据集不存在", "dataset not found")
    axis = int(p.get("axis") or 0)
    mode = p.get("mode") or "aligned"
    if axis == 1:
        out = pd.concat([df.reset_index(drop=True), other.reset_index(drop=True)], axis=1)
        code = "df = pd.concat([df, other], axis=1)"
    elif mode == "types":
        out = pd.concat([df, other], axis=0, ignore_index=True, join="outer")
        code = "df = pd.concat([df, other], axis=0, ignore_index=True)"
    else:
        out = pd.concat([df, other], axis=0, ignore_index=True, join="inner")
        code = "df = pd.concat([df, other], axis=0, ignore_index=True, join='inner')"
    return _flatten_columns(out), code


# -------------------------------- 图形筛选 --------------------------------

@register(
    "category_filter",
    "类别筛选（图表点击）",
    "Category Filter (chart click)",
    "visual",
    [P("column", "column", "列", "Column", required=True), P("values", "tags", "保留的类别", "Keep values", required=True)],
    hint_zh="在图表上点击 / 框选后自动生成，可视化即查询",
    hint_en="Auto-generated when you click or brush a chart",
)
def _op_category_filter(df, p, ctx):
    column = p.get("column")
    values = p.get("values")
    if isinstance(values, str):
        values = [v for v in re.split(r"[,，;；\n]", values) if v != ""]
    values = values or []
    require(column in df.columns and values, "请选择列与类别", "please select column and values")
    casted = cast_list(df[column], values)
    out = df[df[column].isin(casted)].copy()
    return out, f"df = df[df[{quote(column)}].isin({qlist(casted)})]"


@register(
    "range_filter",
    "数值区间筛选（图表刷选）",
    "Range Filter (chart brush)",
    "visual",
    [
        P("column", "column", "列", "Column", required=True, kinds=["numeric"]),
        P("min", "number", "下界", "Lower bound", required=True),
        P("max", "number", "上界", "Upper bound", required=True),
    ],
    hint_zh="在散点图 / 直方图上框选区间后自动生成",
    hint_en="Auto-generated when you brush a numeric range on a chart",
)
def _op_range_filter(df, p, ctx):
    column = p.get("column")
    require(column in df.columns, f"列 {column} 不存在", f"column {column} not found")
    low, high = safe_float(p.get("min")), safe_float(p.get("max"))
    require(low is not None and high is not None, "请提供区间上下界", "please provide both bounds")
    if low > high:
        low, high = high, low
    series = pd.to_numeric(df[column], errors="coerce")
    out = df[series.between(low, high)].copy()
    return out, f"df = df[df[{quote(column)}].between({quote(low)}, {quote(high)})]"


# ---------------------------------------------------------------------------
# 目录 / 执行
# ---------------------------------------------------------------------------

def op_catalog() -> list[dict]:
    """返回前端渲染“算子面板”所需的元数据（剔除 Python 函数）。"""
    catalog = []
    for op_id, spec in OP_SPECS.items():
        catalog.append(
            {
                "id": op_id,
                "label": spec["label"],
                "group": spec["group"],
                "hint": spec["hint"],
                "params": to_native(spec["params"]),
            }
        )
    return catalog


def _initial_code(dataset_name: str, dataset_id: str, builtin: bool) -> list[str]:
    if builtin:
        return [
            "# 内置数据由后端 pandas 生成，可直接用同样的方式读取本地文件：",
            f"# df = pd.read_csv('data/{dataset_id}.csv')",
        ]
    return [
        f"# 上传数据：{dataset_name}",
        f"# df = pd.read_csv('{dataset_name}')",
    ]


def run_pipeline(
    df: pd.DataFrame,
    steps: list[dict],
    context: dict | None = None,
    include_step_preview: int | None = None,
) -> dict:
    """执行管道：返回每步元信息、整体代码、最终 DataFrame。"""
    context = dict(context or {})
    context.setdefault("frames", {})
    context.setdefault("frame_expr", {})
    current = df.copy()
    step_infos: list[dict] = []
    code_lines: list[str] = []
    error_payload = None
    preview = None

    for index, step in enumerate(steps or []):
        op_id = step.get("type") or step.get("id")
        params = step.get("params") or {}
        if step.get("enabled") is False:
            step_infos.append(
                {
                    "index": index,
                    "id": op_id,
                    "disabled": True,
                    "label": OP_SPECS.get(op_id, {}).get("label", {"zh": op_id, "en": op_id}),
                    "params": to_native(params),
                    "code": "# 已跳过该步骤 (disabled)",
                    "rows": int(len(current)),
                    "cols": int(current.shape[1]),
                    "rows_delta": 0,
                    "cols_delta": 0,
                    "elapsed_ms": 0.0,
                    "status": "skipped",
                }
            )
            continue
        spec = OP_SPECS.get(op_id)
        if spec is None:
            error_payload = {"step": index, "id": op_id, "message": f"unknown operator: {op_id}"}
            break
        columns_before = list(current.columns)
        rows_before, cols_before = current.shape
        started = time.perf_counter()
        try:
            result = spec["fn"](current, params, context)
            current, code = result if isinstance(result, tuple) else (result, "")
            if index == include_step_preview:
                head = current.head(12)
                preview = {
                    "rows": [
                        {str(col): to_native(row[col]) for col in head.columns}
                        for _, row in head.iterrows()
                    ]
                }
        except Exception as exc:  # noqa: BLE001 - 需要把 pandas 报错原文回传给前端
            message = f"{type(exc).__name__}: {exc}"
            if len(message) > 400:
                message = message[:400] + " …（已截断 / truncated）"
            error_payload = {
                "step": index,
                "id": op_id,
                "message": message,
                "label": spec["label"],
            }
            step_infos.append(
                {
                    "index": index,
                    "id": op_id,
                    "label": spec["label"],
                    "params": to_native(params),
                    "code": "# 该步骤执行失败",
                    "rows": int(rows_before),
                    "cols": int(cols_before),
                    "rows_delta": 0,
                    "cols_delta": 0,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                    "status": "error",
                    "error": error_payload["message"],
                }
            )
            break

        elapsed = round((time.perf_counter() - started) * 1000, 2)
        columns_after = list(current.columns)
        rows_after, cols_after = current.shape
        step_infos.append(
            {
                "index": index,
                "id": op_id,
                "label": spec["label"],
                "params": to_native(params),
                "code": code,
                "rows": int(rows_after),
                "cols": int(cols_after),
                "rows_delta": int(rows_after - rows_before),
                "cols_delta": int(cols_after - cols_before),
                "columns_added": [c for c in columns_after if c not in columns_before],
                "columns_removed": [c for c in columns_before if c not in columns_after],
                # 该步执行**之后**的完整列清单：前端用它作为下一步参数下拉的候选，
                # 这样 groupby / pivot 之类“改变了列”的步骤之后，下一步仍能看到正确的列。
                "columns": [{"name": str(col), "kind": classify_series(current[col])} for col in current.columns],
                "elapsed_ms": elapsed,
                "status": "ok",
            }
        )
        code_lines.append(code)

    return {
        "df": current,
        "steps": step_infos,
        "code": code_lines,
        "error": error_payload,
        "preview": preview,
        "rows": int(len(current)),
        "cols": int(current.shape[1]),
    }


def build_script(dataset_name: str, dataset_id: str, builtin: bool, code_lines: list[str], chart_code: str = "") -> str:
    header = [
        '"""',
        f"PandasViz Studio 自动导出的 pandas 分析脚本（数据集：{dataset_name}）",
        "运行方式：python analysis_script.py",
        '"""',
        "import pandas as pd  # noqa: F401",
        "",
    ]
    source = (
        [f"df = pd.read_csv('data/{dataset_id}.csv')", ""]
        if not builtin
        else [
            "# 该数据集由 PandasViz Studio 内置生成，如需离线复现请导出清洗后的 CSV，",
            f"# 或替换为：df = pd.read_csv('data/{dataset_id}.csv')",
            "",
        ]
    )
    body = ["# ---------------- 分析管道 ----------------"]
    for i, line in enumerate(code_lines, 1):
        body.append(f"# 步骤 {i}")
        body.extend(line.splitlines())
        body.append("")
    footer = ["# ---------------- 结果 ----------------", "print(df.shape)", "print(df.head())"]
    if chart_code:
        footer += ["", chart_code]
    return "\n".join(header + source + body + footer)
