"""数据集管理：4 套内置演示数据（真实 pandas 生成） + 本地文件上传解析。

设计要点
--------
1. 内置数据集不是静态 JSON，而是用 numpy/pandas 现场生成的“半真实”数据，
   含缺失值、重复行、离群点、时间趋势等真实脏数据特征，方便演示清洗与分析。
2. 每个内置数据集都带 **双语列名** 与 **双语类别取值** 映射，前端切换中英文时
   表格、坐标轴、图例同步切换，而底层列名保持不变（保证 pandas 代码可复现）。
3. 上传文件（CSV/TSV/TXT/JSON/JSONL/XLSX）落盘到 ``data/uploads``，重启后自动恢复。
"""
from __future__ import annotations

import io
import json
import re
import time
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from .utils import (
    UPLOAD_DIR,
    classify_series,
    dtype_name,
    shorten,
    to_native,
)

# ---------------------------------------------------------------------------
# 一、内置数据集定义
# ---------------------------------------------------------------------------

_SALES_LOCATIONS = [
    ("中国", "上海", "亚太", 1.00),
    ("中国", "北京", "亚太", 0.95),
    ("中国", "成都", "亚太", 0.60),
    ("中国", "深圳", "亚太", 0.72),
    ("日本", "东京", "亚太", 0.80),
    ("韩国", "首尔", "亚太", 0.58),
    ("新加坡", "新加坡", "亚太", 0.50),
    ("印度", "孟买", "亚太", 0.52),
    ("澳大利亚", "悉尼", "亚太", 0.46),
    ("美国", "纽约", "北美", 1.00),
    ("美国", "旧金山", "北美", 0.76),
    ("美国", "芝加哥", "北美", 0.60),
    ("加拿大", "多伦多", "北美", 0.52),
    ("墨西哥", "墨西哥城", "北美", 0.38),
    ("德国", "柏林", "欧洲", 0.70),
    ("英国", "伦敦", "欧洲", 0.85),
    ("法国", "巴黎", "欧洲", 0.72),
    ("西班牙", "马德里", "欧洲", 0.50),
    ("意大利", "米兰", "欧洲", 0.48),
    ("波兰", "华沙", "欧洲", 0.38),
    ("巴西", "圣保罗", "南美", 0.56),
    ("阿根廷", "布宜诺斯艾利斯", "南美", 0.38),
    ("智利", "圣地亚哥", "南美", 0.32),
    ("阿联酋", "迪拜", "中东", 0.52),
    ("沙特阿拉伯", "利雅得", "中东", 0.44),
    ("南非", "开普敦", "非洲", 0.34),
    ("埃及", "开罗", "非洲", 0.32),
]

_SALES_CATALOG = {
    "电子产品": {
        "智能手机": 4600,
        "笔记本电脑": 7800,
        "无线耳机": 890,
        "智能手表": 1980,
        "平板电脑": 3200,
        "显示器": 1500,
    },
    "家用电器": {
        "空气净化器": 1899,
        "扫地机器人": 2599,
        "咖啡机": 1299,
        "微波炉": 699,
        "电风扇": 259,
        "加湿器": 399,
    },
    "家居家具": {
        "人体工学椅": 1499,
        "实木书桌": 2199,
        "落地灯": 459,
        "布艺沙发": 4299,
        "收纳柜": 899,
        "乳胶床垫": 3299,
    },
    "服饰鞋包": {
        "羽绒服": 899,
        "运动鞋": 699,
        "双肩包": 429,
        "连衣裙": 559,
        "真皮腰带": 259,
        "棒球帽": 159,
    },
    "食品生鲜": {
        "精品咖啡豆": 128,
        "坚果礼盒": 168,
        "进口牛排": 259,
        "有机牛奶": 89,
        "山茶籽油": 119,
        "五常大米": 79,
    },
    "图书文创": {
        "商业图书": 68,
        "编程图书": 98,
        "儿童绘本": 45,
        "手账本": 39,
        "钢笔": 189,
        "拼图": 129,
    },
}

_SALES_CAT_COST = {
    "电子产品": 0.78,
    "家用电器": 0.72,
    "家居家具": 0.64,
    "服饰鞋包": 0.46,
    "食品生鲜": 0.68,
    "图书文创": 0.52,
}

_SALES_LABELS = {
    "订单号": "Order ID",
    "订单日期": "Order Date",
    "区域": "Region",
    "国家": "Country",
    "城市": "City",
    "品类": "Category",
    "商品": "Product",
    "渠道": "Channel",
    "客户类型": "Customer Segment",
    "支付方式": "Payment Method",
    "数量": "Quantity",
    "单价": "Unit Price",
    "折扣": "Discount",
    "销售额": "Revenue",
    "成本": "Cost",
    "利润": "Profit",
    "毛利率": "Gross Margin",
    "评分": "Rating",
    "是否退货": "Returned",
    "满意度": "Satisfaction",
    "订单月份": "Order Month",
}

