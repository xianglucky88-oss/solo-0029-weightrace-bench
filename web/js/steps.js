import { $, button, el, table } from './dom.js';
import { badge, mg, mono, reviewStatusLabels, stateLabels } from './labels.js';
import { showCurve } from './curve.js';

export function renderSteps(result, onEvidence) {
  const coverage = result.steps.filter(({ state }) => state === 'matched').length;
  $('coverage').textContent = `${coverage} / ${result.steps.length} 步已对齐`;
  const labels = Object.fromEntries(result.steps.map(({ id, label }) => [id, label]));
  const detail = (code) => (code === 'review' && result.review ? `（${reviewStatusLabels[result.review.status]}）` : '');
  $('issues').replaceChildren(...(result.issues.length ? [el('div', { class: 'issues' }, '当前无法判定',
    el('ul', {}, result.issues.map(({ code, step }) => el('li', {}, `${labels[step]}：${stateLabels[code]}${detail(code)}`))))] : []));
  const rows = result.steps.map((step) => {
    const selected = step.candidates.find(({ id }) => id === step.selected);
    return [step.label, badge(step.state), mono(selected?.observed_at.slice(11, 19) ?? '—'), mono(step.reference_mg),
      mono(selected?.indicated_mg ?? '—'), mono(mg(step.error)),
      button(`证据 (${step.candidates.length})`, () => onEvidence(step), 'quiet', { disabled: !step.candidates.length })];
  });
  $('steps').replaceChildren(table(['加载步骤', '状态', '采集 UTC', '参考 mg', '示值 mg', '误差 mg', '原始行'], rows));
  showCurve(result);
}
