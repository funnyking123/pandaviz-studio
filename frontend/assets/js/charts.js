/* ==========================================================================
   图表层：把后端返回的“可视化就绪数据”渲染成 ECharts 图形
   覆盖 22 种图表类型 + 画像小图（质量仪表、缺失矩阵、分布迷你图、漏斗）
   ========================================================================== */

import { getLang, localize, valueLabel, columnLabel, t } from './i18n.js';

const PALETTE = ['#4f8cff', '#22d3ee', '#a855f7', '#34d399', '#fbbf24', '#fb7185',
  '#60a5fa', '#f472b6', '#2dd4bf', '#c084fc', '#facc15', '#38bdf8',
  '#f97316', '#a3e635', '#e879f9', '#14b8a6'];

export function themeVars() {
  const light = document.body.dataset.theme === 'light';
  return {
    light,
    text: light ? '#101a33' : '#e9eeff',
    dim: light ? '#61708f' : '#8f9dc2',
    line: light ? 'rgba(30,60,130,.14)' : 'rgba(122,152,220,.18)',
    grid: light ? 'rgba(30,60,130,.09)' : 'rgba(122,152,220,.10)',
    panel: light ? '#ffffff' : '#131b30',
    colors: PALETTE,
    tooltip: {
      backgroundColor: light ? 'rgba(255,255,255,.96)' : 'rgba(19,27,48,.96)',
      borderColor: light ? 'rgba(30,60,130,.18)' : 'rgba(122,152,220,.28)',
      textStyle: { color: light ? '#101a33' : '#e9eeff', fontSize: 12 },
    },
  };
}

/** 数字紧凑显示（1.2万 / 1.2k） */
export function fmtNumber(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '—';
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  const abs = Math.abs(num);
  const en = getLang() === 'en';
  const trim = (text) => text.replace(/\.0+$/, '').replace(/(\.\d)0$/, '$1');
  if (abs >= 1e12) return `${trim((num / 1e12).toFixed(digits))}${en ? 'T' : '万亿'}`;
  if (abs >= 1e8) return `${trim((num / 1e8).toFixed(digits))}${en ? 'B' : '亿'}`;
  if (abs >= 1e4) return `${trim((num / 1e4).toFixed(digits))}${en ? 'k' : '万'}`;
  if (abs >= 1000) return num.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (Number.isInteger(num)) return String(num);
  return Number(num.toFixed(4)).toString();
}

export function fmtRate(value) {
  if (value === null || value === undefined) return '—';
  return `${(Number(value) * 100).toFixed(2)}%`;
}

/* --------------------------- 实例管理 --------------------------- */

const charts = new WeakMap();

export function renderChart(el, option) {
  if (!el) return null;
  let chart = charts.get(el);
  if (!chart || chart.isDisposed()) {
    chart = echarts.init(el, null, { renderer: 'canvas' });
    charts.set(el, chart);
    el.__pandavizChart = chart;
  }
  chart.setOption({ color: PALETTE, backgroundColor: 'transparent', ...option }, true);
  return chart;
}

export function resizeAllCharts() {
  document.querySelectorAll('.chart-box, .spark').forEach((el) => {
    const chart = charts.get(el) || el.__pandavizChart;
    if (chart && !chart.isDisposed()) chart.resize();
  });
}

let resizeTimer = null;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(resizeAllCharts, 120);
});

function baseGrid(opts = {}) {
  return {
    left: opts.left || 62,
    right: opts.right || 28,
    top: opts.top || 46,
    bottom: opts.bottom || 62,
    containLabel: true,
  };
}

function axisStyle(vars, name, rotate) {
  return {
    name,
    nameTextStyle: { color: vars.dim, fontSize: 11 },
    axisLabel: { color: vars.dim, fontSize: 11, rotate: rotate || 0, hideOverlap: true },
    axisLine: { lineStyle: { color: vars.line } },
    splitLine: { lineStyle: { color: vars.grid } },
    nameLocation: 'middle',
    nameGap: 30,
  };
}

/* --------------------------- 主入口 --------------------------- */

export function buildOption(payload, spec, columnMetaOf) {
  const vars = themeVars();
  const typeName = payload.type || (spec && spec.type) || 'bar';
  const metaOf = columnMetaOf || (() => null);

  const categoryTypes = ['bar', 'hbar', 'line', 'area', 'stacked_bar', 'stacked_area', 'percent_bar'];
  if (categoryTypes.includes(typeName)) return categoryOption(payload, spec, metaOf, vars, typeName);
  if (['pie', 'donut', 'rose'].includes(typeName)) return pieOption(payload, spec, metaOf, vars, typeName);
  if (typeName === 'treemap') return treemapOption(payload, metaOf, vars);
  if (typeName === 'funnel') return funnelOption(payload, metaOf, vars);
  if (['scatter', 'bubble'].includes(typeName)) return scatterOption(payload, spec, metaOf, vars, typeName);
  if (['histogram', 'density', 'ecdf'].includes(typeName)) return distributionOption(payload, spec, metaOf, vars, typeName);
  if (typeName === 'boxplot') return boxplotOption(payload, spec, metaOf, vars);
  if (typeName === 'violin') return violinOption(payload, spec, metaOf, vars);
  if (typeName === 'heatmap') return heatmapOption(payload, spec, metaOf, vars);
  if (typeName === 'radar') return radarOption(payload, metaOf, vars);
  if (typeName === 'parallel') return parallelOption(payload, metaOf, vars);
  if (typeName === 'scatter_matrix') return scatterMatrixOption(payload, metaOf, vars);
  return categoryOption(payload, spec, metaOf, vars, 'bar');
}

