"""PandasViz Studio —— 可视化 pandas 数据分析工作台（后端包）。

模块划分：
* ``datasets``  —— 内置数据集生成、上传解析、数据集注册表
* ``engine``    —— pandas 操作管道（算子注册表 + 执行 + 代码生成）
* ``analysis``  —— 画像 / 图表数据 / 相关性 / 透视 / 时序 / 统计检验 / 自动洞察
* ``exporting`` —— CSV / Excel / pandas 脚本 / Markdown 报告导出
* ``app``       —— Flask 应用（REST API + 静态前端）
"""

__all__ = ["engine", "analysis", "datasets", "exporting"]
__version__ = "1.0.0"
