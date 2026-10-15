/* ==========================================================================
   应用入口：引导、事件绑定、数据流（前端 -> 后端 pandas -> 图形）
   ========================================================================== */

import { api } from './api.js';
import { state, loadSteps, saveSteps, defaultEncodings, preferMetric } from './store.js';
import { t, setLang, getLang, localize, columnLabel, applyStaticTranslations } from './i18n.js';
import { resizeAllCharts } from './charts.js';
import {
  renderOpPalette, renderStepList, renderFunnel, defaultParamsFor, resetStepOpenState, openOnlyStep,
} from './pipeline.js';
import { renderSimpleTable } from './table.js';
import {
  renderChartPanel, renderTablePanel, renderProfilePanel, renderRelationPanel,
  renderPivotPanel, renderTimeseriesPanel, renderStatsPanel, renderInsightsPanel,
  renderCodePanel, exportChartPng, payloadForChart, copyText, createEl, metaOf, relationSeries,
} from './views.js';

const dom = {};
let refreshToken = 0;

function $(id) {
  return document.getElementById(id);
}

function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function currentColumns() {
  const pipelineColumns = state.pipeline && state.pipeline.columns;
  return (pipelineColumns && pipelineColumns.length ? pipelineColumns : (state.dataset && state.dataset.columns)) || [];
}

function toast(message, kind) {
  const node = createEl('div', `toast ${kind || ''}`, message);
  dom.toasts.appendChild(node);
  setTimeout(() => node.remove(), kind === 'error' ? 7200 : 3600);
}

function setLoading(delta) {
  state.loading = Math.max(0, (state.loading || 0) + delta);
  dom.loading.classList.toggle('hidden', state.loading === 0);
}

/* --------------------------- 主数据流 --------------------------- */

function buildPayload(parts) {
  const payload = { dataset_id: state.datasetId, steps: state.steps };
  if (parts.table) payload.table = { ...state.table };
  if (parts.chart) payload.chart = payloadForChart();
  if (parts.profile) payload.profile = true;
  if (parts.corr) payload.corr = { method: state.corr.method };
  if (parts.insights) payload.insights = true;
  if (parts.code) payload.code = true;
  if (parts.pivot && state.pivot.index && state.pivot.values) payload.pivot = { ...state.pivot };
  if (parts.timeseries && state.timeseries.date && state.timeseries.value) payload.timeseries = { ...state.timeseries };
  if (parts.stats && state.stats.value) payload.stats = { ...state.stats };
  return payload;
}

async function runAnalysis(parts, options = {}) {
  if (!state.datasetId) return;
  const token = ++refreshToken;
  const sentSteps = JSON.stringify(state.steps);
  setLoading(1);
  const started = performance.now();
  try {
    const response = await api.analyze(buildPayload(parts));
    if (token !== refreshToken && !options.force) return;
    // 步骤在请求过程中又变了：这次响应对应的是旧管道，直接丢弃，
    // 否则界面会出现“新步骤 + 旧结果”的错位（状态栏与卡片对不上）。
    if (JSON.stringify(state.steps) !== sentSteps) return;
    state.pipeline = response.pipeline;
    state.error = response.pipeline && response.pipeline.error;
    Object.assign(state.outputs, response.outputs || {});
    state.latency = Math.round(performance.now() - started);
    if (response.dataset) state.dataset = response.dataset;
    reconcileSelections();
    renderStatus();
    renderStepArea();
    renderActiveTab();
  } catch (err) {
    toast(`${t('common.error')}: ${err.message}`, 'error');
    console.error(err);
  } finally {
    setLoading(-1);
  }
}

const fullRefresh = debounce(() => {
  saveSteps(state.datasetId, state.steps);
  runAnalysis({
    table: true, chart: true, profile: true, corr: true, insights: true, code: true,
    pivot: true, timeseries: true, stats: true,
  });
}, 30);

const refreshChartOnly = debounce(() => runAnalysis({ chart: true, code: true }), 220);
const refreshTableOnly = debounce(() => runAnalysis({ table: true }), 200);
const refreshPivotOnly = debounce(() => runAnalysis({ pivot: true }), 200);
const refreshTimeseriesOnly = debounce(() => runAnalysis({ timeseries: true }), 200);
const refreshStatsOnly = debounce(() => runAnalysis({ stats: true }), 200);
const refreshCorrOnly = debounce(() => runAnalysis({ corr: true }), 200);

/* --------------------------- 状态栏 --------------------------- */

