/* ==========================================================================
   管道编辑器：算子库、步骤卡片、参数表单、数据量漏斗、步骤预览
   ========================================================================== */

import { t, localize, columnLabel } from './i18n.js';
import { renderChart, funnelStepsOption, fmtNumber } from './charts.js';
import { renderRows } from './table.js';

const openSteps = new Set();

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

/* ------------------------------ 算子库 ------------------------------ */

export function renderOpPalette(container, meta, onAdd) {
  container.innerHTML = '';
  const groups = (meta.op_groups || []).map((group) => ({
    ...group,
    ops: (meta.ops || []).filter((op) => op.group === group.id),
  }));
  groups.forEach((group, index) => {
    const wrap = el('div', `op-group${index < 2 ? ' open' : ''}`);
    const head = el('button', 'op-group-head');
    head.type = 'button';
    head.innerHTML = `<span>${localize(group.label)}</span><span class="muted small">${group.ops.length}</span>`;
    head.addEventListener('click', () => wrap.classList.toggle('open'));
    const body = el('div', 'op-group-body');
    group.ops.forEach((op) => {
      const chip = el('button', 'op-chip', localize(op.label));
      chip.type = 'button';
      chip.title = `${localize(op.hint)}\n${op.id}`;
      chip.addEventListener('click', () => onAdd(op));
      body.appendChild(chip);
    });
    wrap.appendChild(head);
    wrap.appendChild(body);
    container.appendChild(wrap);
  });
}

/* ------------------------------ 参数表单 ------------------------------ */

function optionListFor(param, ctx) {
  if (param.type === 'column' || param.type === 'columns') {
    const kinds = param.kinds;
    return (ctx.columns || []).filter((col) => !kinds || kinds.includes(col.kind));
  }
  return [];
}

function selectControl(options, value, { emptyLabel, onChange } = {}) {
  const select = el('select', 'control');
  if (emptyLabel !== undefined) {
    const opt = el('option', null, emptyLabel);
    opt.value = '';
    select.appendChild(opt);
  }
  options.forEach((opt) => {
    const node = el('option', null, opt.label);
    node.value = opt.value === null || opt.value === undefined ? '' : String(opt.value);
    select.appendChild(node);
  });
  select.value = value === null || value === undefined ? '' : String(value);
  if (onChange) select.addEventListener('change', () => onChange(select.value));
  return select;
}

function readValue(select) {
  return select.value === '' ? null : select.value;
}

/** 换列之后把「值」同步成新列的参考值：区间条件用 min~max，比较条件用中位数 */
function autoAdjustValue(op, values, ctx) {
  if (op.id !== 'filter_row') return;
  const stats = (ctx.stats || []).find((item) => item.name === values.column);
  if (!stats) return;
  if (values.operator === 'between') {
    if (stats.min !== null && stats.min !== undefined) values.value = stats.min;
    if (stats.max !== null && stats.max !== undefined) values.value2 = stats.max;
    return;
  }
  if (values.operator === 'isna' || values.operator === 'notna') return;
  const reference = stats.median !== null && stats.median !== undefined ? stats.median : stats.mean;
  if (reference !== null && reference !== undefined) values.value = reference;
}

