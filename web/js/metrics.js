import { $, el } from './dom.js';
import { badge, metricLabels, mg, mono } from './labels.js';

function basisLine(result) {
  const basis = result.basis;
  if (!basis) return null;
  if (basis.mode === 'own') return el('p', { class: 'basis-note' }, '依据：本单自带限值');
  if (basis.bulletin) {
    return el('p', { class: 'basis-note' }, `依据：公告 ${basis.bulletin.id} · 适用 ${basis.bulletin.effective_from} 至 ${basis.bulletin.effective_until}`);
  }
  return el('p', { class: 'basis-note problem-text' }, `缺依据：测次日 ${basis.measured_on} 无已发布且适用的公告`);
}

export function renderMetrics(result) {
  $('outcome').replaceChildren(badge(result.outcome));
  const labels = Object.fromEntries(result.steps.map(({ id, label }) => [id, label]));
  const note = basisLine(result);
  const list = Object.entries(metricLabels).flatMap(([key, label]) => {
    const m = result.metrics[key];
    return !m ? [] : [el('details', { class: 'metric', open: m.outcome !== 'pass' },
      el('summary', {}, label, badge(m.outcome)), el('p', {}, `上限 ${m.limit_mg} mg`),
      el('ul', {}, m.checks.map((check) => el('li', {}, check.steps.map((id) => labels[id]).join(' / '),
        el('div', {}, mono(`${mg(check.lower)} – ${mg(check.upper)} mg`), ' ', badge(check.outcome))))))];
  });
  $('metrics').replaceChildren(...(note ? [note] : []), ...(list.length ? list : [el('p', { class: 'placeholder' }, '暂无可判定结果') ]));
}
