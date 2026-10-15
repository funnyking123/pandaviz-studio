/* ==========================================================================
   后端 API 封装：所有数据都来自真实 pandas 计算
   ========================================================================== */

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch (err) {
    throw new Error(`Invalid JSON from ${path}: ${text.slice(0, 160)}`);
  }
  if (!response.ok || (payload && payload.ok === false && payload.error && !payload.pipeline)) {
    const message = (payload && payload.error) || `${response.status} ${response.statusText}`;
    const error = new Error(typeof message === 'string' ? message : JSON.stringify(message));
    error.payload = payload;
    throw error;
  }
  return payload;
}

function postJson(path, body) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

async function download(path, body, fallbackName) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      if (payload && payload.error) message = payload.error;
    } catch (err) { /* 保持原始错误信息 */ }
    throw new Error(message);
  }
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = match ? match[1] : (fallbackName || 'pandaviz-export');
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export const api = {
  meta: () => request('/api/meta'),
  datasets: () => request('/api/datasets'),
  dataset: (id) => request(`/api/datasets/${encodeURIComponent(id)}`),
  removeDataset: (id) => request(`/api/datasets/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  upload(formData) {
    return request('/api/datasets/upload', { method: 'POST', body: formData });
  },
  analyze: (payload) => postJson('/api/analyze', payload),
  exportData: (payload, name) => download('/api/export/data', payload, name),
  exportScript: (payload, name) => download('/api/export/script', { ...payload, download: true }, name),
  exportReport: (payload, name) => download('/api/export/report', { ...payload, download: true }, name),
  scriptText: (payload) => postJson('/api/export/script', payload),
  reportText: (payload) => postJson('/api/export/report', payload),
};