_SALES_VALUE_LABELS = {
    "区域": {"亚太": "Asia Pacific", "北美": "North America", "欧洲": "Europe", "南美": "Latin America", "中东": "Middle East", "非洲": "Africa"},
    "国家": {
        "中国": "China", "日本": "Japan", "韩国": "South Korea", "新加坡": "Singapore", "印度": "India",
        "澳大利亚": "Australia", "美国": "United States", "加拿大": "Canada", "墨西哥": "Mexico",
        "德国": "Germany", "英国": "United Kingdom", "法国": "France", "西班牙": "Spain",
        "意大利": "Italy", "波兰": "Poland", "巴西": "Brazil", "阿根廷": "Argentina", "智利": "Chile",
        "阿联酋": "UAE", "沙特阿拉伯": "Saudi Arabia", "南非": "South Africa", "埃及": "Egypt",
    },
    "城市": {
        "上海": "Shanghai", "北京": "Beijing", "成都": "Chengdu", "深圳": "Shenzhen", "东京": "Tokyo",
        "首尔": "Seoul", "新加坡": "Singapore", "孟买": "Mumbai", "悉尼": "Sydney", "纽约": "New York",
        "旧金山": "San Francisco", "芝加哥": "Chicago", "多伦多": "Toronto", "墨西哥城": "Mexico City",
        "柏林": "Berlin", "伦敦": "London", "巴黎": "Paris", "马德里": "Madrid", "米兰": "Milan",
        "华沙": "Warsaw", "圣保罗": "São Paulo", "布宜诺斯艾利斯": "Buenos Aires", "圣地亚哥": "Santiago",
        "迪拜": "Dubai", "利雅得": "Riyadh", "开普敦": "Cape Town", "开罗": "Cairo",
    },
    "品类": {
        "电子产品": "Electronics", "家用电器": "Home Appliances", "家居家具": "Furniture",
        "服饰鞋包": "Apparel", "食品生鲜": "Fresh Food", "图书文创": "Books & Culture",
    },
    "商品": {
        "智能手机": "Smartphone", "笔记本电脑": "Laptop", "无线耳机": "Wireless Earbuds",
        "智能手表": "Smart Watch", "平板电脑": "Tablet", "显示器": "Monitor",
        "空气净化器": "Air Purifier", "扫地机器人": "Robot Vacuum", "咖啡机": "Coffee Machine",
        "微波炉": "Microwave", "电风扇": "Electric Fan", "加湿器": "Humidifier",
        "人体工学椅": "Ergonomic Chair", "实木书桌": "Wooden Desk", "落地灯": "Floor Lamp",
        "布艺沙发": "Fabric Sofa", "收纳柜": "Storage Cabinet", "乳胶床垫": "Latex Mattress",
        "羽绒服": "Down Jacket", "运动鞋": "Sneakers", "双肩包": "Backpack",
        "连衣裙": "Dress", "真皮腰带": "Leather Belt", "棒球帽": "Baseball Cap",
        "精品咖啡豆": "Specialty Coffee Bean", "坚果礼盒": "Nut Gift Box", "进口牛排": "Imported Steak",
        "有机牛奶": "Organic Milk", "山茶籽油": "Camellia Oil", "五常大米": "Wuchang Rice",
        "商业图书": "Business Book", "编程图书": "Programming Book", "儿童绘本": "Picture Book",
        "手账本": "Journal", "钢笔": "Fountain Pen", "拼图": "Jigsaw Puzzle",
    },
    "渠道": {"线上商城": "Online Store", "线下门店": "Offline Store", "分销渠道": "Distributor", "海外直邮": "Cross-border"},
    "客户类型": {"个人客户": "Consumer", "中小企业": "SMB", "大型企业": "Enterprise", "政府机构": "Government"},
    "支付方式": {"信用卡": "Credit Card", "电子钱包": "E-Wallet", "银行转账": "Bank Transfer", "货到付款": "Cash on Delivery"},
    "是否退货": {"是": "Yes", "否": "No"},
    "满意度": {"非常满意": "Very Satisfied", "满意": "Satisfied", "一般": "Neutral", "不满意": "Dissatisfied"},
}

_IRIS_LABELS = {
    "品种": "Species",
    "花萼长度": "Sepal Length",
    "花萼宽度": "Sepal Width",
    "花瓣长度": "Petal Length",
    "花瓣宽度": "Petal Width",
    "种植区": "Plot",
    "植株编号": "Plant ID",
}
_IRIS_VALUE_LABELS = {
    "品种": {"山鸢尾": "Setosa", "变色鸢尾": "Versicolor", "维吉尼亚鸢尾": "Virginica"},
    "种植区": {"A区": "Plot A", "B区": "Plot B", "C区": "Plot C"},
}

_AIR_LABELS = {
    "日期": "Date",
    "城市": "City",
    "AQI": "AQI",
    "PM2.5": "PM2.5",
    "PM10": "PM10",
    "臭氧": "Ozone",
    "二氧化氮": "NO2",
    "二氧化硫": "SO2",
    "一氧化碳": "CO",
    "温度": "Temperature",
    "湿度": "Humidity",
    "风速": "Wind Speed",
    "天气": "Weather",
    "是否周末": "Is Weekend",
}
_AIR_VALUE_LABELS = {
    "城市": {"北京": "Beijing", "上海": "Shanghai", "广州": "Guangzhou", "成都": "Chengdu", "西安": "Xi'an"},
    "天气": {"晴": "Sunny", "多云": "Cloudy", "阴": "Overcast", "小雨": "Light Rain", "中雨": "Moderate Rain", "小雪": "Light Snow"},
    "是否周末": {"周末": "Weekend", "工作日": "Weekday"},
}

