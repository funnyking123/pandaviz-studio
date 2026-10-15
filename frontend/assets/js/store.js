/* ==========================================================================
   全局状态 + 极简事件总线
   ========================================================================== */

const bus = new Map();

export function on(event, handler) {
  if (!bus.has(event)) bus.set(event, new Set());
  bus.get(event).add(handler);
  return () => bus.get(event).delete(handler);
}

export function emit(event, payload) {
  const handlers = bus.get(event);
  if (!handlers) return;
  handlers.forEach((handler) => {
    try {
      handler(payload);
    } catch (err) {
      console.error(`[PandasViz] handler error on "${event}"`, err);
    }
  });
}

export const state = {
  meta: null,
  datasets: [],
  datasetId: null,
  dataset: null,
  steps: [],
  pipeline: null,
  outputs: {},
  activeTab: 'chart',
  loading: 0,
  error: null,
  latency: null,
  chart: {
    type: 'bar',
    x: null,
    y: null,
    series: null,
    size: null,
    dims: [],
    agg: 'sum',
    topN: 12,
    sort: 'desc',
    stacked: false,
    percent: false,
    smooth: false,
    fit: true,
    labels: false,
    logY: false,
    bins: 30,
    values: null,
    normalize: 'none',
  },
  table: { offset: 0, limit: 50, sort_by: null, sort_dir: 'asc', search: '' },
  corr: { method: 'pearson' },
  relationView: 'corr',
  pivot: { index: null, columns: null, values: null, agg: 'sum', normalize: 'none' },
  timeseries: { date: null, value: null, freq: 'M', agg: 'sum', group: null, rolling: 0 },
  stats: { test: 'anova', value: null, group: null },
  modal: null,
};

export function stepsKey(datasetId) {
  return `pandaviz.steps.${datasetId}`;
}

export function loadSteps(datasetId) {
  try {
    const raw = localStorage.getItem(stepsKey(datasetId));
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    return [];
  }
}

export function saveSteps(datasetId, steps) {
  try {
    localStorage.setItem(stepsKey(datasetId), JSON.stringify(steps || []));
  } catch (err) { /* 隐私模式下忽略 */ }
}

export function columnsOf(dataset) {
  return (dataset && dataset.columns) || [];
}

export function columnMeta(name) {
  if (!state.dataset || !name) return null;
  return (state.dataset.columns || []).find((col) => col.name === name) || null;
}

export function columnsByKind(...kinds) {
  return columnsOf(state.dataset).filter((col) => kinds.length === 0 || kinds.includes(col.kind));
}

export function numericColumns() {
  return columnsByKind('numeric').map((col) => col.name);
}

export function categoricalColumns() {
  return columnsByKind('categorical', 'boolean').map((col) => col.name);
}

export function datetimeColumns() {
  return columnsByKind('datetime').map((col) => col.name);
}

/** 数值列里挑一个“更值得看”的指标列（避开订单号等标识列，金额类优先） */
const METRIC_HINT = /(销售额|金额|总额|收入|营收|利润|revenue|sales|amount|profit|turnover|price|rating|score|aqi|gdp|population|ratio|value)/i;
const COUNT_HINT = /(数量|个数|次数|件数|qty|quantity|count)/i;
const ID_HINT = /(id|编号|序号|号码|code|订单号)$/i;

export function preferMetric(names) {
  return names.find((name) => METRIC_HINT.test(name) && !ID_HINT.test(name))
    || names.find((name) => !ID_HINT.test(name) && !COUNT_HINT.test(name))
    || names.find((name) => !ID_HINT.test(name))
    || names[0]
    || null;
}

/** 图表 / 透视 / 时序等编码通道的“安全默认值” */
export function defaultEncodings() {
  const numeric = numericColumns();
  const categorical = categoricalColumns();
  const datetimes = datetimeColumns();
  const metric = preferMetric(numeric);
  const second = numeric.filter((name) => name !== metric)[0] || metric;
  return {
    chart: {
      x: categorical[0] || numeric[0] || null,
      y: metric,
      series: null,
      size: second,
      values: metric,
      dims: numeric.slice(0, 4),
    },
    pivot: {
      index: categorical[0] || null,
      columns: categorical[1] || null,
      values: metric,
    },
    timeseries: {
      date: datetimes[0] || null,
      value: metric,
      group: categorical[0] || null,
    },
    stats: {
      value: metric,
      group: categorical[0] || null,
    },
  };
}
