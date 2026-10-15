"""打包提交用的网站源代码 zip。

用法::

    python tools/build_zip.py            # 生成 pandas-viz-studio-网站源代码.zip
    python tools/build_zip.py --check    # 只列出将要打包的文件，不写 zip
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_NAME = "pandas-viz-studio-网站源代码.zip"

EXCLUDE_DIRS = {"__pycache__", ".venv", "venv", ".idea", ".vscode", ".reasonix", ".probe"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".pyd", ".log", ".zip", ".png", ".tmp", ".bak"}
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db", "index.json", "task.lock"}
# Word / Excel 打开文档时的临时锁文件（~$xxx.docx）与 macOS 元数据文件，都不该进压缩包
EXCLUDE_PREFIXES = ("~$", "._")
# 上传数据属于个人运行期文件，仅保留目录占位
UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"


def should_include(path: Path) -> bool:
    relative = path.relative_to(PROJECT_ROOT)
    if path.name.startswith(EXCLUDE_PREFIXES):
        return False
    if any(part in EXCLUDE_DIRS for part in relative.parts):
        return False
    if path.suffix.lower() in EXCLUDE_SUFFIX:
        return False
    if path.name in EXCLUDE_NAMES:
        return False
    if UPLOAD_DIR in path.parents and path.name != ".gitkeep":
        return False
    return path.is_file()


def collect() -> list[Path]:
    files = [path for path in PROJECT_ROOT.rglob("*") if should_include(path)]
    return sorted(files, key=lambda item: str(item.relative_to(PROJECT_ROOT)).lower())


def main() -> int:
    parser = argparse.ArgumentParser(description="打包 PandasViz Studio 源码")
    parser.add_argument("--check", action="store_true", help="只列出文件清单")
    parser.add_argument("--output", default=ARCHIVE_NAME, help="输出 zip 名称")
    args = parser.parse_args()

    files = collect()
    total_bytes = sum(path.stat().st_size for path in files)
    print(f"待打包文件 {len(files)} 个，共 {total_bytes / 1024:.1f} KB")
    for path in files:
        print("  ", path.relative_to(PROJECT_ROOT))
    if args.check:
        return 0

    target = PROJECT_ROOT / args.output
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=str(Path(PROJECT_ROOT.name) / path.relative_to(PROJECT_ROOT)))
    print()
    print(f"已生成：{target}（{target.stat().st_size / 1024:.1f} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