function axisName(columnMetaOf, name) {
  return name ? columnLabel(columnMetaOf(name), name) : '';
}

function categoryLabels(payload, metaOf, columnName) {
  const meta = metaOf(columnName);
  const labels = (payload.categories || []).map((value) => valueLabel(meta, value));
  return { labels, meta };
}

function hoverLabel(payload, metaOf, dataIndex, columnName) {
  const meta = metaOf(columnName);
  const raw = (payload.categories || [])[dataIndex];
  return valueLabel(meta, raw);
}

/* --------------------------- 类别轴系列 --------------------------- */

function categoryOption(payload, spec, metaOf, vars, typeName) {
  const horizontal = typeName === 'hbar';
  const isLine = ['line', 'area', 'stacked_area'].includes(typeName);
  const isArea = ['area', 'stacked_area'].includes(typeName);
  const stacked = payload.stacked || ['stacked_bar', 'stacked_area', 'percent_bar'].includes(typeName);
  const { labels } = categoryLabels(payload, metaOf, spec ? spec.x : null);
  const seriesMeta = spec && spec.series ? metaOf(spec.series) : null;

  let seriesList = payload.series || [];
  if (payload.percent) {
    const totals = labels.map((_, index) => seriesList.reduce((sum, s) => sum + (Number(s.data[index]) || 0), 0));
    seriesList = seriesList.map((s) => ({
      ...s,
      data: s.data.map((value, index) => {
        const total = totals[index];
        return !total ? 0 : Number(((Number(value) || 0) / total * 100).toFixed(2));
      }),
    }));
  }

  const dataZoom = labels.length > 28 ? [
    { type: 'inside', throttle: 60 },
    { type: 'slider', height: 16, bottom: 6, borderColor: vars.line, textStyle: { color: vars.dim, fontSize: 10 } },
  ] : [];

  const common = {
    color: vars.colors,
    grid: baseGrid({ bottom: dataZoom.length ? 78 : 62 }),
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: isLine ? 'line' : 'shadow' },
      ...vars.tooltip,
      valueFormatter: (value) => fmtNumber(value),
    },
    legend: {
      type: 'scroll',
      top: 4,
      textStyle: { color: vars.dim, fontSize: 11 },
      formatter: (name) => valueLabel(seriesMeta, name),
    },
    dataZoom,
    series: seriesList.map((entry) => ({
      name: entry.name,
      type: isLine ? 'line' : 'bar',
      smooth: Boolean(payload.smooth || (spec && spec.smooth)),
      symbolSize: 6,
      showSymbol: (payload.categories || []).length <= 40,
      stack: stacked ? 'total' : undefined,
      areaStyle: isArea ? { opacity: payload.percent ? 0.6 : 0.28 } : undefined,
      barMaxWidth: 34,
      label: {
        show: Boolean(spec && spec.labels) && !stacked,
        position: horizontal ? 'right' : 'top',
        color: vars.dim,
        fontSize: 10,
        formatter: (params) => fmtNumber(params.value),
      },
      emphasis: { focus: 'series' },
      data: entry.data,
    })),
  };

  if (horizontal) {
    common.xAxis = {
      type: 'value',
      ...axisStyle(vars, axisName(metaOf, payload.axis && payload.axis.y)),
      axisLabel: {
        color: vars.dim,
        fontSize: 11,
        formatter: (value) => fmtNumber(value, 1),
      },
    };
    common.yAxis = {
      type: 'category',
      data: labels,
      inverse: true,
      ...axisStyle(vars, axisName(metaOf, payload.axis && payload.axis.x)),
      axisLabel: { color: vars.dim, fontSize: 11, width: 130, overflow: 'truncate' },
    };
  } else {
    common.xAxis = {
      type: 'category',
      data: labels,
      ...axisStyle(vars, axisName(metaOf, payload.axis && payload.axis.x), labels.length > 12 ? 28 : 0),
    };
    const logY = Boolean(spec && spec.logY);
    common.yAxis = {
      type: logY ? 'log' : 'value',
      ...axisStyle(vars, axisName(metaOf, payload.axis && payload.axis.y)),
      axisLabel: { color: vars.dim, fontSize: 11, formatter: (value) => fmtNumber(value, 1) },
    };
  }

  common.tooltip.formatter = (params) => {
    const list = Array.isArray(params) ? params : [params];
    const head = list.length ? hoverLabel(payload, metaOf, list[0].dataIndex, spec ? spec.x : null) : '';
    const rows = list.map((item) => {
      const name = valueLabel(seriesMeta, item.seriesName);
      const value = payload.percent ? `${fmtNumber(item.value)}%` : fmtNumber(item.value);
      return `${item.marker}${name}：<b>${value}</b>`;
    });
    return `<div style="font-weight:600;margin-bottom:4px">${head}</div>${rows.join('<br>')}`;
  };
  return common;
}

/* ------------------------------ 饼 / 环 / 玫瑰 ------------------------------ */

