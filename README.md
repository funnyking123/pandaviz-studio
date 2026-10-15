# PandasViz Studio · 可视化 pandas 数据分析工作台

> 一个把 **真实 pandas 计算** 变成 **可交互图形** 的 Web 分析工作台：
> 用「可视化管道」拼出 pandas 操作，每一步都实时给出图形结果与等价 pandas 代码。
>
> A visual workbench that turns **real pandas computation** into **interactive figures**:
> compose pandas operations as a visual pipeline and get charts plus equivalent pandas code in real time.

---

## 1. 为什么做这个

课程作业要求「参考 Python 的 pandas 库，以可视化的方式实现 pandas 的各种功能」，并且明确三点：
**分析功能要强大完整、交互要方便简洁、页面设计要美观耐看**，同时中英双语。

PandasViz Studio 的做法是：

| 作业要点 | 本项目如何实现 |
| --- | --- |
| 功能强大完整 | 后端是**真 pandas 内核**（不是前端模拟）：29 个算子覆盖筛选、清洗、类型转换、分组聚合、透视、交叉表、重采样、滚动窗口、环比同比、宽长表转换、独热编码、标准化、异常值处理、多表 merge/concat；分析层再提供画像、相关性、透视、时间序列、统计检验、自动洞察 |
| 交互方便简洁 | 「点算子 → 填参数 → 图形与代码立刻更新」；管道可拖动、可暂停、可单步预览；图表上的点击/刷选能反向生成筛选步骤 |
| 页面美观耐看 | 深/浅双主题、玻璃拟态面板、ECharts 定制主题、22 种图表类型、响应式布局 |
| 中英双语 | 界面、坐标轴、图例、类别取值、洞察文案、错误提示全部双语切换，且英文模式下**底层数据与生成的 pandas 代码完全不变** |
| 用图形增加分析能力 | 数据量漏斗、缺失矩阵、质量仪表、相关性热力图、散点矩阵、平行坐标、密度/ECDF/箱线/小提琴、分组分布对比、热力透视 |

---

## 2. 快速开始

### 2.1 环境要求

* Python **3.9+**（开发环境 Python 3.13）
* 依赖：`pandas`、`numpy`、`Flask`；推荐 `scipy`（KDE 密度曲线、t 检验 / ANOVA / 卡方 / 正态性检验）与 `openpyxl`（Excel 导入导出）

### 2.2 安装与运行

#### Windows 一键启动（推荐，不需要敲命令）

在文件资源管理器里**双击**项目根目录下的 **`启动网站.bat`**：

* 自动检查 Python 与依赖（缺依赖时自动 `pip install -r requirements.txt`）
* 自动启动服务并打开浏览器 `http://127.0.0.1:5000`
* 弹出的黑色命令行窗口就是网站服务，**请保持它打开**；按 `Ctrl+C` 或关闭窗口即停止服务
* 窗口内提示为英文，这是为了避免命令行中文编码问题，不影响网站本身的中英双语

#### 命令行启动

```bash
# 1) 安装依赖
pip install -r requirements.txt

# 2) 启动（会自动打开浏览器 http://127.0.0.1:5000）
python run.py

# 常用参数
python run.py --port 8080        # 指定端口
python run.py --host 0.0.0.0     # 局域网访问（手机 / 平板也能打开，可用于录制演示）
python run.py --no-browser       # 不自动打开浏览器
python run.py --debug            # Flask 调试模式
```

启动后浏览器打开 `http://127.0.0.1:5000`，默认加载内置数据集「全球零售订单」。

### 2.3 自检（可选）

```bash
python tests/test_backend.py     # 148 项检查：内置数据集、29 个算子逐个真实执行、22 种图表、REST API、上传解析、导出、错误路径
```

---

## 3. 功能总览

### 3.1 数据加载

* **4 套内置数据集**（后端用 numpy/pandas 现场生成，含真实脏数据特征）

  | 数据集 | 规模 | 适合演示 |
  | --- | --- | --- |
  | 全球零售订单 (2023-2024) | 4,000 × 21 | 分组聚合、透视、时间趋势、相关性、异常检测 |
  | 城市空气质量时序 (2023-2024) | 3,655 × 14 | 滚动均值、重采样、季节热力图、气泡图 |
  | 鸢尾花形态测量（含重复/缺失） | 162 × 7 | 散点矩阵、平行坐标、箱线图、聚类结构 |
  | 国家发展指标 (2019-2024) | 252 × 10 | 气泡图、树图、平行坐标、对数坐标 |

* **本地上传**：CSV / TSV / TXT / JSON / JSONL / XLSX，自动嗅探编码（utf-8 / gb18030 / big5 / latin-1）与分隔符，可手工指定分隔符、编码、表头行、数据集名称

