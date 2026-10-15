/* ==========================================================================
   视图层：9 个标签页的控件与渲染（图表 / 表格 / 画像 / 关系 / 透视 / 时序 / 统计 / 洞察 / 代码）
   ========================================================================== */

import {
  t, localize, columnLabel, valueLabel, chartTypeLabel, chartChannels, getLang,
} from './i18n.js';
import {
  renderChart, buildOption, qualityGaugeOption, missingBarOption, missingMatrixOption,
  sparkHistogramOption, correlationHeatmapOption, trendLineOption, densityCompareOption,
  attachClickHandler, chartPng, fmtNumber, fmtRate,
} from './charts.js';
import { renderRows, renderSimpleTable, renderColumnStats, kindLabel } from './table.js';
import { state, columnMeta } from './store.js';

/* ------------------------------ 表单小工具 ------------------------------ */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

/** 视图级错误：后端某个视图算不出来时会返回 { error: {zh,en} }，就地显示而不是整页失效 */
function guardError(payload, ...targets) {
  if (!payload || !payload.error) return false;
  targets.filter(Boolean).forEach((target) => {
    target.innerHTML = '';
    const node = el('div', 'warning');
    node.textContent = localize(payload.error);
    target.appendChild(node);
  });
  return true;
}

function field(labelText, control) {
  const wrap = el('div', 'param-row');
  wrap.appendChild(el('label', null, labelText));
  if (control) wrap.appendChild(control);
  return wrap;
}

function selectControl(options, value, onChange) {
  const select = el('select', 'control');
  options.forEach((opt) => {
    const node = el('option', null, opt.label);
    node.value = opt.value === null || opt.value === undefined ? '' : String(opt.value);
    select.appendChild(node);
  });
  select.value = value === null || value === undefined ? '' : String(value);
  select.addEventListener('change', () => onChange(select.value === '' ? null : select.value));
  return select;
}

function numberControl(value, onChange, { min, max, step } = {}) {
  const input = el('input', 'control');
  input.type = 'number';
  if (min !== undefined) input.min = min;
  if (max !== undefined) input.max = max;
  if (step !== undefined) input.step = step;
  input.value = value === null || value === undefined ? '' : value;
  input.addEventListener('input', () => onChange(input.value === '' ? null : Number(input.value)));
  return input;
}

function checkboxControl(labelText, checked, onChange) {
  const wrap = el('label');
  wrap.style.display = 'flex';
  wrap.style.alignItems = 'center';
  wrap.style.gap = '6px';
  wrap.style.fontSize = '.75rem';
  wrap.style.color = 'var(--text-dim)';
  const box = document.createElement('input');
  box.type = 'checkbox';
  box.checked = Boolean(checked);
  box.addEventListener('change', () => onChange(box.checked));
  wrap.appendChild(box);
  wrap.appendChild(document.createTextNode(labelText));
  return wrap;
}

function chipsControl(options, selected, onChange) {
  const wrap = el('div', 'param-multi');
  const current = new Set(selected || []);
  options.forEach((opt) => {
    const label = el('label');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = current.has(opt.value);
    box.addEventListener('change', () => {
      if (box.checked) current.add(opt.value);
      else current.delete(opt.value);
      onChange(Array.from(current));
    });
    label.appendChild(box);
    label.appendChild(document.createTextNode(opt.label));
    wrap.appendChild(label);
  });
  return wrap;
}

/** 列选项：可选按 kind 过滤；label 用中英双语列名 */
function aggOptions() {
  const aggs = (state.meta && state.meta.aggs) || [];
  return aggs.map((agg) => ({ value: agg.value, label: localize(agg.label) }));
}

function currentColumns() {
  const pipelineColumns = state.pipeline && state.pipeline.columns;
  return (pipelineColumns && pipelineColumns.length ? pipelineColumns : (state.dataset && state.dataset.columns)) || [];
}