_COUNTRY_LABELS = {
    "国家": "Country",
    "大洲": "Continent",
    "年份": "Year",
    "人口(万)": "Population (10k)",
    "人均GDP(美元)": "GDP per Capita (USD)",
    "预期寿命": "Life Expectancy",
    "互联网普及率(%)": "Internet Penetration (%)",
    "人均碳排放(吨)": "CO2 per Capita (t)",
    "城镇化率(%)": "Urbanization (%)",
    "幸福指数": "Happiness Index",
}
_COUNTRY_VALUE_LABELS = {
    "大洲": {"亚洲": "Asia", "欧洲": "Europe", "北美洲": "North America", "南美洲": "South America", "非洲": "Africa", "大洋洲": "Oceania"},
}

# 国家基线：(中文名, 英文名, 大洲, 人口万, 人均GDP, 预期寿命, 互联网%, 人均碳排, 城镇化%, 幸福指数)
_COUNTRY_BASE = [
    ("中国", "China", "亚洲", 141000, 12700, 78.2, 76.4, 8.0, 65.2, 5.9),
    ("印度", "India", "亚洲", 142800, 2500, 70.4, 46.3, 1.9, 36.4, 4.1),
    ("日本", "Japan", "亚洲", 12450, 33800, 84.5, 83.0, 8.5, 91.9, 6.1),
    ("韩国", "South Korea", "亚洲", 5174, 33100, 83.5, 97.6, 11.9, 81.4, 6.0),
    ("印度尼西亚", "Indonesia", "亚洲", 27900, 4900, 71.7, 66.5, 2.6, 58.6, 5.2),
    ("越南", "Vietnam", "亚洲", 9950, 4300, 74.6, 79.1, 3.5, 39.5, 5.5),
    ("泰国", "Thailand", "亚洲", 7180, 7300, 79.0, 88.0, 3.8, 53.6, 5.8),
    ("新加坡", "Singapore", "亚洲", 592, 82800, 83.7, 96.9, 8.9, 100.0, 6.5),
    ("马来西亚", "Malaysia", "亚洲", 3430, 12000, 76.7, 97.4, 8.6, 78.2, 6.0),
    ("沙特阿拉伯", "Saudi Arabia", "亚洲", 3690, 30500, 78.7, 100.0, 18.0, 84.7, 6.4),
    ("阿联酋", "UAE", "亚洲", 1030, 49400, 79.3, 100.0, 21.8, 87.5, 6.6),
    ("土耳其", "Türkiye", "亚洲", 8530, 13000, 78.6, 83.4, 5.3, 77.0, 4.9),
    ("以色列", "Israel", "亚洲", 976, 52200, 82.7, 90.3, 6.4, 92.7, 7.4),
    ("德国", "Germany", "欧洲", 8450, 52700, 81.4, 93.0, 7.9, 77.7, 6.9),
    ("英国", "United Kingdom", "欧洲", 6760, 49000, 81.3, 96.7, 5.2, 84.4, 6.8),
    ("法国", "France", "欧洲", 6820, 44500, 83.2, 93.1, 4.7, 81.8, 6.7),
    ("意大利", "Italy", "欧洲", 5890, 38500, 83.5, 85.1, 5.7, 71.9, 6.5),
    ("西班牙", "Spain", "欧洲", 4840, 33500, 83.6, 95.8, 5.0, 81.6, 6.4),
    ("荷兰", "Netherlands", "欧洲", 1790, 62500, 82.2, 97.1, 7.6, 93.2, 7.4),
    ("瑞士", "Switzerland", "欧洲", 890, 93700, 84.0, 96.5, 4.4, 74.0, 7.5),
    ("瑞典", "Sweden", "欧洲", 1060, 56300, 83.1, 95.5, 4.2, 88.2, 7.3),
    ("波兰", "Poland", "欧洲", 3670, 22100, 78.0, 87.6, 8.7, 60.0, 6.1),
    ("俄罗斯", "Russia", "欧洲", 14380, 13900, 73.3, 90.7, 12.1, 75.1, 5.7),
    ("美国", "United States", "北美洲", 33500, 81700, 77.5, 91.9, 14.9, 83.3, 6.7),
    ("加拿大", "Canada", "北美洲", 4010, 53300, 82.6, 94.6, 14.2, 81.9, 7.0),
    ("墨西哥", "Mexico", "北美洲", 12900, 13900, 75.1, 78.6, 3.7, 81.6, 6.3),
    ("古巴", "Cuba", "北美洲", 1120, 9500, 78.1, 73.8, 2.4, 77.4, 5.4),
    ("危地马拉", "Guatemala", "北美洲", 1800, 5600, 69.2, 65.1, 1.4, 53.0, 6.0),
    ("巴西", "Brazil", "南美洲", 21600, 10100, 75.9, 84.3, 2.2, 87.6, 6.3),
    ("阿根廷", "Argentina", "南美洲", 4560, 13700, 76.6, 88.4, 4.1, 92.3, 6.0),
    ("智利", "Chile", "南美洲", 1960, 17000, 80.2, 90.2, 4.4, 87.9, 6.5),
    ("哥伦比亚", "Colombia", "南美洲", 5220, 6600, 72.8, 74.0, 1.8, 82.1, 5.6),
    ("秘鲁", "Peru", "南美洲", 3380, 7900, 72.4, 74.7, 1.7, 78.9, 5.5),
    ("南非", "South Africa", "非洲", 6040, 6200, 62.3, 72.3, 7.6, 68.3, 5.2),
    ("埃及", "Egypt", "非洲", 11270, 3500, 70.2, 72.2, 2.4, 43.1, 4.2),
    ("尼日利亚", "Nigeria", "非洲", 22380, 2200, 53.6, 55.4, 0.6, 54.3, 4.9),
    ("肯尼亚", "Kenya", "非洲", 5510, 2100, 63.7, 42.2, 0.4, 29.5, 4.4),
    ("摩洛哥", "Morocco", "非洲", 3780, 3700, 74.6, 88.1, 1.9, 65.1, 5.0),
    ("加纳", "Ghana", "非洲", 3410, 2200, 64.1, 68.2, 0.6, 58.3, 4.6),
    ("埃塞俄比亚", "Ethiopia", "非洲", 12650, 1300, 65.4, 25.0, 0.2, 22.7, 4.1),
    ("澳大利亚", "Australia", "大洋洲", 2640, 64800, 83.2, 96.2, 15.4, 86.6, 7.1),
    ("新西兰", "New Zealand", "大洋洲", 522, 48800, 82.5, 95.0, 6.9, 86.9, 7.3),
]


