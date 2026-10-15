"""后端冒烟测试：自动为每个算子生成参数并真实执行，然后检查 REST API 全链路。

运行： python tests/test_backend.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from backend import analysis, engine, exporting  # noqa: E402
from backend.app import create_app  # noqa: E402
from backend.datasets import STORE  # noqa: E402

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{label} :: {detail}")
        print(f"  [FAIL] {label} {detail}")


def _columns(dataset_id: str) -> list[dict]:
    return STORE.describe(dataset_id)["columns"]


def _names(columns: list[dict], kinds=None, limit=3) -> list[str]:
    pool = [c["name"] for c in columns if not kinds or c["kind"] in kinds]
    return pool[:limit]


def _is_numeric(df: pd.DataFrame, col: str) -> bool:
    return col in df.columns and pd.api.types.is_numeric_dtype(df[col])


def build_params(op: dict, columns: list[dict], df: pd.DataFrame, other_dataset: str, other_columns: list[dict]) -> dict:
    """按算子参数 schema 自动生成一份“尽量合法”的参数，用于覆盖全部算子。"""
    op_id = op["id"]
    numeric = _names(columns, ["numeric"], 6)
    categorical = _names(columns, ["categorical"], 6)
    datetimes = _names(columns, ["datetime"], 2)
    shared = [c["name"] for c in columns if c["name"] in [c2["name"] for c2 in other_columns]]
    used: list[str] = []
    params: dict = {}

    def take(pool):
        for candidate in pool:
            if candidate not in used:
                used.append(candidate)
                return candidate
        return pool[0] if pool else None

    for spec in op["params"]:
        name, ptype = spec["name"], spec["type"]
        if ptype == "column":
            kinds = spec.get("kinds")
            if op_id == "extract_datetime" or name == "date_column":
                value = take(datetimes)
            elif kinds:
                value = take(_names(columns, kinds, 6))
            elif name in ("values", "value"):
                value = take(numeric)
            elif op_id in ("pivot_table", "crosstab") and name == "columns":
                value = take(categorical)
            elif op_id == "category_filter":
                value = take(categorical)
            else:
                value = take(numeric + categorical)
            params[name] = value
        elif ptype == "columns":
            if op_id == "merge" and name in ("left_on", "right_on"):
                params[name] = shared[:1]
            elif spec.get("allow_empty"):
                params[name] = []
            else:
                pool = shared if op_id == "merge" else _names(columns, spec.get("kinds"), 6)
                picked = []
                for candidate in pool:
                    if candidate not in used:
                        picked.append(candidate)
                        used.append(candidate)
                    if len(picked) >= 2:
                        break
                params[name] = picked or pool[:1]
        elif ptype == "select":
            params[name] = spec.get("default")
            if params[name] is None and spec.get("options"):
                params[name] = spec["options"][0]["value"]
        elif ptype == "number":
            params[name] = spec.get("default", 1)
            if op_id == "filter_row" and name == "value2":
                params[name] = 100
        elif ptype == "bool":
            params[name] = bool(spec.get("default"))
        elif ptype == "text":
            params[name] = spec.get("default") or {
                "name": "测试列",
                "value": "1",
                "new_name": "",
                "rank_col": "",
                "prefix": "P",
                "suffix": "_new",
                "var_name": "指标",
                "value_name": "数值",
            }.get(name, "1")
        elif ptype == "textarea":
            if op_id == "filter_query":
                params[name] = f"{numeric[0]} > 0" if numeric else "index == index"
            else:
                params[name] = "1"
        elif ptype == "multi_select":
            params[name] = spec.get("default") or [spec["options"][0]["value"]]
        elif ptype == "agg_list":
            params[name] = [{"column": numeric[0], "how": "sum"}] if numeric else [{"column": categorical[0], "how": "count"}]
        elif ptype == "dataset":
            params[name] = other_dataset
        elif ptype == "tags":
            params[name] = ["x"]
        else:
            params[name] = None
    return params


def main() -> int:
    app = create_app()
    client = app.test_client()

    print("== 1. 内置数据集 ==")
    STORE.ensure_builtins()
    for item in STORE.list():
        check(f"dataset {item['id']} rows", item["rows"] > 0, f"rows={item['rows']}")
    check("4 个内置数据集", len([d for d in STORE.list() if d["source"] == "builtin"]) == 4)
    print(f"  数据集：{[(d['id'], d['rows'], d['cols']) for d in STORE.list()]}")

    print("== 2. 逐个算子真实执行 ==")
    primary, secondary = "sales", "countries"
    df = STORE.frame(primary)
    columns = _columns(primary)
    other_columns = _columns(secondary)
    catalog = engine.op_catalog()
    check("算子数量 >= 25", len(catalog) >= 25, f"ops={len(catalog)}")
    for op in catalog:
        params = build_params(op, columns, df, secondary, other_columns)
        steps = [{"type": op["id"], "params": params}]
        try:
            outcome = engine.run_pipeline(df, steps, {"frames": {secondary: STORE.frame(secondary)}, "meta": {secondary: {"zh": "国家发展指标"}}})
        except Exception as exc:  # noqa: BLE001
            check(f"op {op['id']}", False, f"raised {type(exc).__name__}: {exc} params={params}")
            continue
        if outcome["error"]:
            check(f"op {op['id']}", False, f"{outcome['error']['message']} params={params}")
            continue
        code = outcome["steps"][0]["code"]
        check(f"op {op['id']} runs", outcome["error"] is None, str(params))
        check(f"op {op['id']} codegen", bool(code) and "Traceback" not in code, code[:80])
        try:
            compile(code if "df[" in code and "import" not in code else "df = df\n" + code, "<code>", "exec")
        except SyntaxError as exc:
            check(f"op {op['id']} code-valid-python", False, f"{exc} :: {code}")
    print(f"  算子执行完成：{len(catalog)} 个")

    print("== 3. 组合管道 ==")
    chain = [
        {"type": "filter_row", "params": {"column": "销售额", "operator": ">", "value": "2000"}},
        {"type": "dropna", "params": {"subset": ["评分"], "how": "any"}},
        {"type": "extract_datetime", "params": {"column": "订单日期", "parts": ["year", "month", "weekday_name"]}},
        {"type": "assign_expr", "params": {"name": "利润_万元", "expr": "利润 / 10000"}},
        {"type": "groupby_agg", "params": {"by": ["区域", "品类"], "aggs": [{"column": "销售额", "how": "sum", "new_name": "销售额合计"}, {"column": "利润", "how": "mean", "new_name": "平均利润"}]}},
        {"type": "sort_values", "params": {"by": ["销售额合计"], "ascending": False, "rank_col": "排名"}},
        {"type": "head_rows", "params": {"mode": "head", "n": 20}},
    ]
    outcome = engine.run_pipeline(df, chain, {"frames": {}, "meta": {}})
    check("组合管道无错误", outcome["error"] is None, str(outcome["error"]))
    check("组合管道行数", outcome["rows"] == 20, f"rows={outcome['rows']}")
    check("组合管道列数", outcome["cols"] == 5, f"cols={outcome['cols']} cols={list(outcome['df'].columns)}")
    script = engine.build_script("sales", "sales", True, outcome["code"], "# plot")
    compile(script, "<script>", "exec")
    check("导出脚本可编译", True)

    print("== 4. REST API ==")
    resp = client.get("/api/meta")
    check("/api/meta 200", resp.status_code == 200, str(resp.status_code))
    meta_payload = resp.get_json()
    check("/api/meta 有算子目录", len(meta_payload.get("ops") or []) >= 25)

    resp = client.get("/")
    check("首页 200", resp.status_code == 200, str(resp.status_code))

    payload = {
        "dataset_id": "sales",
        "steps": chain[:2],
        "table": {"offset": 0, "limit": 20},
        "chart": {"type": "bar", "x": "区域", "y": "销售额", "agg": "sum", "topN": 10},
        "profile": True,
        "corr": {"method": "pearson"},
        "pivot": {"index": "区域", "columns": "品类", "values": "销售额", "agg": "sum"},
        "timeseries": {"date": "订单日期", "value": "销售额", "freq": "M", "agg": "sum", "rolling": 3},
        "stats": {"test": "anova", "value": "销售额", "group": "区域"},
        "insights": True,
        "code": True,
    }
    resp = client.post("/api/analyze", json=payload)
    check("/api/analyze 200", resp.status_code == 200, resp.get_data(as_text=True)[:200])
    body = resp.get_json()
    check("/api/analyze ok", body.get("ok") is True, json.dumps(body.get("pipeline", {}).get("error"), ensure_ascii=False))
    outputs = body.get("outputs") or {}
    for key in ("table", "chart", "profile", "corr", "pivot", "timeseries", "stats", "insights", "code"):
        check(f"outputs.{key}", key in outputs and outputs[key], key)
    check("表格有行", len(outputs["table"]["rows"]) == 20, str(len(outputs["table"]["rows"])))
    check("图表有 series", len(outputs["chart"]["series"]) >= 1)
    check("画像质量分", outputs["profile"]["summary"]["quality_score"] > 0)
    check("相关性矩阵", len(outputs["corr"]["matrix"]) >= 4)
    check("透视矩阵", len(outputs["pivot"]["cells"]) > 0)
    check("时序序列", len(outputs["timeseries"]["series"]) >= 1)
    check("统计检验", "p" in outputs["stats"], json.dumps(outputs["stats"], ensure_ascii=False)[:200])
    check("洞察条数", len(outputs["insights"]["insights"]) >= 1)
    check("代码行数", len(outputs["code"]["lines"]) >= 1)

    print("== 5. 图表类型全覆盖 ==")
    chart_df = engine.run_pipeline(df, chain[:5], {"frames": {}, "meta": {}})["df"]
    chart_specs = {
        "bar": {"x": "品类", "y": "销售额合计", "agg": "sum"},
        "hbar": {"x": "品类", "y": "销售额合计", "agg": "sum"},
        "line": {"x": "区域", "y": "销售额合计", "agg": "sum"},
        "area": {"x": "区域", "y": "销售额合计", "agg": "sum"},
        "stacked_bar": {"x": "区域", "y": "销售额合计", "agg": "sum", "series": "品类"},
        "percent_bar": {"x": "区域", "y": "销售额合计", "agg": "sum", "series": "品类"},
        "pie": {"x": "品类", "y": "销售额合计", "agg": "sum"},
        "donut": {"x": "品类", "y": "销售额合计", "agg": "sum"},
        "rose": {"x": "品类", "y": "销售额合计", "agg": "sum"},
        "treemap": {"x": "品类", "y": "销售额合计", "agg": "sum"},
        "funnel": {"x": "品类", "y": "销售额合计", "agg": "sum"},
        "scatter": {"x": "销售额合计", "y": "平均利润", "fit": True},
        "bubble": {"x": "销售额合计", "y": "平均利润", "size": "平均利润", "series": "区域"},
        "histogram": {"y": "销售额合计", "bins": 20},
        "density": {"y": "销售额合计"},
        "ecdf": {"y": "销售额合计"},
        "boxplot": {"x": "品类", "y": "销售额合计"},
        "violin": {"x": "区域", "y": "销售额合计"},
        "heatmap": {"x": "品类", "y": "区域", "values": "销售额合计", "agg": "sum"},
        "radar": {"dims": ["销售额合计", "平均利润"], "series": "品类"},
        "parallel": {"dims": ["销售额合计", "平均利润"], "series": "区域"},
        "scatter_matrix": {"dims": ["销售额合计", "平均利润"], "series": "区域"},
    }
    for chart_type, spec in chart_specs.items():
        spec = {"type": chart_type, **spec}
        try:
            built = analysis.build_chart(chart_df, spec, STORE.meta("sales"))
        except Exception as exc:  # noqa: BLE001
            check(f"chart {chart_type}", False, f"{type(exc).__name__}: {exc}")
            continue
        has_data = bool(built.get("series") or built.get("cells") or built.get("boxes") or built.get("violins"))
        check(f"chart {chart_type}", has_data, json.dumps(built, ensure_ascii=False)[:160])
        check(f"chart {chart_type} code", bool(built.get("code")))
    print(f"  图表类型：{len(chart_specs)} 个")

    print("== 6. 数据加载与导出 ==")
    csv_bytes = exporting.to_csv_bytes(chart_df)
    check("CSV 导出", len(csv_bytes) > 100)
    excel_bytes = exporting.to_excel_bytes(chart_df)
    check("Excel 导出", len(excel_bytes) > 100)
    report = exporting.build_report_markdown(STORE.describe("sales"), engine.run_pipeline(df, chain, {"frames": {}, "meta": {}}), None, None, [])
    check("报告生成", "分析报告" in report)
    resp = client.post("/api/export/script", json={"dataset_id": "sales", "steps": chain[:3], "chart": {"type": "bar", "x": "区域", "y": "销售额", "agg": "sum"}})
    check("/api/export/script 200", resp.status_code == 200, str(resp.status_code))
    check("脚本含 groupby 或步骤", "df" in (resp.get_json() or {}).get("script", ""))
    resp = client.post("/api/export/data", json={"dataset_id": "sales", "steps": chain[:2], "format": "csv"})
    check("/api/export/data csv", resp.status_code == 200 and resp.data[:3] == b"\xef\xbb\xbf", str(resp.status_code))

    print("== 7. 上传解析（CSV with GBK + 分号分隔） ==")
    import io as _io

    gbk_csv = "城市;销量;评分\n上海;120;4.5\n北京;98;\n广州;77;3.9\n".encode("gb18030")
    resp = client.post(
        "/api/datasets/upload",
        data={"file": (_io.BytesIO(gbk_csv), "test_cn.csv")},
        content_type="multipart/form-data",
    )
    check("上传 200", resp.status_code == 200, resp.get_data(as_text=True)[:200])
    uploaded = (resp.get_json() or {}).get("dataset") or {}
    check("上传列识别", [c["name"] for c in uploaded.get("columns", [])] == ["城市", "销量", "评分"], str(uploaded.get("columns")))
    if uploaded.get("id"):
        resp = client.post("/api/analyze", json={"dataset_id": uploaded["id"], "steps": [], "profile": True, "table": {}})
        check("上传数据可分析", resp.status_code == 200 and (resp.get_json() or {}).get("ok") is True)
        resp = client.delete(f"/api/datasets/{uploaded['id']}")
        check("删除上传数据集", resp.status_code == 200)

    print("== 8. 错误路径 ==")
    resp = client.post("/api/analyze", json={"dataset_id": "nope", "steps": []})
    check("未知数据集 404", resp.status_code == 404, str(resp.status_code))
    resp = client.post("/api/analyze", json={"dataset_id": "sales", "steps": [{"type": "filter_row", "params": {"column": "不存在", "operator": ">", "value": 1}}]})
    body = resp.get_json()
    check("错误步骤被捕获", resp.status_code == 200 and body.get("ok") is False and body["pipeline"]["error"], json.dumps(body.get("pipeline", {}).get("error"), ensure_ascii=False))
    check("错误定位到步骤 0", body["pipeline"]["error"]["step"] == 0)

    print()
    print(f"通过 {PASS} 项，失败 {FAIL} 项")
    if FAILURES:
        print("失败明细：")
        for item in FAILURES:
            print("  -", item)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