function renderStatus() {
  const pipeline = state.pipeline;
  const dataset = state.dataset;
  dom.chipShape.textContent = pipeline ? `${pipeline.rows.toLocaleString()} × ${pipeline.cols}` : '—';
  dom.chipShape.title = `${t('table.output')}（pandas 真实计算结果）`;
  dom.chipDataset.textContent = dataset ? `${localize(dataset.name)} · ${dataset.rows.toLocaleString()} × ${dataset.cols}` : '—';
  dom.chipPandas.textContent = `pandas ${(state.meta && state.meta.pandas_version) || '?'}`;
  dom.chipSteps.textContent = `${t('pipeline.steps')}: ${state.steps.length}`;
  dom.chipLatency.textContent = state.latency === null ? '—' : `${state.latency} ms`;
  if (pipeline && pipeline.error) {
    dom.chipError.classList.remove('hidden');
    dom.chipError.classList.add('bad');
    dom.chipError.textContent = `${t('common.step')} ${pipeline.error.step + 1}: ${pipeline.error.message}`;
    dom.chipError.title = pipeline.error.message;
  } else {
    dom.chipError.classList.add('hidden');
  }
  dom.stepCount.textContent = String(state.steps.length);
  dom.stepEmpty.classList.toggle('hidden', state.steps.length > 0);
}

/* --------------------------- 管道 --------------------------- */

const pipelineHandlers = {
  onToggle(index) {
    state.steps[index].enabled = state.steps[index].enabled === false;
    fullRefresh();
  },
  onRemove(index) {
    state.steps.splice(index, 1);
    resetStepOpenState();
    fullRefresh();
  },
  onMove(index, delta) {
    const target = index + delta;
    if (target < 0 || target >= state.steps.length) return;
    const [item] = state.steps.splice(index, 1);
    state.steps.splice(target, 0, item);
    resetStepOpenState();
    fullRefresh();
  },
  onUpdateParams(index, params) {
    state.steps[index].params = params;
    fullRefresh();
  },
  onPreview(index) {
    state.previewIndex = index;
    const sentSteps = JSON.stringify(state.steps);
    api.analyze({ dataset_id: state.datasetId, steps: state.steps, step_preview: index })
      .then((response) => {
        if (JSON.stringify(state.steps) !== sentSteps) return; // 步骤已变，丢弃这次预览
        state.outputs.stepPreview = {
          columns: response.pipeline.columns || currentColumns(),
          rows: (response.pipeline.preview && response.pipeline.preview.rows) || [],
        };
        renderStepArea(index);
      })
      .catch((err) => toast(err.message, 'error'));
  },
};

/** 第 index 步的“输入列”：往前找最近一个成功步骤的输出列，找不到就用原始数据集列。
 *  这样 groupby / pivot 等改变列的步骤之后，下一步的下拉里依然是“当时真实存在的列”。 */
function columnsForStep(index) {
  const pipelineSteps = (state.pipeline && state.pipeline.steps) || [];
  for (let i = index - 1; i >= 0; i -= 1) {
    const info = pipelineSteps.find((item) => item.index === i);
    if (info && Array.isArray(info.columns) && info.columns.length) return info.columns;
  }
  return (state.dataset && state.dataset.columns) || [];
}

function renderStepArea(previewIndex) {
  renderStepList(dom.stepList, {
    steps: state.steps,
    pipeline: state.pipeline,
    ops: (state.meta && state.meta.ops) || [],
    columns: currentColumns(),
    columnsForStep,
    datasets: state.datasets,
    aggs: (state.meta && state.meta.aggs) || [],
    currentDatasetId: state.datasetId,
    previewIndex: previewIndex !== undefined ? previewIndex : state.previewIndex,
    preview: state.outputs.stepPreview,
    stats: (state.outputs.table && state.outputs.table.column_stats) || [],
  }, pipelineHandlers);
  renderFunnel(dom.funnelChart, (state.pipeline && state.pipeline.steps) || [], (state.dataset && state.dataset.rows) || 0);
  dom.stepPreviewWrap.innerHTML = '';
  if (!state.steps.length) {
    dom.stepPreviewWrap.appendChild(createEl('p', 'empty-hint', t('pipeline.previewEmpty')));
  }
}

function addStep(op) {
  const columns = currentColumns();
  const params = refineDefaultParams(op, defaultParamsFor(op, {
    columns,
    datasets: state.datasets,
    currentDatasetId: state.datasetId,
  }), columns);
  state.steps.push({ type: op.id, params, enabled: true });
  openOnlyStep(state.steps.length - 1); // 新加的步骤自动展开，方便立刻改参数
  fullRefresh();
  toast(`${localize(op.label)} · ${t('common.step')} ${state.steps.length}`, 'ok');
}

/* ------------------- 让新添加的算子“点一下就能跑” -------------------
   defaultParamsFor 只按 schema 填默认值，像「条件筛选」的“值”会是空的，
   一添加就会报错。这里按列统计（中位数等）补齐那些必填项，保证新步骤立即有效。 */

function columnStatsOf(name) {
  const stats = (state.outputs.table && state.outputs.table.column_stats) || [];
  return stats.find((item) => item.name === name) || null;
}

function quoteIdent(name) {
  if (!name) return 'x';
  return /^[^\W\d]\w*$/.test(name) ? name : `\`${name}\``;
}