function pieOption(payload, spec, metaOf, vars, typeName) {
  const { labels, meta } = categoryLabels(payload, metaOf, spec ? spec.x : null);
  const values = ((payload.series && payload.series[0] && payload.series[0].data) || []).map((v) => Number(v) || 0);
  const data = labels.map((name, index) => ({ name, value: values[index] }));
  return {
    color: vars.colors,
    tooltip: {
      trigger: 'item',
      ...vars.tooltip,
      formatter: (params) => `${params.marker}<b>${params.name}</b><br>${fmtNumber(params.value)}（${params.percent}%）`,
    },
    legend: {
      type: 'scroll',
      orient: 'vertical',
      right: 8,
      top: 20,
      textStyle: { color: vars.dim, fontSize: 11 },
    },
    series: [{
      type: 'pie',
      roseType: typeName === 'rose' ? 'radius' : undefined,
      radius: typeName === 'donut' ? ['42%', '68%'] : (typeName === 'rose' ? ['18%', '70%'] : '66%'),
      center: ['38%', '54%'],
      data: data.sort((a, b) => b.value - a.value),
      label: {
        color: vars.dim,
        fontSize: 11,
        formatter: (params) => `${params.name}\n${fmtNumber(params.value)}`,
      },
      labelLine: { lineStyle: { color: vars.line } },
      itemStyle: { borderColor: vars.panel, borderWidth: 1.5 },
      emphasis: { scale: true, scaleSize: 6, itemStyle: { shadowBlur: 18, shadowColor: 'rgba(79,140,255,.45)' } },
    }],
  };
}

function treemapOption(payload, metaOf, vars) {
  const { labels } = categoryLabels(payload, metaOf, payload.axis && payload.axis.x);
  const values = ((payload.series && payload.series[0] && payload.series[0].data) || []).map((v) => Number(v) || 0);
  return {
    color: vars.colors,
    tooltip: {
      ...vars.tooltip,
      formatter: (params) => `${params.name}<br><b>${fmtNumber(params.value)}</b>`,
    },
    series: [{
      type: 'treemap',
      roam: false,
      nodeClick: false,
      breadcrumb: { show: false },
      label: { color: '#fff', fontSize: 11, formatter: (params) => `${params.name}\n${fmtNumber(params.value)}` },
      itemStyle: { borderColor: vars.panel, borderWidth: 2, gapWidth: 2 },
      data: labels.map((name, index) => ({ name, value: values[index] })),
    }],
  };
}

function funnelOption(payload, metaOf, vars) {
  const { labels } = categoryLabels(payload, metaOf, payload.axis && payload.axis.x);
  const values = ((payload.series && payload.series[0] && payload.series[0].data) || []).map((v) => Number(v) || 0);
  const data = labels.map((name, index) => ({ name, value: values[index] }))
    .sort((a, b) => b.value - a.value);
  return {
    color: vars.colors,
    tooltip: { ...vars.tooltip, trigger: 'item', formatter: (params) => `${params.name}<br><b>${fmtNumber(params.value)}</b>` },
    series: [{
      type: 'funnel',
      left: '12%',
      right: '12%',
      top: 26,
      bottom: 20,
      minSize: '18%',
      sort: 'descending',
      gap: 3,
      label: { color: vars.text, fontSize: 11, position: 'inside', formatter: (params) => `${params.name}: ${fmtNumber(params.value)}` },
      itemStyle: { borderColor: vars.panel, borderWidth: 1 },
      data,
    }],
  };
}

/* ------------------------------ 散点 / 气泡 ------------------------------ */

function scatterOption(payload, spec, metaOf, vars, typeName) {
  const xName = spec ? spec.x : null;
  const yName = spec ? spec.y : null;
  const sizeName = spec ? spec.size : null;
  const colorName = spec ? spec.series : null;
  const seriesMeta = metaOf(colorName);
  const allValues = [];
  (payload.series || []).forEach((s) => s.data.forEach((p) => { allValues.push(Number(p[2]) || 0); }));
  const maxSize = Math.max(1, ...allValues);
  const bubble = typeName === 'bubble' && sizeName;

  const series = (payload.series || []).map((entry) => ({
    name: entry.name,
    type: 'scatter',
    symbolSize: bubble
      ? (value) => 8 + 44 * Math.sqrt(Math.max(0, Number(value[2]) || 0) / maxSize)
      : 9,
    itemStyle: { opacity: 0.78 },
    emphasis: { focus: 'series', itemStyle: { opacity: 1 } },
    data: entry.data,
  }));

  if (payload.trend) {
    series.push({
      name: t('chart.fit'),
      type: 'line',
      showSymbol: false,
      silent: true,
      lineStyle: { type: 'dashed', width: 2, color: vars.colors[4] },
      itemStyle: { color: vars.colors[4] },
      data: payload.trend,
    });
  }

  return {
    color: vars.colors,
    grid: baseGrid({ right: 34, bottom: 66 }),
    tooltip: {
      ...vars.tooltip,
      formatter: (params) => {
        const point = params.value || [];
        const rows = [
          `${columnLabel(metaOf(xName), xName)}：<b>${fmtNumber(point[0])}</b>`,
          `${columnLabel(metaOf(yName), yName)}：<b>${fmtNumber(point[1])}</b>`,
        ];
        if (bubble && point.length > 2) rows.push(`${columnLabel(metaOf(sizeName), sizeName)}：<b>${fmtNumber(point[2])}</b>`);
        return `<div style="font-weight:600;margin-bottom:4px">${params.marker}${valueLabel(seriesMeta, params.seriesName)}</div>${rows.join('<br>')}`;
      },
    },
    legend: { top: 4, textStyle: { color: vars.dim, fontSize: 11 } },
    xAxis: {
      type: 'value',
      ...axisStyle(vars, columnLabel(metaOf(xName), xName)),
      axisLabel: { color: vars.dim, fontSize: 11, formatter: (value) => fmtNumber(value, 1) },
    },
    yAxis: {
      type: 'value',
      ...axisStyle(vars, columnLabel(metaOf(yName), yName)),
      axisLabel: { color: vars.dim, fontSize: 11, formatter: (value) => fmtNumber(value, 1) },
    },
    series,
  };
}

/* ------------------------------ 分布类 ------------------------------ */

