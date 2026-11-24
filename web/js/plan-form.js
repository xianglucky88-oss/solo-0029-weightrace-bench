import { request } from './api.js';
import { el, labelled } from './dom.js';
import { closeEditor, editorForm, openEditor } from './editor.js';
import { metricLabels } from './labels.js';

function input(name, label, type = 'text', attrs = {}) {
  return labelled(label, el('input', { name, type, required: true, ...attrs }));
}

function loadChoices(name, title, standards) {
  return el('fieldset', {}, el('legend', {}, title), standards.map((item, i) => el('label', { class: 'check' },
    el('input', { type: 'checkbox', name, value: i }), `${item.id} / ${item.revision} · ${item.nominal_mg} mg`)));
}

export async function showPlan(onCreated) {
  const standards = await request('standards');
  if (!standards.length) {
    openEditor('开测次', el('p', { class: 'placeholder' }, '无可引用的砝码凭据。'));
    return;
  }
  const baseMetrics = Object.entries(metricLabels).filter(([id]) => id !== 'increment');
  const incrementToggle = el('input', { type: 'checkbox', name: 'increment_check' });
  const incrementLimit = input('increment', metricLabels.increment, 'number', { min: 1, max: 1000000, value: 4 });
  incrementLimit.hidden = true;
  incrementToggle.addEventListener('change', () => { incrementLimit.hidden = !incrementToggle.checked; });
  openEditor('开测次', editorForm([
    el('div', { class: 'field-grid' }, input('id', '测次编号', 'text', { pattern: '[A-Za-z0-9][A-Za-z0-9_\\-]{0,47}' }),
      input('bench', '工位', 'text', { maxlength: 64 }), input('measured_on', '测次日', 'date'),
      input('resolution_mg', '分度值 mg', 'number', { min: 1, max: 100000, value: 1 })),
    el('div', { class: 'field-grid' }, loadChoices('low', '低档凭据', standards), loadChoices('high', '高档凭据', standards)),
    el('label', { class: 'check' }, incrementToggle, '启用升档增量检查（允许首次签出前换用高档附加砝码）'),
    el('fieldset', {}, el('legend', {}, '分项上限 mg'), el('div', { class: 'field-grid' },
      baseMetrics.map(([id, label]) => input(id, label, 'number', { min: 1, max: 1000000, value: 10 })),
      incrementLimit)),
  ], '锁定计划', async (form) => {
    const refs = (name) => form.getAll(name).map((index) => {
      const { id, revision } = standards[Number(index)];
      return { id, revision };
    });
    const incrementCheck = form.get('increment_check') === 'on';
    const metricEntries = incrementCheck ? [...baseMetrics, ['increment', metricLabels.increment]] : baseMetrics;
    const value = { id: form.get('id'), bench: form.get('bench'), measured_on: form.get('measured_on'),
      resolution_mg: Number(form.get('resolution_mg')),
      increment_check: incrementCheck,
      loads: { low: refs('low'), high: refs('high') },
      limits_mg: Object.fromEntries(metricEntries.map(([id]) => [id, Number(form.get(id))])) };
    await request('sessions', value);
    closeEditor();
    await onCreated(value.id);
  }));
}