function refineDefaultParams(op, params, columns) {
  const numeric = columns.filter((col) => col.kind === 'numeric');
  const firstNumeric = numeric.length ? numeric[0].name : null;
  const firstAny = columns.length ? columns[0].name : null;

  switch (op.id) {
    case 'filter_row': {
      if (!params.column) params.column = firstNumeric || firstAny;
      if (!params.operator) params.operator = '>';
      const empty = params.value === '' || params.value === null || params.value === undefined;
      if (empty) {
        const stats = columnStatsOf(params.column);
        if (stats && stats.median !== null && stats.median !== undefined) params.value = stats.median;
        else if (stats && stats.mean) params.value = Math.round(stats.mean);
        else {
          // 拿不到列统计（例如刚打开页面）→ 退化成“非空筛选”，依然是一个有效且有意义的一步
          params.operator = 'notna';
          params.value = null;
        }
      }
      break;
    }
    case 'filter_query': {
      if (!params.expr) params.expr = `${quoteIdent(firstNumeric || firstAny)} > 0`;
      break;
    }
    case 'assign_expr': {
      if (!params.name) params.name = '新列';
      if (!params.expr) params.expr = firstNumeric || '1';
      break;
    }
    case 'rename_columns': {
      if (!params.new) params.new = `${params.old || '列'}_重命名`;
      break;
    }
    case 'range_filter': {
      const stats = columnStatsOf(params.column);
      if (stats) {
        if (params.min === undefined || params.min === null) params.min = Math.floor(stats.min);
        if (params.max === undefined || params.max === null) params.max = Math.ceil(stats.max);
      }
      break;
    }
    default:
      break;
  }
  return params;
}

function addVisualFilterStep({ column, values }) {
  const columns = currentColumns();
  const list = (values || []).filter((value) => value !== null && value !== '∅');
  if (!list.length) return;
  const existing = state.steps.findIndex((step) => step.type === 'category_filter' && step.params && step.params.column === column);
  const patch = { type: 'category_filter', params: { column, values: list }, enabled: true };
  if (existing >= 0) state.steps[existing] = patch;
  else state.steps.push(patch);
  fullRefresh();
  toast(`${t('tab.chart')} → ${localize({ zh: '图形筛选', en: 'Visual filter' })}: ${columnLabel(metaOf(column), column)} ∈ {${list.join(', ')}}`, 'ok');
}

/** 清空整条管道，回到原始数据（左侧「清空」按钮与各视图的空状态都在用） */
function clearAllSteps() {
  state.steps = [];
  resetStepOpenState();
  fullRefresh();
  toast(t('pipeline.cleared'), 'ok');
}

/* --------------------------- 视图渲染 --------------------------- */

function renderActiveTab() {
  switch (state.activeTab) {
    case 'chart':
      renderChartPanel(dom.chart, { onSpecChange: handleChartSpecChange, onVisualFilter: addVisualFilterStep });
      break;
    case 'table':
      renderTablePanel(dom.table, {
        onSort: (column) => {
          if (state.table.sort_by === column) state.table.sort_dir = state.table.sort_dir === 'desc' ? 'asc' : 'desc';
          else {
            state.table.sort_by = column;
            state.table.sort_dir = 'desc';
          }
          refreshTableOnly();
        },
      });
      break;
    case 'profile':
      renderProfilePanel(dom.profile);
      break;
    case 'relation':
      renderRelationPanel(dom.relation, relationHandlers);
      break;
    case 'pivot':
      renderPivotPanel(dom.pivotView, {
        onChange: (patch) => {
          Object.assign(state.pivot, patch);
          refreshPivotOnly();
        },
      });
      break;
    case 'timeseries':
      renderTimeseriesPanel(dom.ts, {
        onChange: (patch) => {
          Object.assign(state.timeseries, patch);
          refreshTimeseriesOnly();
        },
        onClearSteps: clearAllSteps,
      });
      break;
    case 'stats':
      renderStatsPanel(dom.statsPanel, {
        onChange: (patch) => {
          Object.assign(state.stats, patch);
          refreshStatsOnly();
        },
      });
      break;
    case 'insights':
      renderInsightsPanel(dom.insights, { onJump: jumpToInsight });
      break;
    case 'code':
      renderCodePanel(dom.codePanel);
      break;
    default:
      break;
  }
  resizeAllCharts();
}

function handleChartSpecChange(patch) {
  // X 轴与分色不能是同一列：否则后端分组键重复，整张图都画不出来
  const merged = { ...state.chart, ...patch };
  if (merged.series && merged.series === merged.x) {
    if (patch.series !== undefined) {
      toast(t('chart.duplicateChannel'), 'error');
      delete patch.series;
    } else {
      patch.series = null;
    }
  }
  Object.assign(state.chart, patch);
  const structural = ['x', 'y', 'series', 'size', 'agg', 'type', 'values', 'dims', 'bins', 'fit'].some((key) => key in patch);
  renderChartPanel(dom.chart, { onSpecChange: handleChartSpecChange, onVisualFilter: addVisualFilterStep });
  if (structural) runAnalysis({ chart: true, code: true, insights: true });
  else refreshChartOnly();
}