/** 构造一个算子的参数表单；返回 {element, getValues, rerender} */
export function buildParamForm(op, initial, ctx, onChange) {
  const wrapper = el('div');
  wrapper.style.display = 'flex';
  wrapper.style.flexDirection = 'column';
  wrapper.style.gap = '9px';
  const values = { ...(initial || {}) };
  const rerender = () => {
    wrapper.innerHTML = '';
    (op.params || []).forEach((param) => {
      const visible = !param.depends || Object.entries(param.depends).every(([key, allowed]) => allowed.includes(values[key]));
      const falseHidden = (param.false_ops || []).includes(values.operator);
      // ops：只有列出的运算符才需要这个参数（例如「值2」只在“区间范围内”时需要）
      const opsBlocked = Array.isArray(param.ops) && !param.ops.includes(values.operator);
      if (!visible || falseHidden || opsBlocked) return;

      const row = el('div', 'param-row');
      row.appendChild(el('label', null, localize(param.label)));

      if (param.type === 'column') {
        const options = optionListFor(param, ctx).map((col) => ({ value: col.name, label: columnLabel(col, col.name) }));
        const select = selectControl(options, values[param.name], {
          emptyLabel: param.allow_empty ? t('common.none') : '—',
          onChange: (value) => {
            values[param.name] = readValue(select);
            autoAdjustValue(op, values, ctx); // 换列后把“值”同步成新列的参考值（中位数等）
            onChange && onChange(values);
            rerender();
          },
        });
        row.appendChild(select);
      } else if (param.type === 'columns') {
        const options = optionListFor(param, ctx);
        const chips = el('div', 'param-multi');
        const current = new Set(values[param.name] || []);
        options.forEach((col) => {
          const label = el('label');
          const box = document.createElement('input');
          box.type = 'checkbox';
          box.checked = current.has(col.name);
          box.addEventListener('change', () => {
            if (box.checked) current.add(col.name);
            else current.delete(col.name);
            values[param.name] = Array.from(current);
            onChange && onChange(values);
          });
          label.appendChild(box);
          label.appendChild(document.createTextNode(columnLabel(col, col.name)));
          chips.appendChild(label);
        });
        row.appendChild(chips);
      } else if (param.type === 'select') {
        const options = (param.options || []).map((opt) => ({
          value: opt.value,
          label: opt.label ? localize(opt.label) : String(opt.value),
        }));
        const select = selectControl(options, values[param.name] !== undefined ? values[param.name] : param.default, {
          emptyLabel: param.allow_empty ? t('common.none') : undefined,
          onChange: (value) => {
            values[param.name] = value === 'true' ? true : value === 'false' ? false : readValue(select);
            onChange && onChange(values);
            rerender();
          },
        });
        row.appendChild(select);
      } else if (param.type === 'multi_select') {
        const chips = el('div', 'param-multi');
        const current = new Set(values[param.name] || param.default || []);
        (param.options || []).forEach((opt) => {
          const label = el('label');
          const box = document.createElement('input');
          box.type = 'checkbox';
          box.checked = current.has(opt.value);
          box.addEventListener('change', () => {
            if (box.checked) current.add(opt.value);
            else current.delete(opt.value);
            values[param.name] = Array.from(current);
            onChange && onChange(values);
          });
          label.appendChild(box);
          label.appendChild(document.createTextNode(localize(opt.label)));
          chips.appendChild(label);
        });
        row.appendChild(chips);
      } else if (param.type === 'number') {
        const input = el('input', 'control');
        input.type = 'number';
        if (param.min !== undefined) input.min = param.min;
        input.value = values[param.name] !== undefined ? values[param.name] : (param.default !== undefined ? param.default : '');
        input.addEventListener('input', () => {
          values[param.name] = input.value === '' ? null : Number(input.value);
          onChange && onChange(values);
        });
        row.appendChild(input);
      } else if (param.type === 'bool') {
        const label = el('label');
        label.style.display = 'flex';
        label.style.alignItems = 'center';
        label.style.gap = '6px';
        label.style.fontSize = '.74rem';
        const box = document.createElement('input');
        box.type = 'checkbox';
        box.checked = Boolean(values[param.name] !== undefined ? values[param.name] : param.default);
        box.addEventListener('change', () => {
          values[param.name] = box.checked;
          onChange && onChange(values);
        });
        label.appendChild(box);
        label.appendChild(document.createTextNode(localize(param.label)));
        row.innerHTML = '';
        row.appendChild(label);
      } else if (param.type === 'textarea') {
        const area = el('textarea', 'control');
        area.rows = 2;
        area.style.minHeight = '54px';
        area.style.fontFamily = 'var(--mono)';
        if (param.placeholder) area.placeholder = param.placeholder;
        area.value = values[param.name] !== undefined ? values[param.name] : (param.default || '');
        area.addEventListener('input', () => {
          values[param.name] = area.value;
          onChange && onChange(values);
        });
        row.appendChild(area);
      } else if (param.type === 'dataset') {
        const options = (ctx.datasets || [])
          .filter((item) => item.id !== ctx.currentDatasetId)
          .map((item) => ({ value: item.id, label: `${localize(item.name)}\u00a0(${item.rows}×${item.cols})` }));
        const select = selectControl(options, values[param.name], {
          emptyLabel: t('common.none'),
          onChange: (value) => {
            values[param.name] = readValue(select);
            onChange && onChange(values);
            rerender();
          },
        });
        row.appendChild(select);
      } else if (param.type === 'agg_list') {
        const list = el('div');
        list.style.display = 'flex';
        list.style.flexDirection = 'column';
        list.style.gap = '6px';
        const aggs = Array.isArray(values[param.name]) && values[param.name].length
          ? values[param.name]
          : [{ column: (ctx.columns.find((c) => c.kind === 'numeric') || ctx.columns[0] || {}).name, how: 'sum', new_name: '' }];
        values[param.name] = aggs;
        const redraw = () => {
          list.innerHTML = '';
          aggs.forEach((item, index) => {
            const line = el('div', 'agg-item');
            const colOptions = (ctx.columns || []).map((col) => ({ value: col.name, label: columnLabel(col, col.name) }));
            line.appendChild(selectControl(colOptions, item.column, {
              onChange: (value) => { item.column = value; onChange && onChange(values); },
            }));
            line.appendChild(selectControl((ctx.aggs || []).map((agg) => ({ value: agg.value, label: localize(agg.label) })), item.how, {
              onChange: (value) => { item.how = value; onChange && onChange(values); },
            }));
            const alias = el('input', 'control');
            alias.placeholder = t('common.none');
            alias.value = item.new_name || '';
            alias.addEventListener('input', () => { item.new_name = alias.value; onChange && onChange(values); });
            line.appendChild(alias);
            const remove = el('button', 'btn tiny ghost', '✕');
            remove.type = 'button';
            remove.addEventListener('click', () => {
              aggs.splice(index, 1);
              values[param.name] = aggs;
              onChange && onChange(values);
              redraw();
            });
            line.appendChild(remove);
            list.appendChild(line);
          });
          const add = el('button', 'btn tiny ghost', '＋');
          add.type = 'button';
          add.addEventListener('click', () => {
            aggs.push({ column: (ctx.columns.find((c) => c.kind === 'numeric') || {}).name, how: 'sum', new_name: '' });
            values[param.name] = aggs;
            onChange && onChange(values);
            redraw();
          });
          list.appendChild(add);
        };
        redraw();
        row.appendChild(list);
      } else {
        const input = el('input', 'control');
        if (param.placeholder) input.placeholder = param.placeholder;
        input.value = values[param.name] !== undefined && values[param.name] !== null ? values[param.name] : (param.default || '');
        input.addEventListener('input', () => {
          values[param.name] = input.value;
          onChange && onChange(values);
        });
        row.appendChild(input);
      }
      wrapper.appendChild(row);
    });
  };
  rerender();
  return { element: wrapper, getValues: () => ({ ...values }), rerender };
}

