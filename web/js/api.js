const root = '/weightrace/api/';

export function sessionPath(key, suffix = '') {
  return `sessions/${encodeURIComponent(key)}${suffix}`;
}

export function fileUrl(key, number) {
  return root + sessionPath(key, `/releases/${number}/file`);
}

export async function request(path, value, { raw = false } = {}) {
  const response = await fetch(root + path, value === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: raw ? value : JSON.stringify(value),
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.message || '请求失败');
    error.code = data.error;
    error.details = data.details;
    throw error;
  }
  return data;
}