def _build_sales() -> pd.DataFrame:
    rng = np.random.default_rng(20240521)
    n = 4000
    loc = pd.DataFrame(_SALES_LOCATIONS, columns=["国家", "城市", "区域", "权重"])
    weights = loc["权重"].to_numpy(dtype=float)
    weights = weights / weights.sum()
    idx = rng.choice(len(loc), size=n, p=weights)
    country = loc["国家"].to_numpy()[idx]
    city = loc["城市"].to_numpy()[idx]
    region = loc["区域"].to_numpy()[idx]

    cat_names = list(_SALES_CATALOG)
    cat_p = np.array([1.00, 0.78, 0.66, 1.05, 0.92, 0.55])
    cat_p = cat_p / cat_p.sum()
    category = rng.choice(cat_names, size=n, p=cat_p)

    product = np.empty(n, dtype=object)
    unit_price = np.zeros(n)
    cost_rate = np.zeros(n)
    for cat in cat_names:
        mask = category == cat
        k = int(mask.sum())
        if k == 0:
            continue
        items = list(_SALES_CATALOG[cat])
        base = np.array([_SALES_CATALOG[cat][item] for item in items], dtype=float)
        item_p = base / base.sum()
        picked = rng.choice(items, size=k, p=item_p)
        product[mask] = picked
        picked_base = np.array([_SALES_CATALOG[cat][item] for item in picked], dtype=float)
        unit_price[mask] = np.round(picked_base * rng.lognormal(0, 0.16, size=k), 2)
        cost_rate[mask] = np.clip(_SALES_CAT_COST[cat] + rng.normal(0, 0.05, size=k), 0.32, 0.94)

    channel = rng.choice(["线上商城", "线下门店", "分销渠道", "海外直邮"], size=n, p=[0.40, 0.30, 0.18, 0.12])
    segment = rng.choice(["个人客户", "中小企业", "大型企业", "政府机构"], size=n, p=[0.56, 0.24, 0.13, 0.07])
    payment = rng.choice(["信用卡", "电子钱包", "银行转账", "货到付款"], size=n, p=[0.33, 0.37, 0.20, 0.10])

    lam = np.select(
        [segment == "个人客户", segment == "中小企业", segment == "大型企业"],
        [1.7, 4.6, 9.5],
        default=6.8,
    )
    qty = rng.poisson(lam) + 1
    # 批发大单：制造少量离群点，用于演示箱线图 / IQR 异常检测
    bulk = rng.choice(n, size=26, replace=False)
    qty[bulk] = rng.integers(60, 150, size=len(bulk))
    qty = qty.astype(int)

    discount_levels = np.array([0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35])
    discount_p = np.array([0.30, 0.18, 0.15, 0.12, 0.10, 0.07, 0.05, 0.03])
    discount = discount_levels[rng.choice(len(discount_levels), size=n, p=discount_p)]
    is_big = np.isin(segment, ["大型企业", "政府机构"])
    discount = np.where(is_big, np.round(np.clip(discount + 0.05, 0, 0.40), 2), discount)

    revenue = np.round(unit_price * qty * (1 - discount), 2)
    cost = np.round(revenue * cost_rate, 2)
    profit = np.round(revenue - cost, 2)
    margin = np.round(np.where(revenue > 0, profit / revenue, 0), 4)

    rating = np.round(np.clip(rng.normal(np.where(segment == "个人客户", 4.25, 3.95), 0.55, n), 1, 5), 1)
    rating = np.where(rng.random(n) < 0.085, np.nan, rating)
    satisfaction = np.select(
        [rating >= 4.5, rating >= 3.8, rating >= 3.0],
        ["非常满意", "满意", "一般"],
        default="不满意",
    )
    satisfaction = np.where(np.isnan(rating), None, satisfaction)

    returned = np.where(rng.random(n) < np.clip(0.035 + discount * 0.28 + (rating < 3.5) * 0.12, 0, 0.6), "是", "否")

    order_days = pd.date_range("2023-01-01", "2024-12-31", freq="D")
    month_weight = np.array([0.80, 0.72, 0.92, 0.96, 1.00, 1.06, 1.02, 0.98, 1.08, 1.14, 1.38, 1.46])
    day_w = month_weight[order_days.month - 1] * (1 + 0.45 * np.linspace(0, 1, len(order_days)))
    day_w = day_w / day_w.sum()
    picked_days = order_days[rng.choice(len(order_days), size=n, p=day_w)]
    order_date = picked_days + pd.to_timedelta(rng.integers(0, 24 * 60, size=n), unit="m")

    city_missing = rng.random(n) < 0.006
    city_series = np.where(city_missing, None, city)

    df = pd.DataFrame(
        {
            "订单号": [f"SO-{100000 + i}" for i in range(n)],
            "订单日期": order_date,
            "区域": region,
            "国家": country,
            "城市": city_series,
            "品类": category,
            "商品": product,
            "渠道": channel,
            "客户类型": segment,
            "支付方式": payment,
            "数量": qty,
            "单价": unit_price,
            "折扣": discount,
            "销售额": revenue,
            "成本": cost,
            "利润": profit,
            "毛利率": margin,
            "评分": rating,
            "是否退货": returned,
            "满意度": satisfaction,
            "订单月份": order_date.to_period("M").astype(str),
        }
    )
    df = df.sort_values("订单日期").reset_index(drop=True)
    df["订单号"] = [f"SO-{100000 + i}" for i in range(len(df))]
    return df


