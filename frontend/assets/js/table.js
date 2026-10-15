/* ==========================================================================
   表格层：数据表 / 列统计 / 通用小表
   ========================================================================== */

import { t, columnLabel, valueLabel, getLang } from './i18n.js';
import { fmtNumber, fmtRate } from './charts.js';

const KIND_CLASS = {
  numeric: 'type-numeric',
  categorical: 'type-categorical',
  datetime: 'type-datetime',
  text: 'type-text',
  boolean: 'type-boolean',
};

const KIND_LABEL = {
  numeric: { zh: '数值', en: 'numeric' },
  categorical: { zh: '类别', en: 'categorical' },
  datetime: { zh: '时间', en: 'datetime' },
  text: { zh: '文本', en: 'text' },
  boolean: { zh: '布尔', en: 'boolean' },
};

export function kindLabel(kind) {
  const entry = KIND_LABEL[kind];
  if (!entry) return kind || '—';
  return getLang() === 'en' ? entry.en : entry.zh;
}

export function formatCell(value, kind, columnMeta) {
  if (value === null || value === undefined) return { text: '∅', missing: true };
  if (kind === 'datetime') {
    const text = String(value).replace('T', ' ').slice(0, 19);
    return { text };
  }
  if (kind === 'numeric') return { text: fmtNumber(value, 2), numeric: true };
  if (kind === 'boolean') return { text: value ? '✓' : '✗' };
  if (kind === 'categorical') {
    const localized = valueLabel(columnMeta, value);
    return { text: localized, title: localized !== String(value) ? `${localized} · ${value}` : undefined };
  }
  if (kind === 'text') {
    const text = String(value);
    return {
      text: text.length > 64 ? `${text.slice(0, 63)}…` : text,
      title: text.length > 64 ? text : undefined,
    };
  }
  return { text: String(value) };
}

function cellClass(kind) {
  if (kind === 'numeric') return 'num';
  if (kind === 'datetime') return 'num';
  return '';
}

/** 简单数据表：columns 为后端列描述（含 kind / label / value_labels） */
export function renderRows(container, columns, rows, options = {}) {
  container.innerHTML = '';
  const table = document.createElement('table');
  table.className = 'data';
  const thead = document.createElement('thead');
  const headRow = document.createElement('tr');
  if (!options.compact) {
    const indexCell = document.createElement('th');
    indexCell.textContent = '#';
    headRow.appendChild(indexCell);
  }
  (columns || []).forEach((col) => {
    const cell = document.createElement('th');
    if (options.onSort) {
      const active = options.sortBy === col.name;
      cell.textContent = `${columnLabel(col, col.name)} ${active ? (options.sortDir === 'desc' ? '▾' : '▴') : ''}`;
      cell.addEventListener('click', () => options.onSort(col.name));
    } else {
      cell.textContent = columnLabel(col, col.name);
    }
    if (!options.compact) {
      const sub = document.createElement('span');
      sub.className = 'sub';
      sub.textContent = `${kindLabel(col.kind)}${col.missing ? ` · ∅${col.missing}` : ''}`;
      cell.appendChild(sub);
    }
    headRow.appendChild(cell);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  (rows || []).forEach((row, rowIndex) => {
    const tr = document.createElement('tr');
    if (!options.compact) {
      const indexCell = document.createElement('td');
      indexCell.className = 'idx';
      indexCell.textContent = String((options.offset || 0) + rowIndex + 1);
      tr.appendChild(indexCell);
    }
    (columns || []).forEach((col) => {
      const td = document.createElement('td');
      const formatted = formatCell(row[col.name], col.kind, col);
      td.textContent = formatted.text;
      if (formatted.numeric) td.classList.add('num');
      else if (cellClass(col.kind)) td.classList.add(cellClass(col.kind));
      if (formatted.missing) td.classList.add('missing');
      if (formatted.title) td.title = formatted.title;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.appendChild(table);
  return table;
}

/** 通用小表：headerDefs = [{label, align, render}] */
export function renderSimpleTable(container, headerDefs, rows, options = {}) {
  container.innerHTML = '';
  const table = document.createElement('table');
  table.className = 'data';
  const thead = document.createElement('thead');
  const headRow = document.createElement('tr');
  headerDefs.forEach((def) => {
    const th = document.createElement('th');
    th.textContent = def.label;
    if (def.align === 'right') th.style.textAlign = 'right';
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  rows.forEach((row, rowIndex) => {
    const tr = document.createElement('tr');
    if (options.onRowClick) {
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', () => options.onRowClick(row, rowIndex));
    }
    headerDefs.forEach((def) => {
      const td = document.createElement('td');
      const value = def.render ? def.render(row) : row[def.key];
      if (value instanceof Node) td.appendChild(value);
      else td.textContent = value === null || value === undefined ? '—' : String(value);
      if (def.align === 'right') td.style.textAlign = 'right';
      if (def.className) td.className = def.className;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.appendChild(table);
  return table;
}

/** 列统计表（Tabular describe） */
export function renderColumnStats(container, stats, columns) {
  const metaByName = new Map((columns || []).map((col) => [col.name, col]));
  const headerDefs = [
    { label: t('table.columns'), render: (row) => columnLabel(metaByName.get(row.name), row.name) },
    { label: t('table.type'), render: (row) => kindLabel(row.kind) },
    { label: t('table.missing'), align: 'right', render: (row) => `${row.missing} (${fmtRate(row.missing_rate)})` },
    { label: t('table.unique'), align: 'right', render: (row) => fmtNumber(row.nunique) },
    { label: t('table.min'), align: 'right', render: (row) => (row.min === undefined ? '—' : fmtNumber(row.min)) },
    { label: t('table.median'), align: 'right', render: (row) => (row.median === undefined ? '—' : fmtNumber(row.median)) },
    { label: t('table.mean'), align: 'right', render: (row) => (row.mean === undefined ? '—' : fmtNumber(row.mean)) },
    { label: t('table.max'), align: 'right', render: (row) => (row.max === undefined ? '—' : fmtNumber(row.max)) },
    { label: t('table.std'), align: 'right', render: (row) => (row.std === undefined ? '—' : fmtNumber(row.std)) },
    { label: t('table.sum'), align: 'right', render: (row) => (row.sum === undefined ? '—' : fmtNumber(row.sum)) },
  ];
  return renderSimpleTable(container, headerDefs, stats || []);
}
