import { $, el } from './dom.js';
import { badge, metricLabels, mg, mono } from './labels.js';

export function renderMetrics(result) {
  $('outcome').replaceChildren(badge(result.outcome));
  const labels = Object.fromEntries(result.steps.map(({ id, label }) => [id, label]));
  const list = Object.entries(metricLabels).flatMap(([key, label]) => {
    const m = result.metrics[key];
    return !m ? [] : [el('details', { class: 'metric', open: m.outcome !== 'pass' },
      el('summary', {}, label, badge(m.outcome)), el('p', {}, `上限 ${m.limit_mg} mg`),
      el('ul', {}, m.checks.map((check) => el('li', {}, check.steps.map((id) => labels[id]).join(' / '),
        el('div', {}, mono(`${mg(check.lower)} – ${mg(check.upper)} mg`), ' ', badge(check.outcome))))))];
  });
  $('metrics').replaceChildren(...(list.length ? list : [el('p', { class: 'placeholder' }, '暂无可判定结果') ]));
}