### 3.2 可视化管道（核心交互）

* 左侧「算子库」按 7 组分类：筛选与采样、清洗与类型、重塑与派生、分组与聚合、时间序列、多表合并、图形筛选
* 点击算子即添加一步，参数表单按算子 schema 动态生成（列下拉自动按类型过滤：数值 / 类别 / 时间）
* 步骤卡片显示：**行数变化徽章**、等价 pandas 代码、执行耗时；支持上移/下移/暂停/删除/展开预览
* **数据量漏斗图**：每步剩余行数条形化，一眼看出哪一步筛掉最多数据
* 某一步出错时，精确定位到该步骤并回显 pandas 原始报错（中英双语提示）

### 3.3 九个分析视图

| 视图 | 能力 |
| --- | --- |
| 图表工作室 | 22 种图表类型；X / Y / 分组 / 气泡大小 / 数值维度编码；聚合、Top N、排序、堆叠、百分比、平滑、对数轴、数值标签、线性拟合与相关系数；点击图形直接生成「图形筛选」步骤；一键导出 PNG |
| 数据表 | 分页、排序、全字段搜索、类型着色、缺失值高亮、列头显示类型与缺失数；下方同步 `describe()` 式列统计 |
| 质量画像 | 数据质量分仪表、KPI 概览、缺失率排行、缺失值矩阵、数值列分布迷你直方图、字段详情表 |
| 关系分析 | Pearson / Spearman / Kendall 相关性热力图、最强相关对表格（点击即跳转散点图）、散点矩阵、平行坐标 |
| 透视表 | 行维度 × 列维度 × 数值字段 × 聚合函数 × 归一化，输出热力矩阵与等价 `pivot_table` 代码 |
| 时间序列 | 时间列解析、重采样（天/周/月/季/年）、多序列分组、滚动均值、最小二乘趋势线与相对变化 |
| 统计检验 | Welch t 检验、单因素 ANOVA、卡方独立性检验（Cramér's V + 列联表）、Shapiro-Wilk 正态性检验；组间 KDE 分布对比与分组描述统计 |
| 自动洞察 | 由真实 pandas 统计驱动：缺失、重复、偏斜、IQR 异常值、强相关对、类别不均衡、高基数、时间趋势、组间差异；每条洞察可点击跳转到对应图形 |
| pandas 代码 | 管道逐步生成的代码 + 可运行完整脚本（含数据读取、每步清洗聚合、绘图代码），一键复制 |

### 3.4 导出

* 清洗后数据 → **CSV / Excel**
* **pandas 分析脚本（.py）**：包含读数据、每一步操作、结果输出与图形代码，可直接 `python 脚本.py` 运行
* **分析报告（.md）**：数据概览、质量指标、管道代码、每步行数变化、自动洞察、图表及其代码

### 3.5 其他

* 中 / 英一键切换（含图表坐标轴、图例、类别取值、洞察文案）
* 深色 / 浅色主题切换
* URL 路由：`#chart` / `#table` / `#profile` / `#relation/matrix` / `#pivot` / `#timeseries` / `#stats` / `#insights` / `#code`，可直接分享某个视图
* 上传数据集持久化（重启后自动恢复）与删除
* 管道步骤按数据集记忆在浏览器本地（localStorage）

---

## 4. 目录结构

```
pandas-viz-studio/
├─ run.py                     # 启动入口（端口探测、自动打开浏览器）
├─ requirements.txt
├─ backend/                   # ===== 后端：真 pandas =====
│  ├─ app.py                  # Flask 应用与 REST API
│  ├─ engine.py               # 算子注册表 + 管道执行 + pandas 代码生成（29 个算子）
│  ├─ analysis.py             # 画像 / 图表数据 / 相关性 / 透视 / 时序 / 统计检验 / 自动洞察
│  ├─ datasets.py             # 内置数据集生成、上传解析、数据集注册表
│  ├─ exporting.py            # CSV / Excel / 脚本 / Markdown 报告导出
│  └─ utils.py                # JSON 安全序列化、类型识别
├─ frontend/                  # ===== 前端：原生 ES Module + ECharts =====
│  ├─ index.html
│  ├─ assets/css/app.css      # 深/浅双主题样式
│  ├─ assets/js/i18n.js       # 中英双语词典 + 取值本地化
│  ├─ assets/js/api.js        # REST 封装
│  ├─ assets/js/store.js      # 全局状态与默认编码策略
│  ├─ assets/js/charts.js     # 22 种图表 → ECharts option
│  ├─ assets/js/pipeline.js   # 算子库 / 步骤卡片 / 参数表单 / 漏斗图
│  ├─ assets/js/table.js      # 数据表与统计表渲染
│  ├─ assets/js/views.js      # 九个视图的控件与渲染
│  ├─ assets/js/app.js        # 引导、事件绑定、数据流编排
│  └─ vendor/echarts.min.js   # 本地化 ECharts（离线可用）
├─ data/uploads/              # 上传数据（含索引，重启恢复）
├─ tests/test_backend.py      # 后端自检 148 项
├─ tools/build_zip.py         # 打包提交用源码 zip
└─ docs/                      # 亮点说明、录屏脚本、提交清单
```

