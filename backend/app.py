"""Flask 应用：REST API + 静态前端（单进程即可运行）。"""
from __future__ import annotations

import io
import time

from flask import Flask, Response, jsonify, request, send_from_directory

from . import analysis, engine, exporting
from .datasets import STORE
from .utils import FRONTEND_DIR, json_safe_dumps, steps_fingerprint, to_native

APP_VERSION = "1.0.0"

# 只缓存最近一次管道执行结果（分页 / 排序 / 换图表时无需重算管道）
_LAST_EXEC: dict = {"key": None, "df": None}


def _json(payload, status: int = 200) -> Response:
    return Response(json_safe_dumps(payload), status=status, mimetype="application/json")


def _error(message: str, status: int = 400, **extra) -> Response:
    return _json({"ok": False, "error": message, **extra}, status=status)


def _execute_pipeline(dataset_id: str, steps: list[dict], step_preview: int | None = None):
    """执行管道（带轻量缓存）。返回 (df, pipeline_payload)。"""
    key = steps_fingerprint(dataset_id, steps)
    if step_preview is None and _LAST_EXEC.get("key") == key and _LAST_EXEC.get("df") is not None:
        return _LAST_EXEC["df"], _LAST_EXEC["payload"]
    datasets = STORE.list()
    context = {
        "frames": {item["id"]: STORE.frame(item["id"]) for item in datasets},
        "meta": {item["id"]: (STORE.meta(item["id"]).get("name") or {}) for item in datasets},
    }
    outcome = engine.run_pipeline(STORE.frame(dataset_id), steps, context, include_step_preview=step_preview)
    df = outcome.pop("df")
    payload = to_native(outcome)
    if step_preview is None:
        _LAST_EXEC.update({"key": key, "df": df, "payload": payload})
    return df, payload