function distributionOption(payload, spec, metaOf, vars, typeName) {
  const column = (spec && (spec.y || spec.x)) || (payload.axis && payload.axis.x);
  const name = columnLabel(metaOf(column), column);
  const seriesMeta = spec && spec.series ? metaOf(spec.series) : null;

  if (typeName === 'histogram') {
    return {
      color: vars.colors,
      grid: baseGrid({ bottom: 72 }),
      tooltip: { ...vars.tooltip, trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { top: 4, textStyle: { color: vars.dim, fontSize: 11 }, formatter: (n) => valueLabel(seriesMeta, n) },
      xAxis: { type: 'category', data: payload.categories || [], ...axisStyle(vars, name, 32) },
      yAxis: { type: 'value', ...axisStyle(vars, 'count') },
      series: (payload.series || []).map((entry) => ({
        name: entry.name,
        type: 'bar',
        stack: (payload.series || []).length > 1 ? 'hist' : undefined,
        barCategoryGap: '2%',
        data: entry.data,
      })),
    };
  }

  const isEcdf = typeName === 'ecdf';
  return {
    color: vars.colors,
    grid: baseGrid(),
    tooltip: {
      ...vars.tooltip,
      trigger: 'axis',
      formatter: (params) => {
        const list = Array.isArray(params) ? params : [params];
        const rows = list.map((item) => `${item.marker}${valueLabel(seriesMeta, item.seriesName)}：<b>${fmtNumber(item.value[0])}</b> → ${isEcdf ? fmtRate(item.value[1]) : fmtNumber(item.value[1], 4)}`);
        return `${columnLabel(metaOf(column), column)}<br>${rows.join('<br>')}`;
      },
    },
    legend: { top: 4, textStyle: { color: vars.dim, fontSize: 11 }, formatter: (n) => valueLabel(seriesMeta, n) },
    xAxis: {
      type: 'value',
      ...axisStyle(vars, name),
      axisLabel: { color: vars.dim, fontSize: 11, formatter: (value) => fmtNumber(value, 1) },
    },
    yAxis: {
      type: 'value',
      ...axisStyle(vars, isEcdf ? 'P(X ≤ x)' : 'density'),
      axisLabel: { color: vars.dim, fontSize: 11, formatter: (value) => (isEcdf ? `${(value * 100).toFixed(0)}%` : value.toFixed(2)) },
    },
    series: (payload.series || []).map((entry) => ({
      name: entry.name,
      type: 'line',
      smooth: typeName === 'density',
      step: isEcdf ? 'end' : undefined,
      showSymbol: false,
      lineStyle: { width: 2 },
      areaStyle: typeName === 'density' ? { opacity: 0.16 } : undefined,
      data: entry.data,
    })),
  };
}

/* ------------------------------ 箱线 / 小提琴 ------------------------------ */

function boxplotOption(payload, spec, metaOf, vars) {
  const { labels } = categoryLabels(payload, metaOf, spec ? spec.x : null);
  const yName = spec ? spec.y : null;
  const outlierData = [];
  (payload.outliers || []).forEach((values, index) => {
    values.forEach((value) => outlierData.push([index, value]));
  });
  return {
    color: vars.colors,
    grid: baseGrid({ bottom: 72 }),
    tooltip: {
      ...vars.tooltip,
      trigger: 'item',
      formatter: (params) => {
        if (params.seriesType === 'boxplot') {
          const [low, q1, median, q3, high] = params.value.slice(1);
          return `<b>${params.name}</b><br>Q1：${fmtNumber(q1)}<br>中位数：${fmtNumber(median)}<br>Q3：${fmtNumber(q3)}<br>范围：${fmtNumber(low)} ~ ${fmtNumber(high)}`;
        }
        return `${columnLabel(metaOf(yName), yName)}：<b>${fmtNumber(params.value[1])}</b>`;
      },
    },
    xAxis: { type: 'category', data: labels, ...axisStyle(vars, spec ? spec.x : '', labels.length > 10 ? 28 : 0) },
    yAxis: {
      type: 'value',
      ...axisStyle(vars, columnLabel(metaOf(yName), yName)),
      axisLabel: { color: vars.dim, fontSize: 11, formatter: (value) => fmtNumber(value, 1) },
    },
    series: [
      {
        name: columnLabel(metaOf(yName), yName),
        type: 'boxplot',
        boxWidth: ['22%', '46%'],
        itemStyle: { borderWidth: 1.6 },
        data: (payload.boxes || []).map((box, index) => [index].concat(box)),
        markPoint: {
          symbolSize: 0,
          label: { show: true, color: vars.dim, fontSize: 10, formatter: (params) => fmtNumber(params.value, 1) },
          data: (payload.means || []).map((mean, index) => ({ coord: [index, mean], value: mean })),
        },
      },
      {
        name: t('chart.dataTitle'),
        type: 'scatter',
        symbolSize: 5,
        itemStyle: { color: vars.colors[5], opacity: 0.6 },
        data: outlierData,
      },
    ],
  };
}

function violinOption(payload, spec, metaOf, vars) {
  const xName = spec ? spec.x : null;
  const yName = spec ? spec.y : null;
  const { labels } = categoryLabels(payload, metaOf, xName);
  const series = (payload.violins || []).map((violin, index) => ({
    name: violin.name,
    type: 'line',
    smooth: true,
    showSymbol: false,
    lineStyle: { width: 1.4, opacity: 0.9 },
    areaStyle: { opacity: 0.14 },
    data: violin.points,
    color: vars.colors[index % vars.colors.length],
  }));
  series.push({
    name: t('stats.median'),
    type: 'scatter',
    symbolSize: 5,
    itemStyle: { color: vars.colors[4] },
    data: (payload.medians || []).filter((point) => point[0] !== null),
  });
  return {
    color: vars.colors,
    grid: baseGrid({ bottom: 72 }),
    tooltip: {
      ...vars.tooltip,
      formatter: (params) => `${params.marker}${params.seriesName}<br>${columnLabel(metaOf(yName), yName)}：<b>${fmtNumber(params.value[0])}</b><br>${columnLabel(metaOf(xName), xName)}：<b>${params.value[1]}</b>`,
    },
    legend: { top: 4, textStyle: { color: vars.dim, fontSize: 11 } },
    xAxis: {
      type: 'value',
      ...axisStyle(vars, columnLabel(metaOf(yName), yName)),
      axisLabel: { color: vars.dim, fontSize: 11, formatter: (value) => fmtNumber(value, 1) },
    },
    yAxis: {
      type: 'value',
      ...axisStyle(vars, columnLabel(metaOf(xName), xName)),
      min: -0.5,
      max: labels.length - 0.5,
      axisLabel: {
        color: vars.dim, fontSize: 11,
        formatter: (value) => (Number.isInteger(value) && labels[value] !== undefined ? labels[value] : ''),
      },
    },
    series,
  };
}

/* ------------------------------ 热力矩阵 ------------------------------ */

function heatmapOption(payload, spec, metaOf, vars) {
  const rowLabels = payload.row_labels || [];
  const colLabels = payload.categories || [];
  const values = (payload.cells || []).map((cell) => Number(cell[2]));
  const finite = values.filter((v) => Number.isFinite(v));
  const min = finite.length ? Math.min(...finite) : 0;
  const max = finite.length ? Math.max(...finite) : 1;
  const isRate = (spec && spec.normalize && spec.normalize !== 'none');
  return {
    grid: {
      left: 70, right: 76, top: 30, bottom: 96, containLabel: true,
    },
    tooltip: {
      ...vars.tooltip,
      formatter: (params) => {
        const [x, y, value] = params.value;
        return `${columnLabel(metaOf(spec && spec.y), spec && spec.y)}：<b>${valueLabel(metaOf(spec && spec.y), y === null ? null : rowLabels[y])}</b><br>` +
          `${columnLabel(metaOf(spec && spec.x), spec && spec.x)}：<b>${valueLabel(metaOf(spec && spec.x), colLabels[x])}</b><br>` +
          `${columnLabel(metaOf(spec && spec.values), spec && spec.values)}：<b>${isRate ? fmtRate(value) : fmtNumber(value)}</b>`;
      },
    },
    xAxis: {
      type: 'category',
      data: colLabels.map((value) => valueLabel(metaOf(spec && spec.x), value)),
      splitArea: { show: true, areaStyle: { color: ['transparent'] } },
      axisLabel: { color: vars.dim, fontSize: 11, rotate: colLabels.length > 8 ? 34 : 0, hideOverlap: true },
      axisLine: { lineStyle: { color: vars.line } },
    },
    yAxis: {
      type: 'category',
      data: rowLabels.map((value) => valueLabel(metaOf(spec && spec.y), value)),
      splitArea: { show: true, areaStyle: { color: ['transparent'] } },
      axisLabel: { color: vars.dim, fontSize: 11, width: 110, overflow: 'truncate' },
      axisLine: { lineStyle: { color: vars.line } },
    },
    visualMap: {
      min, max,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 6,
      itemWidth: 12,
      itemHeight: 92,
      textStyle: { color: vars.dim, fontSize: 10 },
      inRange: { color: ['#1e3a8a', '#2563eb', '#22d3ee', '#fbbf24', '#f87171'] },
      formatter: (value) => (isRate ? fmtRate(value) : fmtNumber(value, 0)),
    },
    series: [{
      type: 'heatmap',
      data: (payload.cells || []).map((cell) => {
        const value = Number(cell[2]);
        const ratio = max === min ? 0.5 : (value - min) / (max - min);
        const darkText = ratio > 0.28 && ratio < 0.78;
        return { value: cell, label: { color: darkText ? '#16213b' : '#ffffff' } };
      }),
      label: {
        show: (payload.cells || []).length <= 140,
        fontSize: 9,
        formatter: (params) => (isRate ? `${(params.value[2] * 100).toFixed(0)}%` : fmtNumber(params.value[2], 1)),
      },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,.4)' } },
    }],
  };
}

