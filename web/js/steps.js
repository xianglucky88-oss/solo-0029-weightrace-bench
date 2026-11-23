import { $, button, el, table } from './dom.js';
import { badge, mg, mono, stateLabels } from './labels.js';
import { showCurve } from './curve.js';

export function renderSteps(result, onEvidence) {
  const coverage = result.steps.filter(({ state }) => state === 'matched').length;
  $('coverage').textContent = `${coverage} / ${result.steps.length} 步已对齐`;
  const labels = Object.fromEntries(result.steps.map(({ id, label }) => [id, label]));
  $('issues').replaceChildren(...(result.issues.length ? [el('div', { class: 'issues' }, '当前无法判定',
    el('ul', {}, result.issues.map(({ code, step }) => el('li', {}, `${labels[step]}：${stateLabels[code]}`))))] : []));
  const rows = result.steps.map((step) => {
    const selected = step.candidates.find(({ id }) => id === step.selected);
    const shown = selected ? (selected.scale
      ? `${selected.indicated_mg}（${selected.scale} · ${selected.grids} 格）`
      : selected.indicated_mg) : '—';
    return [step.label, badge(step.state), mono(selected?.observed_at.slice(11, 19) ?? '—'), mono(step.reference_mg),
      mono(shown), mono(mg(step.error)),
      button(`证据 (${step.candidates.length})`, () => onEvidence(step), 'quiet', { disabled: !step.candidates.length })];
  });
  $('steps').replaceChildren(table(['加载步骤', '状态', '采集 UTC', '参考 mg', '示值 mg（档位 · 格数）', '误差 mg', '原始行'], rows));
  showCurve(result);
}
