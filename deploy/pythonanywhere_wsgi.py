# ============================================================================
# PythonAnywhere 部署用的 WSGI 配置文件（免费层的 Web 应用必须手工填这个）
#
# 用法：
#   1. 在 PythonAnywhere 里把本项目上传/克隆到 /home/<你的用户名>/pandas-viz-studio
#   2. Web 标签页 → Add a new web app → 选 Manual configuration → Python 3.10（或 3.11）
#   3. 点开 "WSGI configuration file" 链接，把本文件内容**整份替换**进去
#   4. 把下面的 USERNAME 改成你的 PythonAnywhere 用户名
#   5. 回到 Web 页点 "Reload <用户名>.pythonanywhere.com"
#
# 目录结构要求（上传时保持这一层）：
#   /home/USERNAME/pandas-viz-studio/          ← 项目根（含 run.py、backend/、frontend/）
# ============================================================================

import sys

USERNAME = "USERNAME"  # ← 改成你的 PythonAnywhere 用户名
PROJECT_ROOT = f"/home/{USERNAME}/pandas-viz-studio"

# 让 Python 能找到 backend 包
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app import create_app  # noqa: E402

application = create_app()

# 说明：PythonAnywhere 免费层的 Web 应用需要通过它的 WSGI 服务器启动，
# 因此这里不调用 app.run()，只暴露 application 对象。