/* ------------------------------ 雷达 / 平行坐标 ------------------------------ */

function radarOption(payload, metaOf, vars) {
  const dims = payload.categories || [];
  const indicator = dims.map((dim) => {
    const values = (payload.series || []).flatMap((s) => s.data.map((v) => Number(v) || 0));
    const max = Math.max(1, ...values);
    return { name: columnLabel(metaOf(dim), dim), max: Number((max * 1.08).toFixed(4)) };
  });
  return {
    color: vars.colors,
    tooltip: { ...vars.tooltip },
    legend: { top: 4, textStyle: { color: vars.dim, fontSize: 11 } },
    radar: {
      indicator,
      radius: '62%',
      center: ['50%', '56%'],
      splitLine: { lineStyle: { color: vars.grid } },
      splitArea: { areaStyle: { color: ['transparent'] } },
      axisLine: { lineStyle: { color: vars.grid } },
      axisName: { color: vars.dim, fontSize: 11 },
    },
    series: [{
      type: 'radar',
      symbolSize: 4,
      areaStyle: { opacity: 0.16 },
      data: (payload.series || []).map((entry) => ({ name: entry.name, value: entry.data })),
    }],
  };
}

function parallelOption(payload, metaOf, vars) {
  const dims = payload.dims || [];
  const seriesMeta = metaOf(payload.axis && payload.axis.series);
  const groupNames = (payload.series || []).map((s) => s.name);
  const data = [];
  (payload.series || []).forEach((entry, groupIndex) => {
    entry.data.forEach((row) => data.push({ value: row, group: groupIndex }));
  });
  return {
    color: vars.colors,
    tooltip: {
      ...vars.tooltip,
      formatter: (params) => {
        const values = params.value || params.data.value || [];
        const rows = dims.map((dim, index) => `${columnLabel(metaOf(dim.name), dim.name)}：<b>${fmtNumber(values[index])}</b>`);
        return `${params.marker}${valueLabel(seriesMeta, groupNames[params.data.group])}<br>${rows.join('<br>')}`;
      },
    },
    legend: {
      top: 4,
      textStyle: { color: vars.dim, fontSize: 11 },
      data: groupNames.map((name) => valueLabel(seriesMeta, name)),
      formatter: (name) => name,
    },
    parallelAxis: dims.map((dim, index) => ({
      dim: index,
      name: columnLabel(metaOf(dim.name), dim.name),
      min: dim.min,
      max: dim.max,
      nameTextStyle: { color: vars.dim, fontSize: 10 },
      axisLabel: { color: vars.dim, fontSize: 10, formatter: (value) => fmtNumber(value, 1) },
      axisLine: { lineStyle: { color: vars.line } },
    })),
    parallel: {
      left: 56,
      right: 40,
      top: 52,
      bottom: 34,
      parallelAxisDefault: { type: 'value' },
    },
    series: groupNames.map((name, groupIndex) => ({
      name: valueLabel(seriesMeta, name),
      type: 'parallel',
      smooth: true,
      lineStyle: { width: 1.1, opacity: 0.55 },
      emphasis: { lineStyle: { width: 2.6, opacity: 1 } },
      data: data.filter((row) => row.group === groupIndex).map((row) => row.value),
    })),
  };
}