/** 为算子生成一份默认参数（新增步骤时使用） */
export function defaultParamsFor(op, ctx) {
  const defaults = {};
  const numeric = (ctx.columns || []).filter((col) => col.kind === 'numeric');
  const categorical = (ctx.columns || []).filter((col) => col.kind === 'categorical' || col.kind === 'boolean');
  const datetimes = (ctx.columns || []).filter((col) => col.kind === 'datetime');
  // 优先挑“金额/指标类”的数值列作为默认聚合对象（销售额、AQI、GDP…），而不是数量或编号
  const METRIC_HINT = /(销售额|金额|总额|收入|营收|利润|revenue|sales|amount|profit|aqi|gdp|value|ratio)/i;
  const COUNT_HINT = /(数量|个数|次数|件数|id|编号|序号|code)/i;
  const metricColumn = numeric.find((col) => METRIC_HINT.test(col.name))
    || numeric.find((col) => !COUNT_HINT.test(col.name))
    || numeric[0]
    || null;

  (op.params || []).forEach((param) => {
    if (param.default !== undefined) defaults[param.name] = param.default;
    if (param.type === 'column') {
      const pool = param.kinds
        ? (ctx.columns || []).filter((col) => param.kinds.includes(col.kind))
        : (param.name === 'values' || param.name === 'value' ? numeric : numeric.concat(categorical));
      defaults[param.name] = pool.length ? pool[0].name : null;
      if (param.name === 'date_column' || (op.id === 'extract_datetime' && param.name === 'column')) {
        defaults[param.name] = datetimes.length ? datetimes[0].name : null;
      }
    } else if (param.type === 'columns') {
      if (param.allow_empty) defaults[param.name] = [];
      else {
        let pool = param.kinds ? (ctx.columns || []).filter((c) => param.kinds.includes(c.kind)) : numeric.concat(categorical);
        // 分组聚合默认按“类别列”分组（区域、品类…），比按数值列分组更符合直觉
        if (op.id === 'groupby_agg' && param.name === 'by') pool = categorical.concat(numeric);
        defaults[param.name] = pool.slice(0, 2).map((col) => col.name);
      }
    } else if (param.type === 'agg_list') {
      defaults[param.name] = [{
        column: metricColumn ? metricColumn.name : (ctx.columns[0] || {}).name,
        how: op.id === 'resample' ? 'mean' : 'sum',
        new_name: '',
      }];
    } else if (param.type === 'multi_select') {
      defaults[param.name] = param.default || (param.options || []).slice(0, 2).map((opt) => opt.value);
    } else if (param.type === 'dataset') {
      const other = (ctx.datasets || []).find((item) => item.id !== ctx.currentDatasetId);
      defaults[param.name] = other ? other.id : null;
    } else if (param.type === 'tags') {
      defaults[param.name] = [];
    } else if (param.type === 'text' && defaults[param.name] === undefined) {
      defaults[param.name] = '';
    }
  });
  if (op.id === 'pivot_table' || op.id === 'crosstab') {
    const pool = categorical.concat(numeric);
    defaults.index = pool[0] ? pool[0].name : null;
    if (op.id === 'pivot_table') {
      defaults.index = pool[0] ? [pool[0].name] : [];
      defaults.columns = pool[1] ? pool[1].name : null;
      defaults.values = numeric[0] ? numeric[0].name : null;
    } else {
      defaults.columns = pool[1] ? pool[1].name : null;
      defaults.values = null;
    }
  }
  return defaults;
}