const relationHandlers = {
  onPairClick(row) {
    Object.assign(state.chart, { type: 'scatter', x: row.x, y: row.y, fit: true });
    switchTab('chart');
    runAnalysis({ chart: true, code: true });
  },
};

function jumpToInsight(action) {
  if (!action) return;
  if (action.view === 'chart') {
    const patch = { type: action.chart || state.chart.type };
    if (action.x) patch.x = action.x;
    if (action.y) patch.y = action.y;
    if (action.topN) patch.topN = action.topN;
    if (action.fit !== undefined) patch.fit = action.fit;
    Object.assign(state.chart, patch);
    switchTab('chart');
    runAnalysis({ chart: true, code: true });
  } else if (action.view === 'timeseries') {
    if (action.date && currentColumns().some((col) => col.name === action.date)) state.timeseries.date = action.date;
    if (action.value) state.timeseries.value = action.value;
    state.timeseries.rolling = Math.max(state.timeseries.rolling || 0, 7);
    switchTab('timeseries');
    runAnalysis({ timeseries: true });
  } else if (action.view === 'profile') {
    switchTab('profile');
    if (!state.outputs.profile) runAnalysis({ profile: true });
  } else if (action.view === 'pipeline') {
    const op = ((state.meta && state.meta.ops) || []).find((item) => item.id === action.op);
    if (op) addStep(op);
  }
}

/* --------------------------- 标签页 --------------------------- */

const TAB_NAMES = ['chart', 'table', 'profile', 'relation', 'pivot', 'timeseries', 'stats', 'insights', 'code'];

function readHash() {
  const raw = (location.hash || '').replace(/^#/, '');
  const [tab, sub] = raw.split('/');
  return { tab: TAB_NAMES.includes(tab) ? tab : null, sub: sub || null };
}

function writeHash() {
  const sub = state.activeTab === 'relation' && state.relationView !== 'corr' ? `/${state.relationView}` : '';
  const next = `#${state.activeTab}${sub}`;
  if (location.hash !== next) history.replaceState(null, '', next);
}

function switchTab(name, options = {}) {
  state.activeTab = name;
  if (!options.silent) writeHash();
  document.querySelectorAll('.tab').forEach((tab) => tab.classList.toggle('is-active', tab.dataset.tab === name));
  document.querySelectorAll('.view').forEach((view) => view.classList.toggle('is-active', view.dataset.view === name));
  const needs = {
    table: !state.outputs.table,
    profile: !state.outputs.profile,
    corr: !state.outputs.corr,
    insights: !state.outputs.insights,
    code: !state.outputs.code,
  };
  if (needs[name]) {
    runAnalysis({ [name]: true });
  } else {
    renderActiveTab();
  }
  if (name === 'relation' && state.relationView !== 'corr' && !state.outputs.relationChart) {
    requestRelationChart();
  }
}

function requestRelationChart() {
  const series = relationSeries(state.chart.series);
  const spec = state.relationView === 'matrix'
    ? { type: 'scatter_matrix', dims: state.chart.dims, series }
    : { type: 'parallel', dims: state.chart.dims, series };
  setLoading(1);
  api.analyze({ dataset_id: state.datasetId, steps: state.steps, chart: spec })
    .then((response) => {
      state.outputs.relationChart = response.outputs && response.outputs.chart;
      if (state.activeTab === 'relation') renderRelationPanel(dom.relation, relationHandlers);
    })
    .catch((err) => toast(err.message, 'error'))
    .finally(() => setLoading(-1));
}

/* --------------------------- 数据集 --------------------------- */

function renderDatasetSelect() {
  dom.datasetSelect.innerHTML = '';
  const groups = [
    { key: 'builtin', label: t('dataset.builtin') },
    { key: 'upload', label: t('dataset.upload') },
  ];
  groups.forEach((group) => {
    const items = state.datasets.filter((item) => item.source === group.key);
    if (!items.length) return;
    const optgroup = document.createElement('optgroup');
    optgroup.label = group.label;
    items.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = `${localize(item.name)} — ${item.rows.toLocaleString()}×${item.cols}`;
      optgroup.appendChild(option);
    });
    dom.datasetSelect.appendChild(optgroup);
  });
  dom.datasetSelect.value = state.datasetId || '';
}

async function selectDataset(datasetId, { keepSteps } = {}) {
  state.datasetId = datasetId;
  const detail = await api.dataset(datasetId);
  state.dataset = detail.dataset;
  state.pipeline = null;
  state.outputs = {};
  state.previewIndex = undefined;
  resetStepOpenState();
  state.steps = keepSteps ? state.steps : loadSteps(datasetId);
  // 旧步骤里可能残留“必填参数为空”的（比如早期版本的「条件筛选」），顺手补齐，避免一打开就报错
  const ops = (state.meta && state.meta.ops) || [];
  state.steps = state.steps.map((step) => {
    const op = ops.find((item) => item.id === step.type);
    if (!op) return step;
    return { ...step, params: refineDefaultParams(op, { ...(step.params || {}) }, (state.dataset && state.dataset.columns) || []) };
  });
  applyDefaultEncodings();
  renderDatasetSelect();
  fullRefresh();
}