/* ------------------------------ 散点矩阵 ------------------------------ */

function scatterMatrixOption(payload, metaOf, vars) {
  const dims = payload.dims || [];
  const n = dims.length;
  const cells = payload.cells || [];
  const seriesMeta = metaOf(payload.axis && payload.axis.color);
  const gap = 6;
  const size = 100 / n;
  const grid = [];
  const xAxis = [];
  const yAxis = [];
  const series = [];
  const colors = vars.colors;

  for (let row = 0; row < n; row += 1) {
    for (let col = 0; col < n; col += 1) {
      const index = row * n + col;
      grid.push({
        left: `${size * col + 4}%`,
        top: `${size * row + 6}%`,
        width: `${size - 6}%`,
        height: `${size - 7}%`,
        containLabel: false,
      });
      xAxis.push({
        gridIndex: index,
        type: 'value',
        axisLabel: { show: row === n - 1, color: vars.dim, fontSize: 9, formatter: (v) => fmtNumber(v, 0) },
        axisLine: { lineStyle: { color: vars.line } },
        splitLine: { lineStyle: { color: vars.grid } },
        axisTick: { show: false },
      });
      yAxis.push({
        gridIndex: index,
        type: 'value',
        axisLabel: { show: col === 0, color: vars.dim, fontSize: 9, formatter: (v) => fmtNumber(v, 0) },
        axisLine: { lineStyle: { color: vars.line } },
        splitLine: { lineStyle: { color: vars.grid } },
        axisTick: { show: false },
      });
    }
  }

  cells.forEach((cell) => {
    const index = cell.y * n + cell.x;
    (cell.series || []).forEach((entry, groupIndex) => {
      series.push({
        name: `${entry.name}`,
        type: 'scatter',
        xAxisIndex: index,
        yAxisIndex: index,
        symbolSize: 4,
        itemStyle: { opacity: 0.6, color: colors[groupIndex % colors.length] },
        data: entry.data,
        silent: true,
      });
    });
  });

  return {
    color: colors,
    title: dims.map((dim, index) => ({
      text: columnLabel(metaOf(dim), dim),
      left: `${size * index + size / 2 - 4}%`,
      top: 0,
      textAlign: 'center',
      textStyle: { color: vars.dim, fontSize: 10, fontWeight: 'normal' },
    })),
    tooltip: {
      ...vars.tooltip,
      formatter: (params) => {
        const [x, y] = params.value || [];
        return `${params.marker}${valueLabel(seriesMeta, params.seriesName)}<br>X：<b>${fmtNumber(x)}</b><br>Y：<b>${fmtNumber(y)}</b>`;
      },
    },
    legend: { top: 0, right: 8, textStyle: { color: vars.dim, fontSize: 10 }, formatter: (n2) => valueLabel(seriesMeta, n2) },
    grid,
    xAxis,
    yAxis,
    series,
  };
}

/* --------------------------- 画像 / 洞察 小图 --------------------------- */