def _build_flowers() -> pd.DataFrame:
    """鸢尾花测量数据（按 Fisher 经典统计量模拟生成，含缺失与重复行）。"""
    rng = np.random.default_rng(7)
    specs = [
        ("山鸢尾", (5.006, 3.428, 1.462, 0.246), (0.121, 0.144, 0.030, 0.011), 0.18),
        ("变色鸢尾", (5.936, 2.770, 4.260, 1.326), (0.266, 0.098, 0.221, 0.039), 0.34),
        ("维吉尼亚鸢尾", (6.588, 2.974, 5.552, 2.026), (0.404, 0.104, 0.305, 0.075), 0.30),
    ]
    frames = []
    for species, mean, var, corr in specs:
        cov = np.diag(var).astype(float)
        cov[0, 2] = cov[2, 0] = corr * 0.30
        cov[1, 3] = cov[3, 1] = -corr * 0.05
        sample = rng.multivariate_normal(mean, cov, size=50)
        frames.append(
            pd.DataFrame(
                {
                    "品种": species,
                    "花萼长度": np.round(np.clip(sample[:, 0], 4.0, 8.5), 1),
                    "花萼宽度": np.round(np.clip(sample[:, 1], 1.8, 4.6), 1),
                    "花瓣长度": np.round(np.clip(sample[:, 2], 0.8, 7.2), 1),
                    "花瓣宽度": np.round(np.clip(sample[:, 3], 0.05, 2.8), 1),
                }
            )
        )
    df = pd.concat(frames, ignore_index=True)
    df["种植区"] = np.tile(rng.choice(["A区", "B区", "C区"], size=150, p=[0.36, 0.34, 0.30]), 1)
    df["植株编号"] = [f"P-{i + 1:03d}" for i in range(len(df))]
    # 重复行（模拟录入重复）+ 缺失值（模拟漏测）
    dup = df.sample(12, random_state=11)
    df = pd.concat([df, dup], ignore_index=True)
    for col, frac in (("花瓣宽度", 0.04), ("花萼宽度", 0.03)):
        holes = rng.random(len(df)) < frac
        df.loc[holes, col] = np.nan
    return df