export function escapeHtml(text) {
  return String(text === null || text === undefined ? '' : text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function metaOf(name) {
  if (!name) return null;
  return currentColumns().find((col) => col.name === name) || columnMeta(name);
}

function columnsOfKind(...kinds) {
  return currentColumns().filter((col) => !kinds.length || kinds.includes(col.kind));
}

function columnOptionsFromKinds(kinds, { includeEmpty, emptyLabel } = {}) {
  const options = [];
  if (includeEmpty) options.push({ value: '', label: emptyLabel || t('common.none') });
  columnsOfKind(...(kinds || [])).forEach((col) => options.push({ value: col.name, label: columnLabel(col, col.name) }));
  return options;
}

/* =========================================================================
   1. 图表工作室
   ========================================================================= */

export function renderChartControls(container, onChange) {
  const spec = state.chart;
  container.innerHTML = '';

  const types = (state.meta && state.meta.chart_types) || [];
  container.appendChild(el('label', null, t('chart.type')));
  const grid = el('div', 'chart-type-grid');
  types.forEach((typeName) => {
    const button = el('button', `chart-type${spec.type === typeName ? ' is-active' : ''}`, chartTypeLabel(typeName));
    button.type = 'button';
    button.addEventListener('click', () => onChange({ type: typeName }));
    grid.appendChild(button);
  });
  container.appendChild(grid);

  const ch = chartChannels(spec.type);

  if (ch.x) {
    container.appendChild(field(t('chart.x'), selectControl(columnOptionsFromKinds(null), spec.x, (value) => onChange({ x: value }))));
  }
  if (ch.y) {
    container.appendChild(field(t('chart.y'), selectControl(columnOptionsFromKinds(['numeric'], { includeEmpty: !ch.agg }), spec.y, (value) => onChange({ y: value }))));
  }
  if (ch.series) {
    container.appendChild(field(t('chart.series'), selectControl(columnOptionsFromKinds(['categorical', 'boolean'], { includeEmpty: true }), spec.series, (value) => onChange({ series: value }))));
  }
  if (ch.size) {
    container.appendChild(field(t('chart.size'), selectControl(columnOptionsFromKinds(['numeric'], { includeEmpty: true }), spec.size, (value) => onChange({ size: value }))));
  }
  if (ch.dims) {
    container.appendChild(field(t('chart.dims'), chipsControl(
      columnOptionsFromKinds(['numeric']),
      spec.dims,
      (values) => onChange({ dims: values }),
    )));
  }
  if (ch.values) {
    container.appendChild(field(t('chart.values'), selectControl(columnOptionsFromKinds(['numeric'], { includeEmpty: true, emptyLabel: t('common.none') }), spec.values, (value) => onChange({ values: value }))));
  }
  if (ch.agg) {
    container.appendChild(field(t('chart.agg'), selectControl(aggOptions(), spec.agg, (value) => onChange({ agg: value }))));
  }
  if (ch.bins) {
    container.appendChild(field(t('chart.bins'), numberControl(spec.bins, (value) => onChange({ bins: value || 30 }), { min: 5, max: 120 })));
  }
  if (['bar', 'hbar', 'line', 'area', 'stacked_bar', 'stacked_area', 'percent_bar', 'pie', 'donut', 'rose', 'treemap', 'funnel', 'boxplot', 'violin'].includes(spec.type)) {
    const row = el('div', 'control-row');
    row.appendChild(field(t('chart.topN'), numberControl(spec.topN, (value) => onChange({ topN: value }), { min: 0, max: 200 })));
    row.appendChild(field(t('chart.sort'), selectControl([
      { value: 'desc', label: t('chart.sortDesc') },
      { value: 'asc', label: t('chart.sortAsc') },
      { value: 'none', label: t('chart.orderIndex') },
    ], spec.sort, (value) => onChange({ sort: value }))));
    container.appendChild(row);
  }

  const toggles = el('div');
  toggles.style.display = 'flex';
  toggles.style.flexWrap = 'wrap';
  toggles.style.gap = '10px';
  if (['bar', 'hbar', 'line', 'area', 'stacked_bar', 'stacked_area', 'percent_bar'].includes(spec.type)) {
    toggles.appendChild(checkboxControl(t('chart.stacked'), spec.stacked, (value) => onChange({ stacked: value })));
    toggles.appendChild(checkboxControl(t('chart.percent'), spec.percent, (value) => onChange({ percent: value })));
    toggles.appendChild(checkboxControl(t('chart.smooth'), spec.smooth, (value) => onChange({ smooth: value })));
    toggles.appendChild(checkboxControl(t('chart.labels'), spec.labels, (value) => onChange({ labels: value })));
    toggles.appendChild(checkboxControl(t('chart.logY'), spec.logY, (value) => onChange({ logY: value })));
  }
  if (ch.fit) {
    toggles.appendChild(checkboxControl(t('chart.fit'), spec.fit, (value) => onChange({ fit: value })));
  }
  if (toggles.childNodes.length) container.appendChild(toggles);

  if (ch.normalize) {
    container.appendChild(field(t('chart.normalize'), selectControl([
      { value: 'none', label: t('chart.normNone') },
      { value: 'row', label: t('chart.normRow') },
      { value: 'col', label: t('chart.normCol') },
    ], spec.normalize, (value) => onChange({ normalize: value }))));
  }
}

export function payloadForChart() {
  const spec = state.chart;
  const payload = { type: spec.type, agg: spec.agg };
  ['x', 'y', 'series', 'size', 'values', 'bins', 'topN', 'sort', 'stacked', 'percent', 'smooth', 'fit', 'labels', 'logY', 'normalize', 'dims'].forEach((key) => {
    if (spec[key] !== null && spec[key] !== undefined) payload[key] = spec[key];
  });
  return payload;
}

export function renderChartPanel(refs, handlers) {
  renderChartControls(refs.controls, (patch) => handlers.onSpecChange(patch));
  const chart = state.outputs.chart;
  const spec = state.chart;
  refs.title.textContent = `${chartTypeLabel(spec.type)} · ${columnLabel(metaOf(spec.x), spec.x) || '—'}${chart && chart.axis && chart.axis.y ? ` → ${columnLabel(metaOf(chart.axis.y), chart.axis.y)}` : ''}`;
  if (!chart) {
    renderChart(refs.chart, { title: { text: t('common.loading'), left: 'center', top: 'middle', textStyle: { color: 'var(--muted)' } } });
    return;
  }
  const instance = renderChart(refs.chart, buildOption(chart, spec, metaOf));
  refs.code.textContent = chart.code || t('chart.emptyCode');

  refs.warnings.innerHTML = '';
  if (guardError(chart, refs.warnings)) return;
  (chart.warnings || []).forEach((message) => refs.warnings.appendChild(el('div', 'warning', localize(message))));

  attachClickHandler(instance, chart, (event) => {
    const column = spec.x;
    const raw = event.raw;
    if (!column || raw === null || raw === undefined) return;
    handlers.onVisualFilter({ column, values: [String(raw)] });
  });

  // 数据规模提示 + 可视化提示
  const hints = refs.hints;
  hints.innerHTML = '';
  const axis = chart.axis || {};
  const addHint = (html) => {
    const node = el('div', 'hint');
    node.innerHTML = html;
    hints.appendChild(node);
  };
  addHint(
    `${t('chart.points')} <strong>${fmtNumber(chart.points_n !== undefined ? chart.points_n : (chart.categories || []).length)}</strong>` +
    ` · ${t('chart.seriesCount')} <strong>${(chart.series || []).length}</strong> · ${t('chart.categoriesCount')} <strong>${(chart.categories || []).length}</strong>`,
  );
  if (axis.x && axis.y) {
    addHint(t('chart.insightAgg', {
      x: escapeHtml(columnLabel(metaOf(axis.x), axis.x)),
      y: escapeHtml(columnLabel(metaOf(axis.y), axis.y)),
      agg: escapeHtml(localize(((state.meta && state.meta.aggs) || []).find((agg) => agg.value === axis.agg) || { zh: axis.agg, en: axis.agg }, axis.agg)),
    }));
  }
  if (spec.topN) addHint(t('chart.insightTop', { n: spec.topN }));
  if (['scatter', 'bubble'].includes(spec.type) && chart.corr !== undefined && chart.corr !== null) {
    addHint(`${t('chart.r')}：<strong>${Number(chart.corr).toFixed(3)}</strong> · ${t('chart.insightFit')}`);
  }
  if (spec.type === 'histogram') addHint(t('chart.insightHist'));
  if (spec.type === 'boxplot') addHint(t('chart.insightBox'));
  if (['scatter', 'bubble'].includes(spec.type)) addHint(t('chart.insightScatter'));
  if (['parallel', 'scatter_matrix'].includes(spec.type)) addHint(t('chart.insightParallel'));
  addHint(t('chart.clickHint'));
}

export function exportChartPng() {
  const node = document.getElementById('main-chart');
  const chart = node && node.__pandavizChart;
  if (chart) chartPng(chart, `pandaviz-${state.chart.type}`);
}

/* =========================================================================
   2. 数据表
   ========================================================================= */

export function renderTablePanel(refs, handlers) {
  const payload = state.outputs.table;
  if (!payload) return;
  if (guardError(payload, refs.table)) return;
  const columns = payload.columns || currentColumns();
  renderRows(refs.table, columns, payload.rows || [], {
    offset: payload.offset,
    sortBy: state.table.sort_by,
    sortDir: state.table.sort_dir,
    onSort: (column) => handlers.onSort(column),
  });
  renderColumnStats(refs.stats, payload.column_stats || [], columns);
  const from = payload.total === 0 ? 0 : payload.offset + 1;
  const to = Math.min(payload.offset + payload.limit, payload.total);
  refs.info.textContent = `${t('table.showing', { from, to, total: payload.total.toLocaleString() })} · ${t('table.output')}`;
}

/* =========================================================================
   3. 质量画像
   ========================================================================= */

export function renderProfilePanel(refs) {
  const payload = state.outputs.profile;
  if (!payload) return;
  if (guardError(payload, refs.kpis, refs.gauge)) return;
  const summary = payload.summary || {};
  renderChart(refs.gauge, qualityGaugeOption(summary.quality_score || 0, summary.quality_grade));
  refs.grade.textContent = `${localize(summary.quality_grade)}`;
  refs.grade.style.color = summary.quality_score >= 75 ? 'var(--ok)' : 'var(--warn)';

  const kpis = [
    [t('profile.rows'), (summary.rows || 0).toLocaleString()],
    [t('profile.cols'), summary.cols],
    [t('profile.cells'), (summary.cells || 0).toLocaleString()],
    [t('profile.missing'), `${(summary.missing_cells || 0).toLocaleString()} (${fmtRate(summary.missing_rate)})`],
    [t('profile.duplicates'), `${(summary.duplicated_rows || 0).toLocaleString()} (${fmtRate(summary.duplicated_rate)})`],
    [t('profile.numeric'), summary.numeric_cols],
    [t('profile.datetime'), summary.datetime_cols],
    [t('profile.categorical'), summary.categorical_cols],
    [t('profile.memory'), `${(summary.memory_bytes / 1024 / 1024).toFixed(2)} MB`],
  ];
  refs.kpis.innerHTML = '';
  kpis.forEach(([key, value]) => {
    const card = el('div', 'kpi');
    card.appendChild(el('div', 'k', key));
    card.appendChild(el('div', 'v', String(value)));
    refs.kpis.appendChild(card);
  });

  renderChart(refs.missingBar, missingBarOption(payload.missing_bar, metaOf));
  renderChart(refs.missingMatrix, missingMatrixOption(payload.missing_matrix, metaOf));
  refs.missingTip && (refs.missingTip.textContent = t('profile.tipMatrix'));

  refs.sparkGrid.innerHTML = '';
  (payload.columns || []).filter((col) => col.kind === 'numeric' && col.histogram).slice(0, 12).forEach((col) => {
    const card = el('div', 'spark-card');
    const title = el('div', 't');
    title.appendChild(el('span', null, columnLabel(col, col.name)));
    title.appendChild(el('span', null, `${t('profile.skew')} ${col.stats && col.stats.skew !== null ? Number(col.stats.skew).toFixed(2) : '—'}`));
    card.appendChild(title);
    const box = el('div', 'spark');
    card.appendChild(box);
    refs.sparkGrid.appendChild(card);
    renderChart(box, sparkHistogramOption(col.histogram));
  });

  const headerDefs = [
    { label: t('profile.column'), render: (row) => columnLabel(metaOf(row.name), row.name) },
    { label: t('profile.kind'), render: (row) => kindLabel(row.kind) },
    { label: t('profile.unique'), align: 'right', render: (row) => fmtNumber(row.nunique) },
    { label: t('profile.missingRate'), align: 'right', render: (row) => fmtRate(row.missing_rate) },
    {
      label: t('profile.topValues'),
      render: (row) => {
        if (row.top_values) {
          return row.top_values.slice(0, 3)
            .map((item) => `${item.label ? localize(item.label) : item.value} ×${item.count}`)
            .join(' · ');
        }
        if (row.stats) {
          return `mean ${fmtNumber(row.stats.mean)} · min ${fmtNumber(row.stats.min)} · max ${fmtNumber(row.stats.max)}`;
        }
        return '—';
      },
    },
    { label: t('profile.skew'), align: 'right', render: (row) => (row.stats && row.stats.skew !== null && row.stats.skew !== undefined ? Number(row.stats.skew).toFixed(2) : '—') },
  ];
  renderSimpleTable(refs.columns, headerDefs, payload.columns || []);
}

/* =========================================================================
   4. 关系分析
   ========================================================================= */

export function renderRelationPanel(refs, handlers) {
  refs.method.value = state.corr.method;
  refs.view.value = state.relationView;
  const corr = state.outputs.corr;
  const chart = state.outputs.relationChart;
  if (!corr) return;
  if (guardError(corr, refs.chart, refs.pairs)) return;

  refs.info.textContent = t('relation.sample', { cols: (corr.labels || []).length, rows: (corr.sampled_rows || 0).toLocaleString() });

  if (state.relationView === 'corr') {
    renderChart(refs.chart, correlationHeatmapOption(corr, metaOf));
  } else if (state.relationView === 'matrix' && chart) {
    renderChart(refs.chart, buildOption(chart, { type: 'scatter_matrix', dims: chart.dims, series: relationSeries(chart.axis && chart.axis.color) }, metaOf));
  } else if (state.relationView === 'parallel' && chart) {
    renderChart(refs.chart, buildOption(chart, { type: 'parallel', dims: chart.dims, series: relationSeries(chart.axis && chart.axis.series) }, metaOf));
  } else {
    renderChart(refs.chart, {});
  }

  const headerDefs = [
    { label: t('relation.pairX'), render: (row) => columnLabel(metaOf(row.x), row.x) },
    { label: t('relation.pairY'), render: (row) => columnLabel(metaOf(row.y), row.y) },
    { label: t('relation.r'), align: 'right', render: (row) => Number(row.r).toFixed(3) },
    {
      label: t('relation.strength'),
      render: (row) => {
        const abs = Math.abs(row.r);
        if (abs >= 0.7) return t('relation.strong');
        if (abs >= 0.4) return t('relation.medium');
        return t('relation.weak');
      },
    },
  ];
  renderSimpleTable(refs.pairs, headerDefs, corr.pairs || [], {
    onRowClick: (row) => handlers.onPairClick(row),
  });
  refs.code.textContent = corr.code || '';
  if (refs.hints) {
    refs.hints.innerHTML = '';
    refs.hints.appendChild(el('div', 'hint', t(state.relationView === 'parallel' ? 'relation.tipParallel' : 'relation.tipCorr')));
  }
}

/** 关系视图的分组列：优先用户选择，否则用第一个类别列让图形更有信息量 */
export function relationSeries(current) {
  if (current) return current;
  const categorical = columnsOfKind('categorical', 'boolean');
  return categorical.length ? categorical[0].name : null;
}

/* =========================================================================
   5. 透视表
   ========================================================================= */

export function renderPivotControls(container, onChange) {
  const cfg = state.pivot;
  container.innerHTML = '';
  container.appendChild(field(t('pivot.rows'), selectControl(columnOptionsFromKinds(['categorical', 'boolean', 'datetime', 'numeric']), cfg.index, (value) => onChange({ index: value }))));
  container.appendChild(field(t('pivot.cols'), selectControl(columnOptionsFromKinds(['categorical', 'boolean', 'datetime'], { includeEmpty: true }), cfg.columns, (value) => onChange({ columns: value }))));
  container.appendChild(field(t('pivot.values'), selectControl(columnOptionsFromKinds(['numeric'], { includeEmpty: true }), cfg.values, (value) => onChange({ values: value }))));
  container.appendChild(field(t('pivot.agg'), selectControl(aggOptions(), cfg.agg, (value) => onChange({ agg: value }))));
  container.appendChild(field(t('pivot.normalize'), selectControl([
    { value: 'none', label: t('chart.normNone') },
    { value: 'row', label: t('chart.normRow') },
    { value: 'col', label: t('chart.normCol') },
  ], cfg.normalize, (value) => onChange({ normalize: value }))));
}

export function renderPivotPanel(refs, handlers) {
  renderPivotControls(refs.controls, (patch) => handlers.onChange(patch));
  const payload = state.outputs.pivot;
  if (!payload) return;
  if (guardError(payload, refs.chart, refs.code)) return;
  renderChart(refs.chart, buildOption({ ...payload, type: 'heatmap', categories: payload.col_labels, row_labels: payload.row_labels, cells: payload.cells }, { ...state.pivot, x: state.pivot.columns, y: state.pivot.index, values: state.pivot.values }, metaOf));
  refs.code.textContent = payload.code || '';
  refs.hints.innerHTML = '';
  refs.hints.appendChild(el('div', 'hint', t('pivot.tip')));
  refs.hints.appendChild(el('div', 'hint', t('pivot.topValues')));
}

/* =========================================================================
   6. 时间序列
   ========================================================================= */

export function renderTimeseriesControls(container, onChange) {
  const cfg = state.timeseries;
  container.innerHTML = '';
  // 时间列只列真正的日期列：避免用户选到「区域」这类普通字段后才发现画不出来
  container.appendChild(field(t('ts.date'), selectControl(
    columnOptionsFromKinds(['datetime'], { includeEmpty: true, emptyLabel: t('ts.noDateColumn') }),
    cfg.date,
    (value) => onChange({ date: value }),
  )));
  container.appendChild(field(t('ts.value'), selectControl(columnOptionsFromKinds(['numeric'], { includeEmpty: true, emptyLabel: t('ts.noValueColumn') }), cfg.value, (value) => onChange({ value: value }))));
  container.appendChild(field(t('ts.group'), selectControl(columnOptionsFromKinds(['categorical', 'boolean'], { includeEmpty: true }), cfg.group, (value) => onChange({ group: value }))));
  container.appendChild(field(t('ts.freq'), selectControl(((state.meta && state.meta.resample_freqs) || []).map((item) => ({ value: item.value, label: localize(item.label) })), cfg.freq, (value) => onChange({ freq: value }))));
  container.appendChild(field(t('ts.agg'), selectControl(aggOptions(), cfg.agg, (value) => onChange({ agg: value }))));
  container.appendChild(field(t('ts.rolling'), numberControl(cfg.rolling, (value) => onChange({ rolling: value || 0 }), { min: 0, max: 365 })));
}

export function renderTimeseriesPanel(refs, handlers) {
  renderTimeseriesControls(refs.controls, (patch) => handlers.onChange(patch));
  const payload = state.outputs.timeseries;
  if (!payload) return;
  if (guardError(payload, refs.chart, refs.trend, refs.code)) return;
  if (payload.error || !payload.categories || !payload.categories.length) {
    renderChart(refs.chart, {});
    refs.code.textContent = payload.code || '';
    refs.trend.innerHTML = '';
    const pipeline = state.pipeline || {};
    refs.trend.appendChild(el('div', 'hint', t('ts.noDate', {
      rows: (pipeline.rows || 0).toLocaleString(),
      cols: pipeline.cols || 0,
    })));
    if (state.steps.length) {
      const clear = el('button', 'btn tiny primary', t('ts.clearPipeline'));
      clear.type = 'button';
      clear.addEventListener('click', () => handlers.onClearSteps && handlers.onClearSteps());
      refs.trend.appendChild(clear);
    }
    return;
  }
  renderChart(refs.chart, trendLineOption({ ...payload, __date: state.timeseries.date, __value: state.timeseries.value }, metaOf));
  refs.code.textContent = payload.code || '';
  refs.trend.innerHTML = '';
  const rows = [
    [t('ts.rows'), fmtNumber(payload.rows)],
    [t('ts.agg'), localize(((state.meta && state.meta.aggs) || []).find((agg) => agg.value === payload.agg) || { zh: payload.agg, en: payload.agg }, payload.agg)],
  ];
  if (payload.trend) {
    rows.push([t('ts.direction'), localize(payload.trend.direction)]);
    rows.push([t('ts.slope'), fmtNumber(payload.trend.slope, 4)]);
    rows.push([t('ts.change'), fmtRate(payload.trend.change_rate)]);
  }
  const summary = el('div', 'hint');
  summary.innerHTML = rows.map(([key, value]) => `<strong>${escapeHtml(key)}</strong>：${escapeHtml(value)}`).join('<br>');
  refs.trend.appendChild(summary);
  refs.trend.appendChild(el('div', 'hint', t('ts.tip')));
}

/* =========================================================================
   7. 统计检验
   ========================================================================= */

export function renderStatsControls(container, onChange) {
  const cfg = state.stats;
  container.innerHTML = '';
  container.appendChild(field(t('stats.test'), selectControl([
    { value: 'ttest', label: t('stats.ttest') },
    { value: 'anova', label: t('stats.anova') },
    { value: 'chi2', label: t('stats.chi2') },
    { value: 'normality', label: t('stats.normality') },
  ], cfg.test, (value) => onChange({ test: value }))));
  if (cfg.test === 'chi2') {
    container.appendChild(field(t('stats.value'), selectControl(columnOptionsFromKinds(['categorical', 'boolean']), cfg.value, (value) => onChange({ value }))));
    container.appendChild(field(t('stats.group'), selectControl(columnOptionsFromKinds(['categorical', 'boolean']), cfg.group, (value) => onChange({ group: value }))));
  } else if (cfg.test === 'normality') {
    container.appendChild(field(t('stats.value'), selectControl(columnOptionsFromKinds(['numeric']), cfg.value, (value) => onChange({ value }))));
  } else {
    container.appendChild(field(t('stats.value'), selectControl(columnOptionsFromKinds(['numeric']), cfg.value, (value) => onChange({ value }))));
    container.appendChild(field(t('stats.group'), selectControl(columnOptionsFromKinds(['categorical', 'boolean']), cfg.group, (value) => onChange({ group: value }))));
  }
}

export function renderStatsPanel(refs, handlers) {
  renderStatsControls(refs.controls, (patch) => handlers.onChange(patch));
  const payload = state.outputs.stats;
  if (!payload) return;
  refs.result.innerHTML = '';
  refs.conclusion.textContent = '';
  refs.chartBox.style.display = 'none';

  if (guardError(payload, refs.result)) {
    refs.code.textContent = payload.code || '';
    refs.groups.innerHTML = '';
    renderChart(refs.chart, {});
    return;
  }

  const kpis = [
    [t('stats.name'), localize(payload.name)],
    [t('stats.stat'), fmtNumber(payload.stat)],
    [t('stats.p'), payload.p === null ? '—' : Number(payload.p).toExponential(3)],
  ];
  if (payload.dof) kpis.push([t('stats.dof'), payload.dof]);
  if (payload.effect) kpis.push([localize(payload.effect.label), fmtNumber(payload.effect.value)]);
  kpis.forEach(([key, value]) => {
    const card = el('div', 'kpi');
    card.appendChild(el('div', 'k', key));
    card.appendChild(el('div', 'v', String(value)));
    refs.result.appendChild(card);
  });
  refs.conclusion.textContent = `${t('stats.conclusion')}：${localize(payload.conclusion)}　·　${t('stats.tip')}`;

  if (payload.chart && payload.chart.type === 'density' && (payload.chart.series || []).length) {
    refs.chartBox.style.display = '';
    renderChart(refs.chart, densityCompareOption(payload.chart, metaOf));
  } else if (payload.chart && payload.chart.type === 'heatmap') {
    refs.chartBox.style.display = '';
    renderChart(refs.chart, buildOption({ ...payload.chart, type: 'heatmap', categories: payload.chart.col_labels, row_labels: payload.chart.row_labels, cells: payload.chart.cells }, { type: 'heatmap', x: state.stats.group, y: state.stats.value }, metaOf));
  } else {
    renderChart(refs.chart, {});
  }

  const headerDefs = [
    { label: t('stats.groupName'), render: (row) => row.name },
    { label: t('stats.n'), align: 'right', render: (row) => fmtNumber(row.n) },
    { label: t('stats.mean'), align: 'right', render: (row) => fmtNumber(row.mean) },
    { label: t('stats.median'), align: 'right', render: (row) => fmtNumber(row.median) },
    { label: t('stats.std'), align: 'right', render: (row) => fmtNumber(row.std) },
    { label: t('stats.q1'), align: 'right', render: (row) => fmtNumber(row.q1) },
    { label: t('stats.q3'), align: 'right', render: (row) => fmtNumber(row.q3) },
  ];
  renderSimpleTable(refs.groups, headerDefs, payload.groups || []);
  refs.code.textContent = payload.code || '';
}

/* =========================================================================
   8. 自动洞察
   ========================================================================= */

export function renderInsightsPanel(refs, handlers) {
  const payload = state.outputs.insights;
  if (!payload) return;
  if (guardError(payload, refs.list, refs.gauge)) return;
  renderChart(refs.gauge, qualityGaugeOption(payload.score || 0, { zh: t('insights.score'), en: t('insights.score') }));
  refs.list.innerHTML = '';
  const items = payload.insights || [];
  if (!items.length) {
    refs.list.appendChild(el('div', 'hint', t('insights.none')));
    return;
  }
  items.forEach((item) => {
    const card = el('div', 'insight-card');
    card.dataset.level = item.level || 'info';
    card.appendChild(el('div', 'insight-tag', item.level || 'info'));
    card.appendChild(el('h4', null, localize(item.title)));
    card.appendChild(el('p', null, localize(item.detail)));
    if (item.action) {
      const link = el('div', 'small');
      link.style.marginTop = '8px';
      link.style.color = 'var(--accent-2)';
      link.textContent = `${t('insights.jump')} ↗`;
      card.appendChild(link);
      card.addEventListener('click', () => handlers.onJump(item.action));
    }
    refs.list.appendChild(card);
  });
}

/* =========================================================================
   9. 代码
   ========================================================================= */

export function renderCodePanel(refs) {
  const code = state.outputs.code;
  const pipeline = state.pipeline;
  const lines = (code && code.lines) || (pipeline && pipeline.code) || [];
  refs.pipeline.textContent = lines.length
    ? lines.map((line, index) => `# ${t('common.step')} ${index + 1}\n${line}`).join('\n\n')
    : '# ' + t('pipeline.empty');
  refs.script.textContent = (code && code.script) || '# ' + t('code.tip');
}

export function copyText(text) {
  if (!text) return Promise.resolve(false);
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text).then(() => true).catch(() => false);
  }
  const area = document.createElement('textarea');
  area.value = text;
  document.body.appendChild(area);
  area.select();
  const ok = document.execCommand('copy');
  area.remove();
  return Promise.resolve(ok);
}

export { el as createEl, metaOf };