export function qualityGaugeOption(score, grade) {
  const vars = themeVars();
  const color = score >= 90 ? '#34d399' : score >= 75 ? '#4f8cff' : score >= 55 ? '#fbbf24' : '#f87171';
  return {
    series: [{
      type: 'gauge',
      startAngle: 210,
      endAngle: -30,
      min: 0,
      max: 100,
      radius: '96%',
      center: ['50%', '60%'],
      progress: { show: true, width: 12, roundCap: true, itemStyle: { color } },
      pointer: { show: false },
      axisLine: { lineStyle: { width: 12, color: [[1, vars.grid]] } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: { show: false },
      anchor: { show: false },
      title: { show: false },
      detail: {
        valueAnimation: true,
        offsetCenter: [0, '-8%'],
        fontSize: 30,
        fontWeight: 700,
        color,
        formatter: (value) => `${Math.round(value)}`,
      },
      data: [{ value: score, name: localize(grade, t('profile.scoreLabel')) }],
    }],
  };
}

export function missingBarOption(missingBar, metaOf) {
  const vars = themeVars();
  const items = (missingBar || []).filter((item) => item.rate > 0).slice(0, 14).reverse();
  const maxRate = items.length ? Math.max(...items.map((item) => item.rate)) : 0.1;
  const axisMax = Math.min(1, Math.max(0.05, maxRate * 1.35));
  return {
    grid: baseGrid({ left: 92, right: 52, top: 14, bottom: 22 }),
    tooltip: {
      ...vars.tooltip,
      formatter: (params) => `${params.name}<br>缺失 <b>${items[params.dataIndex].missing}</b> 行（${fmtRate(items[params.dataIndex].rate)}）`,
    },
    xAxis: {
      type: 'value',
      max: axisMax,
      axisLabel: { color: vars.dim, fontSize: 10, formatter: (v) => `${(v * 100).toFixed(0)}%` },
      splitLine: { lineStyle: { color: vars.grid } },
    },
    yAxis: {
      type: 'category',
      data: items.map((item) => columnLabel(metaOf(item.name), item.name)),
      axisLabel: { color: vars.dim, fontSize: 10, width: 86, overflow: 'truncate' },
      axisLine: { lineStyle: { color: vars.line } },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 14,
      itemStyle: {
        borderRadius: [0, 6, 6, 0],
        color: (params) => (params.value > 0.15 ? '#f87171' : params.value > 0.05 ? '#fbbf24' : '#4f8cff'),
      },
      label: { show: true, position: 'right', color: vars.dim, fontSize: 10, formatter: (params) => fmtRate(params.value) },
      data: items.map((item) => item.rate),
    }],
  };
}

export function missingMatrixOption(matrix, metaOf) {
  const vars = themeVars();
  const columns = (matrix && matrix.columns) || [];
  const rows = (matrix && matrix.rows) || 0;
  return {
    grid: { left: 56, right: 26, top: 42, bottom: 76, containLabel: true },
    tooltip: {
      ...vars.tooltip,
      formatter: (params) => {
        const [x, y] = params.value;
        return `${columnLabel(metaOf(columns[x]), columns[x])}<br>采样行 #${y}`;
      },
    },
    xAxis: {
      type: 'category',
      data: columns.map((name) => columnLabel(metaOf(name), name)),
      axisLabel: { color: vars.dim, fontSize: 9, rotate: 42, hideOverlap: true },
      axisLine: { lineStyle: { color: vars.line } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      data: Array.from({ length: rows }, (_, index) => String(index)),
      axisLabel: { show: false },
      axisLine: { lineStyle: { color: vars.line } },
      axisTick: { show: false },
    },
    visualMap: {
      show: false,
      type: 'piecewise',
      pieces: [{ value: 0, color: 'rgba(79,140,255,.08)' }, { value: 1, color: '#f87171' }],
    },
    series: [{
      type: 'heatmap',
      data: (matrix && matrix.points || []).map((point) => [point[0], point[1], 1]),
      progressive: 4000,
      itemStyle: { borderWidth: 0 },
    }],
  };
}

export function sparkHistogramOption(hist, color) {
  const vars = themeVars();
  const counts = (hist && hist.counts) || [];
  const labels = (hist && hist.labels) || [];
  return {
    grid: { left: 6, right: 6, top: 6, bottom: 16 },
    tooltip: {
      ...vars.tooltip,
      formatter: (params) => `区间 ${labels[params.dataIndex]}<br>计数 <b>${params.value}</b>`,
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { show: false },
      axisLine: { lineStyle: { color: vars.line } },
      axisTick: { show: false },
    },
    yAxis: { type: 'value', show: false },
    series: [{
      type: 'bar',
      data: counts,
      barCategoryGap: '8%',
      itemStyle: { color: color || vars.colors[0], borderRadius: [2, 2, 0, 0] },
    }],
  };
}

export function funnelStepsOption(steps, initialRows) {
  const vars = themeVars();
  const rows = [{ name: t('table.source'), value: initialRows }].concat(
    (steps || []).map((step, index) => ({
      name: `${index + 1}. ${localize(step.label, step.id)}`,
      value: step.rows,
    })),
  );
  const max = Math.max(1, ...rows.map((row) => row.value));
  return {
    grid: baseGrid({ left: 8, right: 58, top: 8, bottom: 8 }),
    tooltip: {
      ...vars.tooltip,
      formatter: (params) => `${params.name}<br><b>${params.value.toLocaleString()}</b> ${t('common.rows')}`,
    },
    xAxis: {
      type: 'value',
      max,
      show: false,
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows.map((row) => row.name),
      axisLabel: { color: vars.dim, fontSize: 10, width: 96, overflow: 'truncate' },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 13,
      itemStyle: {
        borderRadius: [0, 6, 6, 0],
        color: (params) => {
          const ratio = params.value / max;
          if (ratio > 0.85) return '#4f8cff';
          if (ratio > 0.55) return '#22d3ee';
          if (ratio > 0.25) return '#fbbf24';
          return '#f87171';
        },
      },
      label: {
        show: true,
        position: 'right',
        color: vars.dim,
        fontSize: 10,
        fontFamily: 'monospace',
        formatter: (params) => params.value.toLocaleString(),
      },
      data: rows.map((row) => row.value),
    }],
  };
}