function applyDefaultEncodings() {
  const defaults = defaultEncodings();
  state.chart = { ...state.chart, ...defaults.chart, type: state.chart.type || 'bar' };
  state.pivot = { ...state.pivot, ...defaults.pivot };
  state.timeseries = { ...state.timeseries, ...defaults.timeseries };
  state.stats = { ...state.stats, ...defaults.stats };
  state.table = { offset: 0, limit: state.table.limit, sort_by: null, sort_dir: 'asc', search: '' };
}

/** 管道列变化后，保证各视图的选择依然有效 */
function reconcileSelections() {
  const columns = currentColumns();
  const names = new Set(columns.map((col) => col.name));
  const numeric = columns.filter((col) => col.kind === 'numeric').map((col) => col.name);
  const categorical = columns.filter((col) => col.kind === 'categorical' || col.kind === 'boolean').map((col) => col.name);
  const datetimes = columns.filter((col) => col.kind === 'datetime').map((col) => col.name);
  const pick = (current, pool) => (current && names.has(current) ? current : (pool[0] || null));
  // 数值通道优先挑“金额/指标类”列（销售额、AQI…），时间通道只接受真正的日期列
  const pickMetric = (current, pool) => (current && names.has(current) ? current : (preferMetric(pool) || null));
  const pickDate = (current) => (current && datetimes.includes(current) ? current : (datetimes[0] || null));

  state.chart.x = pick(state.chart.x, categorical.concat(numeric));
  state.chart.y = pickMetric(state.chart.y, numeric);
  state.chart.series = state.chart.series && names.has(state.chart.series) ? state.chart.series : null;
  state.chart.size = pickMetric(state.chart.size, numeric);
  state.chart.values = pickMetric(state.chart.values, numeric);
  state.chart.dims = (state.chart.dims || []).filter((name) => names.has(name));
  if (!state.chart.dims.length) state.chart.dims = numeric.slice(0, 4);
  state.pivot.index = pick(state.pivot.index, categorical.concat(numeric));
  state.pivot.columns = state.pivot.columns && names.has(state.pivot.columns) ? state.pivot.columns : (categorical[1] || null);
  state.pivot.values = pickMetric(state.pivot.values, numeric);
  state.timeseries.date = pickDate(state.timeseries.date);
  state.timeseries.value = pickMetric(state.timeseries.value, numeric);
  state.timeseries.group = state.timeseries.group && names.has(state.timeseries.group) ? state.timeseries.group : null;
  state.stats.value = pickMetric(state.stats.value, state.stats.test === 'chi2' ? categorical : numeric);
  state.stats.group = pick(state.stats.group, categorical);
}

/* --------------------------- 上传 / 概览模态 --------------------------- */

function openModal({ title, body, foot }) {
  dom.modalTitle.textContent = title;
  dom.modalBody.innerHTML = '';
  dom.modalBody.appendChild(body);
  dom.modalFoot.innerHTML = '';
  (foot || []).forEach((node) => dom.modalFoot.appendChild(node));
  dom.backdrop.classList.remove('hidden');
}

function closeModal() {
  dom.backdrop.classList.add('hidden');
}