/* ------------------------------ 步骤列表 ------------------------------ */

export function renderStepList(container, ctx, handlers) {
  const { steps, pipeline } = ctx;
  container.innerHTML = '';
  (steps || []).forEach((step, index) => {
    const info = (pipeline && pipeline.steps || []).find((item) => item.index === index) || {};
    const op = (ctx.ops || []).find((item) => item.id === step.type) || { label: { zh: step.type, en: step.type }, params: [] };
    const card = el('div', 'step-card');
    if (info.status === 'error') card.classList.add('is-error');
    if (step.enabled === false) card.classList.add('is-disabled');
    if (openSteps.has(index)) card.classList.add('open');

    const head = el('div', 'step-head');
    head.appendChild(el('span', 'step-index', String(index + 1)));
    head.appendChild(el('span', 'step-name', localize(op.label)));

    const delta = info.rows_delta || 0;
    // 上一步失败后，pandas 管道就不再往下执行，这些步骤后端没有返回信息
    const notRun = !info.status && Boolean(pipeline && pipeline.error && index > pipeline.error.step);
    const deltaNode = el('span', `step-delta ${!notRun && delta < 0 ? 'minus' : !notRun && delta > 0 ? 'plus' : 'zero'}`);
    deltaNode.textContent = notRun ? t('pipeline.notRun') : `${delta > 0 ? '+' : ''}${delta.toLocaleString()}`;
    deltaNode.title = notRun
      ? t('pipeline.notRunHint')
      : `${info.rows === undefined ? '?' : info.rows} ${t('common.rows')}`;
    head.appendChild(deltaNode);

    const actions = el('div', 'step-actions');
    const mkAction = (label, title, fn) => {
      const button = el('button', null, label);
      button.type = 'button';
      button.title = title;
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        fn();
      });
      return button;
    };
    actions.appendChild(mkAction(step.enabled === false ? '▶' : '⏸', t('pipeline.toggle'), () => handlers.onToggle(index)));
    actions.appendChild(mkAction('↑', t('pipeline.up'), () => handlers.onMove(index, -1)));
    actions.appendChild(mkAction('↓', t('pipeline.down'), () => handlers.onMove(index, 1)));
    actions.appendChild(mkAction('✕', t('pipeline.remove'), () => handlers.onRemove(index)));
    head.appendChild(actions);
    card.appendChild(head);

    const code = el('div', 'step-code', info.code || '');
    card.appendChild(code);
    if (info.error) card.appendChild(el('div', 'step-error', info.error));

    head.style.cursor = 'pointer';
    head.addEventListener('click', () => {
      if (openSteps.has(index)) openSteps.delete(index);
      else openSteps.add(index);
      card.classList.toggle('open');
      if (card.classList.contains('open')) handlers.onPreview(index);
    });

    const body = el('div', 'step-body');
    const stepColumns = typeof ctx.columnsForStep === 'function' ? ctx.columnsForStep(index) : ctx.columns;
    const form = buildParamForm(op, step.params || {}, {
      columns: stepColumns,
      datasets: ctx.datasets,
      aggs: ctx.aggs,
      currentDatasetId: ctx.currentDatasetId,
      stats: ctx.stats,
    }, () => {});
    body.appendChild(form.element);
    const rowActions = el('div', 'param-actions');
    const apply = el('button', 'btn tiny primary', t('pipeline.applyParams'));
    apply.type = 'button';
    apply.addEventListener('click', () => handlers.onUpdateParams(index, form.getValues()));
    const remove = el('button', 'btn tiny ghost', t('pipeline.remove'));
    remove.type = 'button';
    remove.addEventListener('click', () => handlers.onRemove(index));
    rowActions.appendChild(remove);
    rowActions.appendChild(apply);
    body.appendChild(rowActions);

    if (ctx.previewIndex === index && ctx.preview) {
      body.appendChild(el('div', 'small muted', t('pipeline.previewHint')));
      const wrap = el('div', 'mini-table-wrap');
      renderRows(wrap, ctx.preview.columns, ctx.preview.rows, { compact: true });
      body.appendChild(wrap);
    }
    card.appendChild(body);
    container.appendChild(card);
  });
}

/* ------------------------------ 漏斗图 ------------------------------ */

export function renderFunnel(el2, steps, initialRows) {
  renderChart(el2, funnelStepsOption(steps, initialRows));
  const note = document.getElementById('funnel-note');
  if (note) {
    const last = steps && steps.length ? steps[steps.length - 1].rows : initialRows;
    note.textContent = `${t('table.source')} ${fmtNumber(initialRows)} → ${t('table.output')} ${fmtNumber(last)} ${t('common.rows')}`;
  }
}

export function openOnlyStep(index) {
  openSteps.clear();
  if (typeof index === 'number') openSteps.add(index);
}

export function resetStepOpenState() {
  openSteps.clear();
}