export function correlationHeatmapOption(corr, metaOf, onCellClick) {
  const vars = themeVars();
  const labels = corr.labels || [];
  const labelsZh = (corr.labels_i18n || []).map((item) => localize(item));
  const option = {
    grid: { left: 108, right: 30, top: 28, bottom: 92, containLabel: true },
    tooltip: {
      ...vars.tooltip,
      formatter: (params) => {
        const [x, y, value] = params.value;
        return `${labelsZh[y]} ↔ ${labelsZh[x]}<br>${corr.method} <b>${value === null ? '—' : Number(value).toFixed(3)}</b>`;
      },
    },
    xAxis: {
      type: 'category',
      data: labelsZh,
      axisLabel: { color: vars.dim, fontSize: 10, rotate: 40, hideOverlap: true },
      axisLine: { lineStyle: { color: vars.line } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      data: labelsZh,
      axisLabel: { color: vars.dim, fontSize: 10, width: 100, overflow: 'truncate' },
      axisLine: { lineStyle: { color: vars.line } },
      axisTick: { show: false },
    },
    visualMap: {
      min: -1,
      max: 1,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 6,
      itemWidth: 12,
      itemHeight: 110,
      textStyle: { color: vars.dim, fontSize: 10 },
      inRange: { color: ['#2563eb', '#60a5fa', '#e2e8f7', '#fbbf24', '#dc2626'] },
      formatter: (value) => Number(value).toFixed(1),
    },
    series: [{
      type: 'heatmap',
      data: (corr.matrix || []).map((cell) => ({
        value: cell,
        label: { color: cell[2] === null ? 'transparent' : (Math.abs(Number(cell[2])) > 0.5 ? '#ffffff' : '#16213b') },
      })),
      label: {
        show: labels.length <= 10,
        fontSize: 9,
        formatter: (params) => (params.value[2] === null ? '' : Number(params.value[2]).toFixed(2)),
      },
      emphasis: { itemStyle: { borderColor: vars.text, borderWidth: 1 } },
    }],
  };
  return option;
}

export function trendLineOption(tsPayload, metaOf) {
  const vars = themeVars();
  const categories = tsPayload.categories || [];
  const groupMeta = metaOf(tsPayload.series && tsPayload.series[0] && tsPayload.series[0].__group);
  const series = [];
  (tsPayload.series || []).forEach((entry, index) => {
    series.push({
      name: entry.name,
      type: 'line',
      smooth: true,
      showSymbol: categories.length <= 60,
      symbolSize: 5,
      lineStyle: { width: 1.8 },
      data: entry.data,
    });
    if (entry.rolling) {
      series.push({
        name: `${entry.name} · ${t('ts.rolling')} ${entry.rollingWindow}`,
        type: 'line',
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.6, type: 'dashed', opacity: 0.9 },
        data: entry.rolling,
      });
    }
  });
  if (tsPayload.trend && tsPayload.trend.points) {
    series.push({
      name: t('ts.trend'),
      type: 'line',
      showSymbol: false,
      silent: true,
      lineStyle: { type: 'dotted', width: 2.4, color: vars.colors[4] },
      itemStyle: { color: vars.colors[4] },
      data: tsPayload.trend.points.map((point) => point[1] === null ? null : [point[0], point[1]]),
    });
  }
  return {
    color: vars.colors,
    grid: baseGrid({ bottom: 78 }),
    tooltip: {
      ...vars.tooltip,
      trigger: 'axis',
      valueFormatter: (value) => fmtNumber(value),
    },
    legend: { top: 4, type: 'scroll', textStyle: { color: vars.dim, fontSize: 11 } },
    dataZoom: [
      { type: 'inside', throttle: 60 },
      { type: 'slider', height: 16, bottom: 8, borderColor: vars.line, textStyle: { color: vars.dim, fontSize: 10 } },
    ],
    xAxis: {
      type: 'category',
      data: categories,
      ...axisStyle(vars, columnLabel(metaOf(tsPayload.__date), tsPayload.__date), categories.length > 20 ? 30 : 0),
    },
    yAxis: {
      type: 'value',
      ...axisStyle(vars, columnLabel(metaOf(tsPayload.__value), tsPayload.__value)),
      axisLabel: { color: vars.dim, fontSize: 11, formatter: (value) => fmtNumber(value, 1) },
    },
    series,
  };
}

export function densityCompareOption(chart, metaOf) {
  const vars = themeVars();
  return {
    color: vars.colors,
    grid: baseGrid({ bottom: 46 }),
    tooltip: {
      ...vars.tooltip,
      formatter: (params) => `${params.marker}${params.seriesName}<br>数值：<b>${fmtNumber(params.value[0])}</b><br>密度：${fmtNumber(params.value[1], 4)}`,
    },
    legend: { top: 4, textStyle: { color: vars.dim, fontSize: 11 } },
    xAxis: {
      type: 'value',
      axisLabel: { color: vars.dim, fontSize: 11, formatter: (value) => fmtNumber(value, 1) },
      splitLine: { lineStyle: { color: vars.grid } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { show: false },
      splitLine: { lineStyle: { color: vars.grid } },
    },
    series: (chart && chart.series || []).map((entry) => ({
      name: entry.name,
      type: 'line',
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 2 },
      areaStyle: { opacity: 0.18 },
      data: entry.data,
    })),
  };
}

export function chartPng(chart, name) {
  if (!chart) return;
  const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: themeVars().panel });
  const link = document.createElement('a');
  link.href = url;
  link.download = `${name || 'pandaviz-chart'}.png`;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export function attachClickHandler(chart, payload, handler) {
  if (!chart) return;
  chart.off('click');
  if (!handler) return;
  chart.on('click', (params) => {
    const dataIndex = params.dataIndex;
    const raw = payload && payload.categories && payload.categories[dataIndex] !== undefined
      ? payload.categories[dataIndex]
      : params.name;
    handler({ params, payload, raw, dataIndex, seriesIndex: params.seriesIndex });
  });
}
