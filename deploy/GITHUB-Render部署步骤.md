# GitHub → Render 部署步骤（拿永久公网链接）

> 目标：得到一个形如 `https://pandaviz-studio.onrender.com` 的链接，**不依赖你的电脑**，
> 老师任何时间打开都能用。总耗时约 **15–25 分钟**（其中 Render 构建 3–6 分钟是等待）。
>
> 这条路需要 **GitHub 账号**（你已有）和 **Render 账号**（用 GitHub 一键登录）。
> 官方说明 Render 免费层**不需要信用卡**；若你的账号在最后一步被要求验证支付方式，
> 直接改用 `deploy/DEPLOY-部署指引.md` 里的 **PythonAnywhere 方案**（绝对不需要卡）。

---

## 第 0 步：准备要上传的文件

用项目根目录下的 **`github-upload.zip`**（我已经打好包，不含缓存和个人数据）：

1. 在**另一个**空文件夹里把它解压（例如 `桌面\pandaviz-upload\`）
2. 解压后应该**直接看到** `backend`、`frontend`、`requirements.txt`、`Procfile`、`render.yaml`、`README.md`
   ——**不要再套一层文件夹**（`requirements.txt` 必须在最外层，Render 才认得）

> ⚠️ 不要上传 `pandas-viz-studio-网站源代码.zip`（那是交作业用的，仓库里不需要）。
> 也不要上传 `data/uploads/` 里的个人数据。

---

## 第 1 步：在 GitHub 上建仓库并上传

1. 打开 <https://github.com/new>
2. **Repository name** 填 `pandaviz-studio`
3. 选 **Public**（Render 免费层拉取公共仓库最省事）
4. **不要**勾选 "Add a README file"
5. 点绿色 **Create repository**
6. 在新仓库页面点 **Add file → Upload files**
7. 把第 0 步解压出来的**所有文件和文件夹**一起拖进虚线框（Chrome / Edge 支持拖文件夹）
8. 等文件列表出现后，下方 **Commit changes** 点一下
9. 传完后刷新仓库页，根目录应该能看到 `backend/`、`frontend/`、`requirements.txt`、`Procfile`、`render.yaml`

> 如果 `.gitignore`、`启动网站.bat` 这类文件没传上去也没关系（部署用不到它们）；
> 但 **`requirements.txt`、`Procfile`、`render.yaml`、`backend/`、`frontend/` 必须都在**。

---

## 第 2 步：在 Render 上创建 Web Service

1. 打开 <https://render.com> → 点 **Get Started** → 选 **GitHub** 登录并授权
2. 进入 Dashboard 后点右上 **New +** → **Web Service**
3. 在列表里选刚才的 `pandaviz-studio` 仓库 → **Connect**
4. 填写/确认下面几项（如果 Render 自动识别了 `render.yaml`，多半已经填好）：
   * **Name**：`pandaviz-studio`
   * **Region**：Singapore（离国内最近，可选）
   * **Branch**：`main`
   * **Runtime / Language**：`Python 3`
   * **Build Command**：`pip install -r requirements.txt`
   * **Start Command**：`gunicorn "backend.app:create_app()" --bind 0.0.0.0:$PORT --worker-class gthread --workers 1 --threads 4 --timeout 120`
   * **Instance Type**：**Free**
5. 点 **Create Web Service**，然后等待构建（日志里会依次出现 `Installing dependencies` → `Starting service`）

> 首次构建 **3–6 分钟**（要装 pandas / numpy / scipy）。看到日志里出现
> `Listening at: http://0.0.0.0:10000` 或 `Booting worker` 就说明起来了。

---

## 第 3 步：验证链接

1. 页面左上角会显示你的地址：**`https://pandaviz-studio.onrender.com`**（或带随机后缀）
2. 打开它，应该看到：
   * 顶部数据集是「全球零售订单 (2023-2024) — 4,000×21」
   * 图表工作室有一张区域 × 销售额的柱状图（6 根柱子）
   * 左侧「算子库」可以点「条件筛选」
3. 自己先点几下确认能交互，再把链接交上去
4. **交作业前 5 分钟，先自己打开一次**——免费实例 15 分钟没人访问会休眠，
   第一次打开需要等 30–60 秒冷启动，避免老师点开时以为坏了

---

## 第 4 步（可选）：把它设成"随时可开"

* 若不想让老师等冷启动：用 <https://uptimerobot.com>（免费）每 14 分钟访问一次该链接，
  服务就不会休眠；或升级到 $7/月的 Starter（完全不必）。
* 想更新代码：在 GitHub 仓库里重新上传改动文件并 Commit，Render 会自动重新部署。

---

## 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 构建失败，日志里 `No such file or directory: requirements.txt` | 上传时多套了一层文件夹。仓库根目录必须**直接**是 `requirements.txt` |
| 构建失败，`gunicorn: command not found` | `requirements.txt` 里的 gunicorn 行丢了（它带 `sys_platform != "win32"` 标记，是给 Linux 用的）。补上这一行：`gunicorn>=21.0.0; sys_platform != "win32"` |
| 部署成功但页面 502 / 反复重启 | 多半是内存不够：确认 Start Command 里是 `--workers 1`（免费实例只有 512MB），并带上 `--worker-class gthread` |
| 页面能打开但样式/图表全无、点击报错 | 前端静态目录没上传全：仓库里必须有 `frontend/`（含 `vendor/echarts.min.js`） |
| 打开很慢、第一次转圈一分钟 | 免费实例冷启动，正常现象；点刷新即可 |
| 上传 CSV 后过一会儿数据不见了 | 免费层没有持久磁盘，容器重启后上传的文件会丢；内置的 4 套数据集不受影响 |
| 最后一步要求绑定信用卡 | 换 PythonAnywhere 方案（`deploy/DEPLOY-部署指引.md` 方案 A），完全不需要卡 |

---

## 一键核对：上传后仓库里应该有的东西

```
backend/          7 个 .py 文件（app.py / engine.py / analysis.py / datasets.py / exporting.py / utils.py / __init__.py）
frontend/         index.html + assets/css/app.css + assets/js/*.js + vendor/echarts.min.js
requirements.txt
Procfile
render.yaml
README.md
```