def _build_air_quality() -> pd.DataFrame:
    rng = np.random.default_rng(31415)
    cities = [
        ("北京", 62, 1.00, 12.5),
        ("上海", 48, 0.78, 16.5),
        ("广州", 34, 0.55, 22.5),
        ("成都", 55, 0.92, 16.0),
        ("西安", 66, 1.10, 14.0),
    ]
    dates = pd.date_range("2023-01-01", "2024-12-31", freq="D")
    doy = dates.dayofyear.to_numpy()
    winter = np.cos((doy - 15) / 365.25 * 2 * np.pi)  # 冬季≈1，夏季≈-1
    summer = -winter
    rows = []
    for city, base, amp, temp_base in cities:
        noise = rng.normal(0, 1, len(dates))
        aqi = base + 55 * amp * winter + 8 * np.sin(doy / 365 * 2 * np.pi * 2) + rng.normal(0, 14, len(dates))
        aqi = np.clip(aqi, 14, 320)
        weekend = dates.dayofweek.to_numpy() >= 5
        aqi = aqi * np.where(weekend, 0.93, 1.0)
        pm25 = np.clip(aqi * 0.62 + rng.normal(0, 7, len(dates)), 3, 260)
        pm10 = np.clip(pm25 * 1.55 + rng.normal(0, 12, len(dates)), 8, 400)
        ozone = np.clip(48 + 42 * summer + rng.normal(0, 12, len(dates)), 5, 190)
        no2 = np.clip(22 + 26 * amp * winter + rng.normal(0, 7, len(dates)), 4, 120)
        so2 = np.clip(6 + 18 * amp * winter + rng.normal(0, 4, len(dates)), 1, 90)
        co = np.clip(0.55 + 0.35 * winter + rng.normal(0, 0.18, len(dates)), 0.1, 4.0)
        temp = temp_base + 13.5 * summer + rng.normal(0, 3.0, len(dates))
        humidity = np.clip(62 + 18 * summer + rng.normal(0, 12, len(dates)), 15, 100)
        wind = np.clip(rng.gamma(2.2, 1.1, len(dates)), 0.2, 12)
        weather = np.select(
            [
                (pm25 > 90) & (humidity > 60),
                (humidity > 85) & (temp > 3),
                (humidity > 78) & (temp <= 3),
                humidity > 72,
                temp < -2,
            ],
            ["阴", "小雨", "小雪", "多云", "阴"],
            default="晴",
        )
        weather = np.where((rng.random(len(dates)) < 0.10) & (humidity > 70), "中雨", weather)
        frame = pd.DataFrame(
            {
                "日期": dates,
                "城市": city,
                "AQI": np.round(aqi, 0),
                "PM2.5": np.round(pm25, 1),
                "PM10": np.round(pm10, 1),
                "臭氧": np.round(ozone, 1),
                "二氧化氮": np.round(no2, 1),
                "二氧化硫": np.round(so2, 1),
                "一氧化碳": np.round(co, 2),
                "温度": np.round(temp, 1),
                "湿度": np.round(humidity, 0),
                "风速": np.round(wind, 1),
                "天气": weather,
                "是否周末": np.where(weekend, "周末", "工作日"),
            }
        )
        rows.append(frame)
    df = pd.concat(rows, ignore_index=True)
    for col, frac in (("PM2.5", 0.015), ("PM10", 0.018), ("湿度", 0.012), ("温度", 0.008)):
        holes = rng.random(len(df)) < frac
        df.loc[holes, col] = np.nan
    return df.sort_values(["日期", "城市"]).reset_index(drop=True)


def _build_countries() -> pd.DataFrame:
    rows = []
    for zh, en, continent, pop, gdp, life, net, co2, urban, happy in _COUNTRY_BASE:
        for year in range(2019, 2025):
            step = year - 2019
            growth = 1.0 + 0.021 * step + (0.012 * step if continent in ("亚洲", "非洲") else 0.004 * step)
            gdp_year = gdp * growth
            rows.append(
                {
                    "国家": zh,
                    "国家_en": en,
                    "大洲": continent,
                    "年份": year,
                    "人口(万)": round(pop * (1 + 0.006 * step), 1),
                    "人均GDP(美元)": round(gdp_year, 0),
                    "预期寿命": round(life + 0.16 * step, 1),
                    "互联网普及率(%)": round(min(100.0, net + 1.7 * step), 1),
                    "人均碳排放(吨)": round(max(0.1, co2 * (1 - 0.012 * step) + (0.03 if continent == "亚洲" else 0.0)), 2),
                    "城镇化率(%)": round(min(100.0, urban + 0.37 * step), 1),
                    "幸福指数": round(happy + 0.02 * step + (0.03 if gdp > 20000 else 0.0), 2),
                }
            )
    df = pd.DataFrame(rows)
    return df.drop(columns=["国家_en"])


# ---------------------------------------------------------------------------
# 二、数据集注册表
# ---------------------------------------------------------------------------

BUILTIN_SPECS = {
    "sales": {
        "builder": _build_sales,
        "name": {"zh": "全球零售订单 (2023-2024)", "en": "Global Retail Orders (2023-2024)"},
        "description": {
            "zh": "4,000 条跨国零售订单，含缺失值、重复折扣梯度、批发大单离群点，适合演示分组聚合、透视、时间趋势、相关性、异常检测。",
            "en": "4,000 cross-border retail orders with missing values, discount tiers and bulk-order outliers. Great for groupby, pivot, time series, correlation and outlier detection.",
        },
        "labels": _SALES_LABELS,
        "value_labels": _SALES_VALUE_LABELS,
    },
    "airquality": {
        "builder": _build_air_quality,
        "name": {"zh": "城市空气质量时序 (2023-2024)", "en": "Urban Air Quality Time Series (2023-2024)"},
        "description": {
            "zh": "5 座城市 × 731 天 = 3,655 条空气质量与气象观测，含季节性与周末效应，适合演示滚动均值、重采样、热力图、气泡图。",
            "en": "5 cities × 731 days = 3,655 observations with seasonality and weekend effects, ideal for rolling means, resampling, heatmaps and bubble charts.",
        },
        "labels": _AIR_LABELS,
        "value_labels": _AIR_VALUE_LABELS,
    },
    "flowers": {
        "builder": _build_flowers,
        "name": {"zh": "鸢尾花形态测量 (含重复/缺失)", "en": "Iris Flower Measurements (dirty)"},
        "description": {
            "zh": "162 行（含 12 行重复录入与随机缺失）的三大鸢尾品种形态测量，是散点矩阵、平行坐标、箱线图、聚类结构的经典教学数据。",
            "en": "162 rows (12 duplicated + random missing) across three iris species — the classic dataset for scatter matrix, parallel coordinates and boxplots.",
        },
        "labels": _IRIS_LABELS,
        "value_labels": _IRIS_VALUE_LABELS,
    },
    "countries": {
        "builder": _build_countries,
        "name": {"zh": "国家发展指标 (2019-2024)", "en": "Country Development Indicators (2019-2024)"},
        "description": {
            "zh": "42 个国家 × 6 年发展指标，适合演示气泡图、树图、平行坐标、跨年趋势对比与对数坐标。",
            "en": "42 countries × 6 years of development indicators, great for bubble charts, treemap, parallel coordinates and log-scale comparison.",
        },
        "labels": _COUNTRY_LABELS,
        "value_labels": _COUNTRY_VALUE_LABELS,
    },
}