---

## 5. 技术架构

```
浏览器（原生 ES Module + ECharts）
    │  ① 用户操作（点算子 / 改参数 / 点图形）
    ▼
POST /api/analyze  { dataset_id, steps[], 各视图参数 }
    ▼
Flask 路由 ──► engine.run_pipeline()          逐步执行 pandas 算子
                 │  同时生成每步的等价 pandas 代码
                 ▼
              analysis.*()                     把 pandas 结果整理成“可视化就绪”数据结构
                 │  （画像 / 图表 / 相关 / 透视 / 时序 / 统计 / 洞察）
                 ▼
JSON 响应 ──► 前端渲染表格、ECharts 图形、代码、洞察卡片
```

关键设计：

1. **算子 = 数据 + 代码双输出**：每个算子在返回新 DataFrame 的同时返回与该操作等价的 pandas 代码字符串，因此「图形」与「代码」永远一致，导出脚本可复现整条链路。
2. **一次请求刷新多个面板**：`/api/analyze` 接受多个视图参数，一次调用同时返回表格、图表、画像、相关性、透视、时序、统计、洞察与代码，避免多次往返；管道结果按步骤指纹做轻量缓存，分页、排序、换图表无需重算。
3. **列 schema 随管道变化**：响应里带管道结果的列信息（类型、缺失、双语标签），所以 groupby 之后产生的新列（如 `销售额合计`）能立刻出现在坐标轴下拉中。
4. **双语不污染数据**：列名与类别值保持原始形态，双语只作用于展示层（`label` / `value_labels` 映射），英文模式下生成的 pandas 代码与中文模式完全一致。

---

## 6. 常见问题

| 现象 | 处理 |
| --- | --- |
| 浏览器打不开 `http://127.0.0.1:5000` | 确认 `启动网站.bat` 的黑色窗口还开着（关掉窗口＝服务停止）；也可换 `http://localhost:5000` |
| 端口被占用 | `run.py` 会自动向后尝试 20 个端口；也可 `--port` 指定 |
| 密度曲线提示「未检测到 scipy」 | `pip install scipy`（缺失时自动降级为 numpy 高斯核近似） |
| Excel 上传/导出失败 | `pip install openpyxl` |
| 中文 CSV 乱码 | 上传时把「编码」填成 `gb18030`，或留空让服务端自动嗅探 |
| 想用局域网演示 | `python run.py --host 0.0.0.0`，手机浏览器访问电脑 IP 即可 |
| 上传数据想清空 | 「数据概览」中点击「删除」，或删除 `data/uploads/` 下对应文件 |
| 改了 `docs/*.md`，想更新 Word 版 | 先关闭 Word 里打开的 `*.docx`，再双击 `更新文档.bat`（重新生成 docx 并重打 zip） |

---

## 7. English summary

PandasViz Studio is a single-process web app (Flask + real pandas) that exposes pandas
workflows as a **visual pipeline**: click an operator, fill in its parameters, and the app
returns charts, tables, statistics and the **equivalent pandas code** for every step.

* **4 built-in datasets** (generated with numpy/pandas, including missing values, duplicates and outliers) plus drag-and-drop upload of CSV/TSV/JSON/Excel with encoding sniffing.
* **29 operators**: filtering, cleaning, casting, date parts, binning, one-hot, standardizing, groupby.agg, pivot_table, crosstab, resample, rolling, diff/pct_change, melt, merge, concat, outlier handling, visual filters.
* **22 chart types** rendered with ECharts, plus a data-quality profile, correlation heatmap / scatter matrix / parallel coordinates, pivot heatmap, time-series workbench and statistical tests (t-test, ANOVA, chi-square, Shapiro-Wilk).
* **Bilingual by design**: the UI, axes, legends and category values switch between Chinese and English while the underlying data and generated pandas code stay identical.
* Export the cleaned data (CSV/Excel), the analysis script (`.py`) and a Markdown report.

```bash
pip install -r requirements.txt
python run.py
```