def _safe_view(fn, *args, **kwargs):
    """单个视图计算失败时降级为 error 字段，而不是让整个请求 500（避免前端界面错位）。"""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        if len(message) > 300:
            message = message[:300] + " …"
        return {"error": {"zh": f"该视图计算失败：{message}", "en": f"This view failed: {message}"}}


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
    app.config["MAX_CONTENT_LENGTH"] = 128 * 1024 * 1024
    app.config["JSON_AS_ASCII"] = False
    STORE.ensure_builtins()

    # ----------------------------- 静态前端 -----------------------------
    @app.route("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.route("/favicon.ico")
    def favicon():
        return ("", 204)

    # ------------------------------- 元信息 -----------------------------
    @app.get("/api/health")
    def health():
        return _json({"ok": True, "version": APP_VERSION, "time": time.time()})

    @app.get("/api/meta")
    def meta():
        import pandas as pd

        return _json(
            {
                "ok": True,
                "version": APP_VERSION,
                "pandas_version": pd.__version__,
                "datasets": STORE.list(),
                "ops": engine.op_catalog(),
                "op_groups": engine.OP_GROUPS,
                "chart_types": analysis.CHART_TYPES,
                "aggs": [{"value": k, "label": v} for k, v in engine.AGG_LABELS.items()],
                "comparison_ops": engine.COMPARISON_OPS,
                "date_parts": engine.DATE_PARTS,
                "resample_freqs": engine.RESAMPLE_FREQS,
            }
        )

    # ------------------------------- 数据集 -----------------------------
    @app.get("/api/datasets")
    def datasets_index():
        return _json({"ok": True, "datasets": STORE.list()})

    @app.get("/api/datasets/<dataset_id>")
    def dataset_detail(dataset_id: str):
        if not STORE.has(dataset_id):
            return _error(f"dataset not found: {dataset_id}", 404)
        return _json({"ok": True, "dataset": STORE.describe(dataset_id)})

    @app.post("/api/datasets/upload")
    def dataset_upload():
        if "file" not in request.files:
            return _error("no file uploaded")
        file = request.files["file"]
        options = {
            "sep": request.form.get("sep") or None,
            "encoding": request.form.get("encoding") or None,
            "header_row": request.form.get("header_row") or 0,
            "display_name": request.form.get("display_name") or None,
        }
        options = {key: value for key, value in options.items() if value not in (None, "")}
        try:
            info = STORE.add_upload(file, options)
        except Exception as exc:  # noqa: BLE001 - 把读取失败原因回传前端
            return _error(f"{type(exc).__name__}: {exc}", 400)
        description = STORE.describe(info["id"])
        return _json({"ok": True, "dataset": description, "message": {"zh": "上传成功", "en": "Uploaded"}})

    @app.delete("/api/datasets/<dataset_id>")
    def dataset_delete(dataset_id: str):
        if STORE.remove(dataset_id):
            return _json({"ok": True})
        return _error("只能删除上传的数据集 / only uploaded datasets can be removed", 400)

    # ------------------------------- 主接口 -----------------------------
    @app.post("/api/analyze")
    def analyze():
        payload = request.get_json(silent=True) or {}
        dataset_id = payload.get("dataset_id")
        if not dataset_id or not STORE.has(dataset_id):
            return _error(f"dataset not found: {dataset_id}", 404)
        steps = payload.get("steps") or []
        step_preview = payload.get("step_preview")
        try:
            df, pipeline = _execute_pipeline(dataset_id, steps, step_preview)
        except Exception as exc:  # noqa: BLE001
            return _error(f"{type(exc).__name__}: {exc}", 500)

        dataset_meta = STORE.meta(dataset_id)
        try:
            pipeline["columns"] = analysis.describe_columns(df, dataset_meta)
        except Exception:  # noqa: BLE001 - 列信息失败也不能拖垮整个响应
            pipeline["columns"] = STORE.describe(dataset_id).get("columns", [])
        outputs: dict = {}

        if payload.get("table") is not None:
            table_cfg = payload.get("table") or {}
            outputs["table"] = _safe_view(
                analysis.table_page,
                df,
                dataset_meta,
                offset=int(table_cfg.get("offset") or 0),
                limit=min(int(table_cfg.get("limit") or 50), 500),
                sort_by=table_cfg.get("sort_by"),
                sort_dir=table_cfg.get("sort_dir") or "asc",
                search=table_cfg.get("search"),
            )
        if payload.get("chart") is not None:
            outputs["chart"] = _safe_view(analysis.build_chart, df, payload.get("chart") or {}, dataset_meta)
        if payload.get("profile"):
            outputs["profile"] = _safe_view(analysis.profile_dataset, df, dataset_meta)
        if payload.get("corr") is not None:
            corr_cfg = payload.get("corr") or {}
            outputs["corr"] = _safe_view(
                analysis.correlation_view, df, dataset_meta,
                method=corr_cfg.get("method") or "pearson", columns=corr_cfg.get("columns"),
            )
        if payload.get("pivot") is not None:
            outputs["pivot"] = _safe_view(analysis.pivot_view, df, payload.get("pivot") or {}, dataset_meta)
        if payload.get("timeseries") is not None:
            outputs["timeseries"] = _safe_view(analysis.timeseries_view, df, payload.get("timeseries") or {}, dataset_meta)
        if payload.get("stats") is not None:
            outputs["stats"] = _safe_view(analysis.stats_view, df, payload.get("stats") or {}, dataset_meta)
        if payload.get("insights"):
            outputs["insights"] = _safe_view(analysis.auto_insights, df, dataset_meta)
        if payload.get("code"):
            outputs["code"] = {
                "lines": pipeline.get("code") or [],
                "script": engine.build_script(
                    (dataset_meta.get("name") or {}).get("zh") or dataset_id,
                    dataset_id,
                    dataset_meta.get("source") == "builtin",
                    pipeline.get("code") or [],
                    (outputs.get("chart") or {}).get("code") or "",
                ),
            }

        return _json(
            {
                "ok": pipeline.get("error") is None,
                "dataset": STORE.describe(dataset_id),
                "pipeline": pipeline,
                "outputs": outputs,
            }
        )

    # ------------------------------- 导出 -------------------------------
    @app.post("/api/export/data")
    def export_data():
        payload = request.get_json(silent=True) or {}
        dataset_id = payload.get("dataset_id")
        if not dataset_id or not STORE.has(dataset_id):
            return _error("dataset not found", 404)
        steps = payload.get("steps") or []
        fmt = (payload.get("format") or "csv").lower()
        df, pipeline = _execute_pipeline(dataset_id, steps)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if fmt in ("xlsx", "excel"):
            try:
                blob = exporting.to_excel_bytes(df)
            except Exception as exc:  # noqa: BLE001
                return _error(f"excel export failed: {exc}", 500)
            mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            filename = f"pandaviz-{dataset_id}-{stamp}.xlsx"
        else:
            blob = exporting.to_csv_bytes(df)
            mimetype = "text/csv; charset=utf-8"
            filename = f"pandaviz-{dataset_id}-{stamp}.csv"
        return Response(
            blob,
            mimetype=mimetype,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/export/script")
    def export_script():
        payload = request.get_json(silent=True) or {}
        dataset_id = payload.get("dataset_id")
        if not dataset_id or not STORE.has(dataset_id):
            return _error("dataset not found", 404)
        steps = payload.get("steps") or []
        df, pipeline = _execute_pipeline(dataset_id, steps)
        dataset_meta = STORE.meta(dataset_id)
        chart_spec = payload.get("chart")
        chart_code = ""
        if chart_spec:
            chart_code = analysis.build_chart(df, chart_spec, dataset_meta).get("code") or ""
        script = engine.build_script(
            (dataset_meta.get("name") or {}).get("zh") or dataset_id,
            dataset_id,
            dataset_meta.get("source") == "builtin",
            pipeline.get("code") or [],
            chart_code,
        )
        if payload.get("download"):
            return Response(
                script.encode("utf-8"),
                mimetype="text/x-python; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="pandaviz-{dataset_id}-analysis.py"'},
            )
        return _json({"ok": True, "script": script})

    @app.post("/api/export/report")
    def export_report():
        payload = request.get_json(silent=True) or {}
        dataset_id = payload.get("dataset_id")
        if not dataset_id or not STORE.has(dataset_id):
            return _error("dataset not found", 404)
        steps = payload.get("steps") or []
        df, pipeline = _execute_pipeline(dataset_id, steps)
        dataset_meta = STORE.meta(dataset_id)
        profile = analysis.profile_dataset(df, dataset_meta) if payload.get("profile", True) else None
        insights = analysis.auto_insights(df, dataset_meta) if payload.get("insights", True) else None
        charts = []
        for spec in payload.get("charts") or []:
            built = analysis.build_chart(df, spec, dataset_meta)
            built["title"] = (
                f"{(spec.get('axis') or {}).get('x') or ''} → {(spec.get('axis') or {}).get('y') or ''}".strip(" →") or built.get("type")
            )
            charts.append(built)
        markdown = exporting.build_report_markdown(
            STORE.describe(dataset_id), pipeline, profile, insights, charts, lang=payload.get("lang") or "zh"
        )
        if payload.get("download"):
            stamp = time.strftime("%Y%m%d-%H%M%S")
            return Response(
                markdown.encode("utf-8"),
                mimetype="text/markdown; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="pandaviz-report-{stamp}.md"'},
            )
        return _json({"ok": True, "markdown": markdown})

    @app.errorhandler(404)
    def not_found(_):
        return _error("not found", 404)

    @app.errorhandler(500)
    def server_error(exc):
        return _error(f"internal error: {exc}", 500)

    return app


if __name__ == "__main__":  # pragma: no cover
    create_app().run(host="127.0.0.1", port=5000, debug=True)