class DatasetStore:
    """内存 + 磁盘的数据集注册表。上传文件落盘，重启后自动恢复。"""

    def __init__(self, upload_dir: Path = UPLOAD_DIR):
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self._frames: dict[str, pd.DataFrame] = {}
        self._meta: dict[str, dict] = {}
        self._cache: dict[str, pd.DataFrame] = {}

    # -- 内置数据集 ---------------------------------------------------------
    def ensure_builtins(self, force: bool = False):
        for key, spec in BUILTIN_SPECS.items():
            if key in self._meta and not force:
                continue
            df = spec["builder"]()
            self._frames[key] = df
            self._meta[key] = {
                "id": key,
                "source": "builtin",
                "name": dict(spec["name"]),
                "description": dict(spec["description"]),
                "labels": dict(spec["labels"]),
                "value_labels": {k: dict(v) for k, v in spec["value_labels"].items()},
                "created_at": _now_iso(),
                "file_name": None,
                "size_bytes": int(df.memory_usage(deep=True).sum()),
            }
        self._load_index()

    # -- 上传数据集 ---------------------------------------------------------
    def _index_path(self) -> Path:
        return self.upload_dir / "index.json"

    def _load_index(self):
        path = self._index_path()
        if not path.exists():
            return
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for record in records:
            stored = self.upload_dir / f"{record['id']}{Path(record['file_name']).suffix.lower()}"
            if not stored.exists() or record["id"] in self._frames:
                continue
            try:
                df = read_table(stored, record.get("options") or {})
            except Exception:  # 损坏的上传文件不应阻塞启动
                continue
            self._frames[record["id"]] = df
            self._meta[record["id"]] = {
                **record,
                "size_bytes": int(df.memory_usage(deep=True).sum()),
            }

    def _save_index(self):
        records = [m for m in self._meta.values() if m.get("source") == "upload"]
        self._index_path().write_text(json.dumps(to_native(records), ensure_ascii=False, indent=2), encoding="utf-8")

    def add_upload(self, file_storage, options: dict | None = None) -> dict:
        original = Path(file_storage.filename or "upload.csv").name
        suffix = Path(original).suffix.lower() or ".csv"
        dataset_id = f"up_{uuid.uuid4().hex[:10]}"
        stored = self.upload_dir / f"{dataset_id}{suffix}"
        file_storage.save(stored)
        options = options or {}
        try:
            df = read_table(stored, options)
        except Exception:
            stored.unlink(missing_ok=True)
            raise
        display = options.get("display_name") or Path(original).stem
        self._frames[dataset_id] = df
        self._meta[dataset_id] = {
            "id": dataset_id,
            "source": "upload",
            "name": {"zh": display, "en": options.get("display_name_en") or display},
            "description": {
                "zh": f"本地上传文件 {original}（{len(df):,} 行 × {df.shape[1]} 列）",
                "en": f"Locally uploaded file {original} ({len(df):,} rows × {df.shape[1]} columns)",
            },
            "labels": {},
            "value_labels": {},
            "created_at": _now_iso(),
            "file_name": original,
            "options": to_native(options),
            "size_bytes": int(df.memory_usage(deep=True).sum()),
        }
        self._save_index()
        return self.describe(dataset_id)

    def remove(self, dataset_id: str) -> bool:
        meta = self._meta.get(dataset_id)
        if meta is None or meta.get("source") != "upload":
            return False
        stored = self.upload_dir / f"{dataset_id}{Path(meta['file_name']).suffix.lower()}"
        stored.unlink(missing_ok=True)
        self._frames.pop(dataset_id, None)
        self._meta.pop(dataset_id, None)
        self._save_index()
        return True

    # -- 访问 ---------------------------------------------------------------
    def has(self, dataset_id: str) -> bool:
        return dataset_id in self._frames

    def frame(self, dataset_id: str) -> pd.DataFrame:
        """返回副本，避免下游管道修改污染原始数据。"""
        if dataset_id not in self._frames:
            raise KeyError(dataset_id)
        return self._frames[dataset_id]

    def meta(self, dataset_id: str) -> dict:
        return self._meta[dataset_id]

    def list(self) -> list[dict]:
        out = []
        for dataset_id, meta in self._meta.items():
            df = self._frames[dataset_id]
            out.append(
                {
                    "id": dataset_id,
                    "source": meta.get("source"),
                    "name": meta.get("name"),
                    "description": meta.get("description"),
                    "rows": int(len(df)),
                    "cols": int(df.shape[1]),
                    "size_bytes": int(df.memory_usage(deep=True).sum()),
                    "file_name": meta.get("file_name"),
                    "created_at": meta.get("created_at"),
                }
            )
        out.sort(key=lambda item: (item["source"] != "builtin", item["id"]))
        return out

    def describe(self, dataset_id: str) -> dict:
        df = self._frames[dataset_id]
        meta = self._meta[dataset_id]
        labels = meta.get("labels") or {}
        value_labels = meta.get("value_labels") or {}
        columns = []
        for col in df.columns:
            series = df[col]
            kind = classify_series(series)
            non_null = series.dropna()
            sample = [shorten(v, 32) for v in non_null.head(3).tolist()]
            col_values = None
            if kind in ("categorical", "boolean") and col in value_labels:
                col_values = value_labels[col]
            columns.append(
                {
                    "name": str(col),
                    "dtype": dtype_name(series),
                    "kind": kind,
                    "missing": int(series.isna().sum()),
                    "missing_rate": round(float(series.isna().mean()), 4),
                    "nunique": int(non_null.nunique()),
                    "label": {"zh": str(col), "en": labels.get(str(col), str(col))},
                    "value_labels": col_values,
                    "samples": sample,
                }
            )
        return {
            "id": dataset_id,
            "source": meta.get("source"),
            "name": meta.get("name"),
            "description": meta.get("description"),
            "created_at": meta.get("created_at"),
            "file_name": meta.get("file_name"),
            "rows": int(len(df)),
            "cols": int(df.shape[1]),
            "size_bytes": int(df.memory_usage(deep=True).sum()),
            "columns": columns,
        }