function buildUploadBody() {
  const wrap = createEl('div');
  wrap.style.display = 'flex';
  wrap.style.flexDirection = 'column';
  wrap.style.gap = '12px';

  const hint = createEl('p', 'muted small', t('upload.desc'));
  wrap.appendChild(hint);

  const drop = createEl('div', 'dataset-card');
  drop.style.textAlign = 'center';
  drop.style.padding = '26px';
  drop.style.borderStyle = 'dashed';
  drop.appendChild(createEl('p', null, `${t('upload.drop')} `));
  const pick = createEl('button', 'btn primary', t('upload.pick'));
  pick.type = 'button';
  pick.style.marginTop = '10px';
  pick.addEventListener('click', () => dom.fileInput.click());
  drop.appendChild(pick);
  const chosen = createEl('p', 'small');
  chosen.style.marginTop = '10px';
  chosen.style.color = 'var(--accent-2)';
  drop.appendChild(chosen);
  ['dragenter', 'dragover'].forEach((evt) => drop.addEventListener(evt, (event) => {
    event.preventDefault();
    drop.style.borderColor = 'var(--accent)';
  }));
  ['dragleave', 'drop'].forEach((evt) => drop.addEventListener(evt, (event) => {
    event.preventDefault();
    drop.style.borderColor = '';
  }));
  drop.addEventListener('drop', (event) => {
    const file = event.dataTransfer.files && event.dataTransfer.files[0];
    if (file) {
      dom.pendingFile = file;
      chosen.textContent = `${t('upload.selected')}: ${file.name}`;
    }
  });
  wrap.appendChild(drop);

  const grid = createEl('div', 'form-grid');
  const mk = (label, control) => {
    const row = createEl('div', 'param-row');
    row.appendChild(createEl('label', null, label));
    row.appendChild(control);
    grid.appendChild(row);
  };
  const sepSelect = document.createElement('select');
  sepSelect.className = 'control';
  [['', t('upload.auto')], [',', ','], ['\t', 'Tab'], [';', ';'], ['|', '|']].forEach(([value, label]) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    sepSelect.appendChild(option);
  });
  mk(t('upload.sep'), sepSelect);

  const encInput = document.createElement('input');
  encInput.className = 'control';
  encInput.placeholder = 'utf-8 / gb18030 / latin-1';
  mk(t('upload.encoding'), encInput);

  const headerInput = document.createElement('input');
  headerInput.className = 'control';
  headerInput.type = 'number';
  headerInput.value = '0';
  headerInput.min = '0';
  mk(t('upload.header'), headerInput);

  const nameInput = document.createElement('input');
  nameInput.className = 'control';
  mk(t('upload.displayName'), nameInput);
  wrap.appendChild(grid);

  wrap.__collect = () => ({
    file: dom.pendingFile,
    options: {
      sep: sepSelect.value,
      encoding: encInput.value.trim(),
      header_row: headerInput.value,
      display_name: nameInput.value.trim(),
      display_name_en: nameInput.value.trim(),
    },
  });
  return wrap;
}

function openUploadModal() {
  dom.pendingFile = null;
  const body = buildUploadBody();
  const confirm = createEl('button', 'btn primary', t('upload.confirm'));
  confirm.type = 'button';
  confirm.addEventListener('click', async () => {
    const { file, options } = body.__collect();
    if (!file) {
      toast(t('upload.needFile'), 'error');
      return;
    }
    const form = new FormData();
    form.append('file', file);
    Object.entries(options).forEach(([key, value]) => {
      if (value !== '' && value !== null && value !== undefined) form.append(key, value);
    });
    setLoading(1);
    try {
      const response = await api.upload(form);
      const list = await api.datasets();
      state.datasets = list.datasets || [];
      renderDatasetSelect();
      closeModal();
      await selectDataset(response.dataset.id);
      toast(t('upload.success'), 'ok');
    } catch (err) {
      toast(`${t('upload.failed')}: ${err.message}`, 'error');
    } finally {
      setLoading(-1);
    }
  });
  const cancel = createEl('button', 'btn ghost', t('common.cancel'));
  cancel.type = 'button';
  cancel.addEventListener('click', closeModal);
  openModal({ title: t('upload.title'), body, foot: [cancel, confirm] });
}

async function openDatasetModal() {
  if (!state.dataset) return;
  const body = createEl('div');
  body.style.display = 'flex';
  body.style.flexDirection = 'column';
  body.style.gap = '12px';
  const card = createEl('div', 'dataset-card');
  card.appendChild(createEl('h4', null, localize(state.dataset.name)));
  card.appendChild(createEl('p', null, localize(state.dataset.description)));
  const meta = createEl('div', 'meta');
  meta.textContent = `${state.dataset.rows.toLocaleString()} ${t('dataset.rows')} × ${state.dataset.cols} ${t('dataset.cols')} · ${(state.dataset.size_bytes / 1024 / 1024).toFixed(2)} MB · ${state.dataset.source === 'builtin' ? t('dataset.builtin') : t('dataset.upload')}`;
  card.appendChild(meta);
  body.appendChild(card);

  const detail = await api.dataset(state.dataset.id);
  const columns = detail.dataset.columns || [];
  const tableWrap = createEl('div', 'table-wrap');
  renderSimpleTable(
    tableWrap,
    [
      { label: t('dataset.columns'), render: (row) => row.label },
      { label: t('profile.kind'), render: (row) => row.kind },
      { label: t('table.missing'), align: 'right', render: (row) => row.missing },
      { label: t('table.unique'), align: 'right', render: (row) => row.nunique },
      { label: t('chart.dataTitle'), render: (row) => row.samples },
    ],
    columns.map((col) => ({
      label: columnLabel(col, col.name),
      kind: col.kind,
      missing: col.missing,
      nunique: col.nunique,
      samples: (col.samples || []).join(', '),
    })),
  );
  body.appendChild(tableWrap);

  const foot = [];
  const close = createEl('button', 'btn ghost', t('common.close'));
  close.type = 'button';
  close.addEventListener('click', closeModal);
  foot.push(close);
  if (state.dataset.source === 'upload') {
    const remove = createEl('button', 'btn', t('dataset.remove'));
    remove.type = 'button';
    remove.addEventListener('click', async () => {
      await api.removeDataset(state.dataset.id);
      const list = await api.datasets();
      state.datasets = list.datasets || [];
      closeModal();
      const next = state.datasets[0];
      if (next) await selectDataset(next.id);
      toast(`${t('dataset.remove')} ✓`, 'ok');
    });
    foot.push(remove);
  }
  openModal({ title: t('dataset.overview'), body, foot });
}

