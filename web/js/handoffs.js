import { request, sessionPath } from './api.js';
import { $, button, el, labelled, table } from './dom.js';
import { closeEditor, editorForm, openEditor } from './editor.js';
import { badge, mg, mono } from './labels.js';

const riseKeys = ['zero_in', 'rise_low', 'rise_high', 'zero_mid_before'];
const riseLabels = { zero_in: '首空盘', rise_low: '升程 · 低档', rise_high: '升程 · 高档', zero_mid_before: '清零前空盘' };
const statusLabels = { valid: '有效', invalid: '已失效' };
const reasonLabels = {
  step_ambiguous: '本段出现多条有效候选', reading_excluded: '交接读数已被剔除',
  reading_changed: '本段读数已改变', order_changed: '本段时序已改变',
  reviewer_invalidated: '复核员声明失效', handoff_superseded: '已被新的交接取代', plan_changed: '计划已改变',
};

function statusBadge(status) {
  return el('span', { class: `badge ${status.valid ? 'released' : 'withdrawn'}` }, statusLabels[status.valid ? 'valid' : 'invalid']);
}

function handoffView(record) {
  const { document, status } = record;
  const rise = ['rise_low', 'rise_high'].map((key) => [riseLabels[key], mono(document.readings[key]),
    mono(`${mg(document.rise[key].error)} mg`), badge(document.rise[key].judgement.outcome)]);
  return el('section', { class: 'handoff' },
    el('div', { class: 'section-head' }, el('h3', {}, `交接 v${record.number} · ${document.reviewer}`), statusBadge(status)),
    el('p', { class: 'muted' }, `${document.confirmed_at} · ${record.caveat}`),
    el('div', { class: 'table-wrap' }, table(['升程检查', '读数', '修正后误差', '本段判定'], rise)),
    el('p', {}, '空盘依据：',
      ...riseKeys.filter((key) => key.startsWith('zero') || key === 'zero_mid_before').map((key) =>
        el('span', { class: 'mono' }, `${riseLabels[key]} ${document.pans[key]?.id ?? document.readings[key]} · ${document.pans[key]?.indicated_mg ?? ''} mg  `))),
    status.valid ? null : el('p', { class: 'issues' }, `失效：${reasonLabels[status.reason] ?? status.reason}（${status.invalidated_at ?? ''}）`));
}

function confirmHandoff(id, generation, workbench, onSaved) {
  const candidates = workbench.result.steps.filter((step) => riseKeys.includes(step.id));
  const chosen = Object.fromEntries(candidates.map((step) => [step.id, step.selected]));
  const fields = [
    labelled('交接复核员', el('input', { name: 'reviewer', required: true, maxlength: 64 })),
    ...riseKeys.map((key) => labelled(`${riseLabels[key]} 读数`, el('input', {
      name: key, required: true, value: chosen[key] ?? '',
    }))),
  ];
  openEditor('确认并交接升程证据', el('p', {}, '只确认本段升程证据；不代表示值分项通过，也不等于整场签出。'),
    editorForm(el('div', { class: 'field-grid' }, fields), '确认交接', async (form) => {
      const value = { generation, reviewer: form.get('reviewer') };
      for (const key of riseKeys) value[key] = form.get(key);
      await request(sessionPath(id, '/handoffs'), value);
      closeEditor();
      await onSaved('升程证据已确认并交接。');
    }));
}

export function renderHandoffs(id, generation, workbench, onSaved) {
  const { plan, result, handoffs, invalidations } = workbench;
  if (!plan.mid_zero) {
    $('handoffs').replaceChildren(el('p', { class: 'placeholder' }, '本测次未声明中途清零，按完整序列复核，无需分段交接。'));
    return;
  }
  const issues = result.issues.filter((issue) => riseKeys.includes(issue.step));
  const children = [
    el('div', { class: 'section-head' }, el('h2', {}, '升程交接'),
      issues.length ? el('span', { class: 'muted' }, '本段证据尚不足以交接') :
        button('确认并交接', () => confirmHandoff(id, generation, workbench, onSaved), 'primary')),
  ];
  if (issues.length) {
    children.push(el('div', { class: 'issues' }, el('ul', {}, issues.map((issue) =>
      el('li', {}, `${riseLabels[issue.step] ?? issue.step}：${issue.code === 'ambiguous' ? '多条有效候选' : '缺步'}`)))));
  }
  children.push(...handoffs.map(handoffView));
  if (!handoffs.length) children.push(el('p', { class: 'placeholder' }, '尚未交接升程证据。'));
  if (invalidations.length) {
    children.push(el('h2', {}, '失效记录'));
    children.push(el('div', { class: 'table-wrap' }, table(['交接', '代次', '原因', '说明', '记录时间 UTC'],
      invalidations.map((event) => [mono(`v${event.number}`), event.generation,
        reasonLabels[event.reason] ?? event.reason, event.detail, mono(event.invalidated_at)]))));
  }
  $('handoffs').replaceChildren(...children);
}
