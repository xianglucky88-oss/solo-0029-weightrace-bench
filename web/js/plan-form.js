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

function scaleRows(scales) {
  return el('div', { class: 'scale-rows' }, scales.map((scale, i) => el('div', { class: 'field-grid' },
    labelled('分度档编号', el('input', { name: 'scale_id', required: true, pattern: '[A-Za-z0-9][A-Za-z0-9_\\-]{0,47}', value: scale?.id ?? '' })),
    labelled('每格毫克数', el('input', { name: 'scale_grid', type: 'number', min: 1, max: 100000, required: true, value: scale?.grid_mg ?? '' })),
    el('button', { type: 'button', class: 'quiet', onclick: () => { scales.splice(i, 1); refresh(); } }, '移除档位'))));
}

export async function showPlan(onCreated) {
  const standards = await request('standards');
  if (!standards.length) {
    openEditor('开测次', el('p', { class: 'placeholder' }, '无可引用的砝码凭据。'));
    return;
  }
  const metrics = Object.entries(metricLabels);
  const modeHolder = el('div');
  const multi = { on: true };
  const scales = [{ id: 'G1', grid_mg: 1 }];
  function refresh() {
    modeHolder.replaceChildren(multi.on
      ? el('fieldset', {}, el('legend', {}, '开测锁定分度档（每档每格毫克数）'), scaleRows(scales),
          el('button', { type: 'button', class: 'quiet', onclick: () => { scales.push({ id: '', grid_mg: 1 }); refresh(); } }, '增加分度档'))
      : input('resolution_mg', '单分度值 mg', 'number', { min: 1, max: 100000, value: 1 }));
  }
  refresh();
  openEditor('开测次', editorForm([
    el('div', { class: 'field-grid', role: 'group' },
      el('label', { class: 'check' }, el('input', { type: 'radio', name: 'plan_mode', value: 'multi', checked: true,
        onchange: () => { multi.on = true; refresh(); } }), '多分度档（原始整数格数）'),
      el('label', { class: 'check' }, el('input', { type: 'radio', name: 'plan_mode', value: 'single',
        onchange: () => { multi.on = false; refresh(); } }), '旧版单分度（毫克示值）')),
    el('div', { class: 'field-grid' }, input('id', '测次编号', 'text', { pattern: '[A-Za-z0-9][A-Za-z0-9_\\-]{0,47}' }),
      input('bench', '工位', 'text', { maxlength: 64 }), input('measured_on', '测次日', 'date')),
    modeHolder,
    el('div', { class: 'field-grid' }, loadChoices('low', '低档凭据', standards), loadChoices('high', '高档凭据', standards)),
    el('fieldset', {}, el('legend', {}, '分项上限 mg'), el('div', { class: 'field-grid' }, metrics.map(([id, label]) =>
      input(id, label, 'number', { min: 1, max: 1000000, value: 10 })))),
  ], '锁定计划', async (form) => {
    const refs = (name) => form.getAll(name).map((index) => {
      const { id, revision } = standards[Number(index)];
      return { id, revision };
    });
    const value = { id: form.get('id'), bench: form.get('bench'), measured_on: form.get('measured_on'),
      loads: { low: refs('low'), high: refs('high') },
      limits_mg: Object.fromEntries(metrics.map(([id]) => [id, Number(form.get(id))])) };
    if (multi.on) {
      value.scales = form.getAll('scale_id').map((id, i) => ({ id, grid_mg: Number(form.getAll('scale_grid')[i]) }));
      if (!value.scales.length) throw new Error('至少锁定一个分度档。');
    } else {
      value.resolution_mg = Number(form.get('resolution_mg'));
    }
    await request('sessions', value);
    closeEditor();
    await onCreated(value.id);
  }));
}