/* --------------------------- 导出 --------------------------- */

async function doExport(kind) {
  try {
    const base = { dataset_id: state.datasetId, steps: state.steps };
    if (kind === 'csv') await api.exportData({ ...base, format: 'csv' });
    else if (kind === 'xlsx') await api.exportData({ ...base, format: 'xlsx' });
    else if (kind === 'script') await api.exportScript({ ...base, chart: payloadForChart() });
    else if (kind === 'report') await api.exportReport({ ...base, lang: getLang(), charts: [payloadForChart()] });
    toast(t('export.done'), 'ok');
  } catch (err) {
    toast(`${t('export.failed')}: ${err.message}`, 'error');
  }
}

/* --------------------------- 主题 / 语言 --------------------------- */

function setTheme(theme) {
  document.body.dataset.theme = theme;
  localStorage.setItem('pandaviz.theme', theme);
  dom.themeButton.textContent = theme === 'light' ? '☀' : '🌙';
  renderActiveTab();
}

function refreshLanguage() {
  applyStaticTranslations(document);
  renderDatasetSelect();
  if (state.dataset && state.dataset.source) renderStatus();
  if (state.pipeline) renderStepArea();
  renderActiveTab();
  toast(getLang() === 'zh' ? '语言已切换为中文' : 'Language switched to English', 'ok');
}

/* --------------------------- 初始化 --------------------------- */

function cacheDom() {
  dom.datasetSelect = $('dataset-select');
  dom.fileInput = $('file-input');
  dom.uploadButton = $('btn-upload');
  dom.datasetInfo = $('btn-dataset-info');
  dom.themeButton = $('btn-theme');
  dom.exportButton = $('btn-export');
  dom.exportMenu = $('export-menu');
  dom.exportDropdown = dom.exportButton.parentElement;
  dom.clearSteps = $('btn-clear-steps');
  dom.opPalette = $('op-palette');
  dom.stepList = $('step-list');
  dom.stepCount = $('step-count');
  dom.stepEmpty = $('step-empty');
  dom.funnelChart = $('funnel-chart');
  dom.stepPreviewWrap = $('step-preview');
  dom.chipShape = $('chip-shape');
  dom.chipDataset = $('chip-dataset');
  dom.chipPandas = $('chip-pandas');
  dom.chipSteps = $('chip-steps');
  dom.chipError = $('chip-error');
  dom.chipLatency = $('chip-latency');
  dom.toasts = $('toasts');
  dom.loading = $('loading');
  dom.backdrop = $('modal-backdrop');
  dom.modalTitle = $('modal-title');
  dom.modalBody = $('modal-body');
  dom.modalFoot = $('modal-foot');
  dom.tableSearch = $('table-search');
  dom.tableLimit = $('table-limit');
  dom.tablePrev = $('table-prev');
  dom.tableNext = $('table-next');
  dom.tableInfo = $('table-info');

  dom.chart = {
    controls: $('chart-controls'),
    chart: $('main-chart'),
    code: $('chart-code'),
    warnings: $('chart-warnings'),
    hints: $('chart-hints'),
    title: $('chart-title'),
  };
  dom.table = {
    table: $('data-table'),
    stats: $('column-stats'),
    info: dom.tableInfo,
  };
  dom.profile = {
    gauge: $('quality-gauge'),
    grade: $('quality-grade'),
    kpis: $('profile-kpis'),
    missingBar: $('missing-bar'),
    missingMatrix: $('missing-matrix'),
    sparkGrid: $('spark-grid'),
    columns: $('profile-columns'),
  };
  dom.relation = {
    method: $('corr-method'),
    view: $('relation-view'),
    chart: $('relation-chart'),
    pairs: $('corr-pairs'),
    code: $('corr-code'),
    info: $('corr-info'),
    hints: $('relation-hints'),
  };
  dom.pivotView = {
    controls: $('pivot-controls'),
    chart: $('pivot-chart'),
    code: $('pivot-code'),
    hints: $('pivot-hints'),
  };
  dom.ts = {
    controls: $('ts-controls'),
    chart: $('ts-chart'),
    code: $('ts-code'),
    trend: $('ts-trend'),
  };
  dom.statsPanel = {
    controls: $('stats-controls'),
    result: $('stats-result'),
    conclusion: $('stats-conclusion'),
    chart: $('stats-chart'),
    chartBox: $('stats-chart') ? $('stats-chart').closest('.card') : null,
    groups: $('stats-groups'),
    code: $('stats-code'),
  };
  dom.insights = {
    gauge: $('insight-gauge'),
    list: $('insight-list'),
  };
  dom.codePanel = {
    pipeline: $('code-pipeline'),
    script: $('code-script'),
  };
}

