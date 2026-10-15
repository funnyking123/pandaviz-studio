# 部署指引：把网站变成「可以交给老师的链接」

> 作业要求第 1 项是「**你的网站发布后的链接**」，`http://127.0.0.1:5000` 只在你自己的电脑上有效，
> 所以必须把项目放到一台**公网服务器**上，拿到形如 `https://xxx.pythonanywhere.com` 或
> `https://xxx.onrender.com` 的链接。
>
> 本项目是 Flask + pandas 的**服务端应用**（后端要真跑 pandas），因此不能像纯静态网页那样
> 直接丢到 GitHub Pages；需要支持 Python 的托管平台。

本目录已经准备好各平台需要的文件：

| 文件 | 用途 |
| --- | --- |
| `Procfile` | Render / Railway 的启动命令（gunicorn） |
| `render.yaml` | Render 的一键部署配置（Build / Start 命令、环境变量） |
| `deploy/pythonanywhere_wsgi.py` | PythonAnywhere 免费层需要手工填的 WSGI 配置 |
| `requirements.txt` | 已包含 `gunicorn`（用 `sys_platform != "win32"` 标记，Windows 本地会自动跳过） |
| `.gitignore` | 排除 `__pycache__`、个人上传数据、打包产物 |

---

## 方案 A：PythonAnywhere（推荐 · 不需要 git、不需要命令行）

免费层即可，链接长期有效（`https://<用户名>.pythonanywhere.com`）。

1. 注册 <https://www.pythonanywhere.com> （选 **Beginner** 免费账号）
2. **上传代码**：Dashboard → **Files** → 进入 `/home/<用户名>/` → 点 **Upload a file**
   （GitHub 上可以先压成 zip，上传后再用 **Open Bash console here** 执行
   `unzip pandaviz-studio-网站源代码.zip && mv pandas-viz-studio pandaviz-studio`；
   也可以直接用 `git clone`，如果代码已推到 GitHub）
3. **装依赖**：Dashboard → **Consoles** → **Bash**，执行
   ```bash
   cd ~/pandas-viz-studio
   pip install --user -r requirements.txt
   ```
4. **建 Web 应用**：Dashboard → **Web** → **Add a new web app** → **Manual configuration**
   → 选 **Python 3.10**（或 3.11）
5. **填 WSGI 配置**：在 Web 页面点开 **WSGI configuration file** 链接，
   把 `deploy/pythonanywhere_wsgi.py` 的内容**整份粘贴**进去，并把
   `USERNAME = "USERNAME"` 改成你的用户名
6. **Reload**：回到 Web 页面点绿色的 **Reload** 按钮
7. 打开 `https://<用户名>.pythonanywhere.com` —— 应该能看到数据集「全球零售订单 4,000×21」

> 免费层限制：Web 应用需要每 3 个月点一次「Run until 3 months from today」续期；
> 首次加载会慢几秒（服务器在美国），属正常现象。

---

## 方案 B：Render（需要 GitHub 账号）

1. 注册 <https://github.com> ，新建一个仓库（Public）
2. 把项目文件上传到仓库：仓库页 → **Add file → Upload files** → 把解压后的
   `pandas-viz-studio` 目录里的**所有文件和文件夹**拖进去（保持 `backend/`、`frontend/` 等结构）
3. 注册 <https://render.com> ，**New +** → **Web Service** → 连接刚才的仓库
4. 平台会自动识别 `render.yaml`；若手动填写，用：
   * **Build Command**：`pip install -r requirements.txt`
   * **Start Command**：`gunicorn "backend.app:create_app()" --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
   * **Instance Type**：Free
5. 部署完成后得到 `https://<服务名>.onrender.com`

> 免费层会在一段时间无访问后休眠，下次打开需要等 30–60 秒冷启动；
> 建议**交作业前先自己访问一次**把它唤醒。

---

## 方案 C：临时内网穿透（5 分钟拿到链接，但有明显限制）

适合"先有个链接能演示"，命令示例（需要先下载对应工具）：

```powershell
# Cloudflare 隧道（无需注册，随机域名）
cloudflared tunnel --url http://localhost:5000

# 或 ngrok（需要注册拿 token）
ngrok http 5000
```

会得到形如 `https://xxxx.trycloudflare.com` 的临时链接。

**限制（务必注意）**：链接只在你电脑开机且服务运行时有效，**电脑一关就失效**，
老师若在其他时间打开会 404。因此只建议作为兜底，不作为正式提交。

---

## 部署后自检清单

| 检查项 | 期望 |
| --- | --- |
| 首页 | 显示「全球零售订单 (2023-2024) 4,000×21」，图表工作室有柱状图 |
| 交互 | 点左侧「条件筛选」→ 填值 → 图与代码同步更新 |
| 中英切换 | 右上角切到 EN，坐标轴与图例变英文，代码里的列名仍是中文 |
| 上传 | 「加载数据」上传一个 CSV 能正常解析 |
| 导出 | 「导出 → pandas 分析脚本」能下载 `.py` |
| 手机访问 | 同一链接手机浏览器也能打开（响应式布局） |

## 常见部署问题

| 现象 | 原因与处理 |
| --- | --- |
| 页面 502 / Internal Server Error | 多半是依赖没装全或 WSGI 路径写错：检查 `PROJECT_ROOT` 是否指向含 `backend/` 的目录，重新 `pip install --user -r requirements.txt` |
| 静态资源 404（样式丢失） | 上传时目录层级错了，确认服务器上是 `pandas-viz-studio/frontend/index.html` 这一层 |
| 中文乱码 | 设置环境变量 `PYTHONIOENCODING=utf-8`（`render.yaml` 里已加） |
| 首次打开很慢 | 免费层冷启动，等 30–60 秒；先自己访问一次预热 |
| 想换成自己的数据 | 部署后直接在网页上「加载数据」上传即可，无需改代码 |
