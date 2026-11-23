import { request } from './api.js';
import { el, labelled, table } from './dom.js';
import { editorForm, openEditor } from './editor.js';
import { mono } from './labels.js';

const fields = [
  ['id', '砝码编号', 'text'], ['revision', '修订号', 'number', 1], ['nominal_mg', '标称质量 mg', 'number', 1],
  ['correction_mg', '修正量 mg', 'number'], ['radius_mg', '不确定半径 mg', 'number', 0],
  ['valid_from', '起效日（含）', 'date'], ['valid_until', '到期日（不含）', 'date'],
];

export async function showCatalog() {
  const standards = await request('standards');
  openEditor('砝码凭据', el('div', { class: 'table-wrap' }, table(['编号 / 修订', '标称 mg', '修正 mg', '半径 mg', '有效区间'],
    standards.map((x) => [mono(`${x.id} / ${x.revision}`), x.nominal_mg, x.correction_mg, x.radius_mg, `${x.valid_from} 至 ${x.valid_until}`]))),
  el('details', { open: !standards.length }, el('summary', {}, '登记凭据'), editorForm(el('div', { class: 'field-grid' },
    fields.map(([name, label, type, min]) => labelled(label, el('input', { name, type, required: true, ...(min === undefined ? {} : { min }) })))),
  '登记', async (form) => {
    await request('standards', Object.fromEntries(fields.map(([name, , type]) => [name, type === 'number' ? Number(form.get(name)) : form.get(name)])));
    await showCatalog();
  })));
}