# ---------------------------------------------------------------------------
# 三、文件解析
# ---------------------------------------------------------------------------

_CSV_SUFFIXES = {".csv", ".tsv", ".txt", ".dat"}
_JSON_SUFFIXES = {".json", ".jsonl", ".ndjson"}
_EXCEL_SUFFIXES = {".xlsx", ".xls", ".xlsm"}


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """统一列名：去首尾空白、去 BOM、重复列名加序号。"""
    seen: dict[str, int] = {}
    new_columns = []
    for col in df.columns:
        name = str(col).replace("\ufeff", "").strip() or "列"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        new_columns.append(name)
    df.columns = new_columns
    return df


def _coerce_text_columns(df: pd.DataFrame, infer: bool = True) -> pd.DataFrame:
    if not infer:
        return df
    for col in df.columns:
        if df[col].dtype == object:
            converted = pd.to_numeric(df[col], errors="coerce")
            if converted.notna().sum() >= max(3, int(0.9 * df[col].notna().sum())):
                df[col] = converted
    return df


def sniff_csv_options(path: Path) -> dict:
    """嗅探编码与分隔符，尽最大努力读入中文 CSV。"""
    raw = path.read_bytes()[:262144]
    encoding = "utf-8"
    for candidate in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            text = raw.decode(candidate)
            encoding = candidate
            break
        except UnicodeDecodeError:
            continue
    sample = text.splitlines()[:20]
    delimiter = ","
    best = 0
    for candidate in (",", "\t", ";", "|"):
        counts = [line.count(candidate) for line in sample if line.strip()]
        if counts:
            score = min(counts) if min(counts) > 0 else 0
            if score > best:
                best, delimiter = score, candidate
    return {"encoding": encoding, "sep": delimiter}


def read_table(path: Path, options: dict | None = None) -> pd.DataFrame:
    options = dict(options or {})
    suffix = path.suffix.lower()
    if suffix in _EXCEL_SUFFIXES:
        sheet = options.get("sheet") or 0
        df = pd.read_excel(path, sheet_name=sheet)
        return _coerce_text_columns(_clean_columns(df))
    if suffix in _JSON_SUFFIXES:
        if suffix in {".jsonl", ".ndjson"}:
            df = pd.read_json(path, lines=True)
        else:
            try:
                df = pd.read_json(path)
            except ValueError:
                text = path.read_text(encoding=options.get("encoding", "utf-8"), errors="replace")
                payload = json.loads(text)
                if isinstance(payload, dict):
                    for key in ("data", "rows", "records", "items", "result"):
                        if isinstance(payload.get(key), list):
                            payload = payload[key]
                            break
                df = pd.json_normalize(payload)
        if df.shape[1] == 1 and isinstance(df.iloc[:, 0].iloc[0] if len(df) else None, (dict, list)):
            df = pd.json_normalize(df.iloc[:, 0].tolist())
        return _coerce_text_columns(_clean_columns(df))
    # CSV / TSV / 其它文本
    sniffed = sniff_csv_options(path)
    encoding = options.get("encoding") or sniffed["encoding"]
    sep = options.get("sep") or sniffed["sep"]
    if sep == "auto":
        sep = sniffed["sep"]
    header_row = int(options.get("header_row", 0) or 0)
    decimal = options.get("decimal") or "."
    df = pd.read_csv(
        path,
        sep=sep,
        encoding=encoding,
        header=header_row,
        decimal=decimal,
        skip_blank_lines=True,
        keep_default_na=True,
        na_values=["", "NA", "N/A", "null", "NULL", "None", "-", "—", "nan", "NaN"],
        engine="python",
    )
    return _coerce_text_columns(_clean_columns(df))


def _now_iso() -> str:
    return pd.Timestamp.now().tz_localize(None).isoformat(timespec="seconds")


STORE = DatasetStore()
