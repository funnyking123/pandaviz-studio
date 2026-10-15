"""PandasViz Studio 启动入口。

用法::

    python run.py                 # 自动打开浏览器 http://127.0.0.1:5000
    python run.py --port 8080     # 指定端口
    python run.py --host 0.0.0.0  # 局域网访问（手机 / 平板也能打开）
    python run.py --no-browser    # 不自动打开浏览器
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.app import APP_VERSION, create_app  # noqa: E402


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def main() -> int:
    parser = argparse.ArgumentParser(description="PandasViz Studio · 可视化 pandas 数据分析工作台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=5000, help="监听端口，默认 5000")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--debug", action="store_true", help="开启 Flask 调试模式")
    args = parser.parse_args()

    port = args.port
    while port < args.port + 20 and not _port_available(args.host, port):
        print(f"[PandasViz] 端口 {port} 已被占用，尝试 {port + 1} ...")
        port += 1

    app = create_app()
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{port}"
    print("=" * 62)
    print(f"  PandasViz Studio v{APP_VERSION} · 可视化 pandas 数据分析工作台")
    print(f"  服务地址: {url}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 62)
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        app.run(host=args.host, port=port, debug=args.debug, threaded=True)
    except KeyboardInterrupt:
        print("\n[PandasViz] 已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