function bindEvents() {
  dom.datasetSelect.addEventListener('change', () => selectDataset(dom.datasetSelect.value));
  dom.uploadButton.addEventListener('click', openUploadModal);
  dom.datasetInfo.addEventListener('click', () => { openDatasetModal(); });
  dom.fileInput.addEventListener('change', () => {
    const file = dom.fileInput.files && dom.fileInput.files[0];
    if (!file) return;
    const modalOpen = !dom.backdrop.classList.contains('hidden');
    if (!modalOpen) openUploadModal();
    dom.pendingFile = file;
    const hint = dom.modalBody.querySelector('.dataset-card p.small');
    if (hint) hint.textContent = `${t('upload.selected')}: ${file.name}`;
  });

  dom.themeButton.addEventListener('click', () => {
    setTheme(document.body.dataset.theme === 'light' ? 'dark' : 'light');
  });

  dom.exportButton.addEventListener('click', (event) => {
    event.stopPropagation();
    dom.exportDropdown.classList.toggle('open');
  });
  document.addEventListener('click', () => dom.exportDropdown.classList.remove('open'));
  dom.exportMenu.addEventListener('click', (event) => {
    const target = event.target.closest('[data-export]');
    if (target) {
      dom.exportDropdown.classList.remove('open');
      doExport(target.dataset.export);
    }
  });

  dom.clearSteps.addEventListener('click', clearAllSteps);

  document.querySelectorAll('#lang-switch .seg-btn').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('#lang-switch .seg-btn').forEach((node) => node.classList.toggle('is-active', node === button));
      setLang(button.dataset.lang);
      refreshLanguage();
    });
  });

  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });

  dom.relation.method.addEventListener('change', () => {
    state.corr.method = dom.relation.method.value;
    refreshCorrOnly();
  });
  dom.relation.view.addEventListener('change', () => {
    state.relationView = dom.relation.view.value;
    writeHash();
    if (state.relationView === 'corr') renderActiveTab();
    else requestRelationChart();
  });

  dom.tableSearch.addEventListener('input', debounce(() => {
    state.table.search = dom.tableSearch.value;
    state.table.offset = 0;
    refreshTableOnly();
  }, 320));
  dom.tableLimit.addEventListener('change', () => {
    state.table.limit = Number(dom.tableLimit.value);
    state.table.offset = 0;
    refreshTableOnly();
  });
  dom.tablePrev.addEventListener('click', () => {
    state.table.offset = Math.max(0, state.table.offset - state.table.limit);
    refreshTableOnly();
  });
  dom.tableNext.addEventListener('click', () => {
    state.table.offset += state.table.limit;
    refreshTableOnly();
  });

  $('btn-chart-png').addEventListener('click', exportChartPng);
  $('btn-chart-refresh').addEventListener('click', () => runAnalysis({ chart: true, code: true }));
  $('btn-copy-pipeline').addEventListener('click', async () => {
    const ok = await copyText(dom.codePanel.pipeline.textContent);
    toast(ok ? t('code.copied') : t('common.error'), ok ? 'ok' : 'error');
  });
  $('btn-copy-script').addEventListener('click', async () => {
    const ok = await copyText(dom.codePanel.script.textContent);
    toast(ok ? t('code.copied') : t('common.error'), ok ? 'ok' : 'error');
  });

  $('modal-close').addEventListener('click', closeModal);
  dom.backdrop.addEventListener('click', (event) => {
    if (event.target === dom.backdrop) closeModal();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeModal();
  });
}

async function boot() {
  cacheDom();
  applyStaticTranslations(document);
  const savedTheme = localStorage.getItem('pandaviz.theme') || 'dark';
  setTheme(savedTheme);
  const activeLang = getLang();
  document.querySelectorAll('#lang-switch .seg-btn').forEach((node) => {
    node.classList.toggle('is-active', node.dataset.lang === activeLang);
  });

  const meta = await api.meta();
  state.meta = meta;
  state.datasets = meta.datasets || [];
  renderOpPalette(dom.opPalette, meta, addStep);
  renderDatasetSelect();

  const preferred = state.datasets.find((item) => item.id === 'sales') || state.datasets[0];
  if (preferred) {
    bindEvents();
    const hash = readHash();
    state.activeTab = hash.tab || 'chart';
    if (hash.tab === 'relation' && hash.sub && ['corr', 'matrix', 'parallel'].includes(hash.sub)) {
      state.relationView = hash.sub;
    }
    document.querySelectorAll('.tab').forEach((tab) => tab.classList.toggle('is-active', tab.dataset.tab === state.activeTab));
    document.querySelectorAll('.view').forEach((view) => view.classList.toggle('is-active', view.dataset.view === state.activeTab));
    await selectDataset(preferred.id);
    if (state.activeTab === 'relation' && state.relationView !== 'corr') requestRelationChart();
  }
}

boot().catch((err) => {
  console.error(err);
  toast(`${t('common.error')}: ${err.message}`, 'error');
});
