import { request } from './api.js';
import { el, labelled, table } from './dom.js';
import { editorForm, openEditor } from './editor.js';
import { metricLabels, mono } from './labels.js';

const fields = [
  ['id', '公告编号', 'text'],
  ['effective_from', '适用测次（含）', 'date'],
  ['effective_until', '适用截止（不含）', 'date'],
];

export async function showBulletins() {
  const bulletins = await request('bulletins');
  const metrics = Object.entries(metricLabels);
  const register = el('details', { open: !bulletins.length }, el('summary', {}, '登记公告'),
    editorForm(el('div', { class: 'field-grid' },
      ...fields.map(([name, label, type]) => labelled(label, el('input', { name, type, required: true }))),
      el('fieldset', {}, el('legend', {}, '分项上限 mg'), el('div', { class: 'field-grid' },
        metrics.map(([id, label]) => labelled(label, el('input', {
          name: id, type: 'number', required: true, min: 1, max: 1000000, value: 10,
        })))))),
    '登记公告', async (form) => {
      const value = {
        id: form.get('id'), effective_from: form.get('effective_from'), effective_until: form.get('effective_until'),
        limits_mg: Object.fromEntries(metrics.map(([id]) => [id, Number(form.get(id))])),
      };
      await request('bulletins', value);
      await showBulletins();
    }));
  openEditor('限值公告', el('p', { class: 'placeholder' },
      '公告只按测次日适用；同编号重送相同内容幂等，换内容拒绝。'),
    el('div', { class: 'table-wrap' }, table(['编号', '适用测次范围', '分项上限 mg'],
      bulletins.map((x) => [mono(x.id), `${x.effective_from} 至 ${x.effective_until}`,
        mono(metrics.map(([id, label]) => `${label} ${x.limits_mg[id]}`).join(' · '))]), '尚无公告')),
    register);
}
