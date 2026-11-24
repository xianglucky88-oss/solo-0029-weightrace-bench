import { $, button, el, table } from './dom.js';
import { badge, mg, mono, stateLabels } from './labels.js';
import { showCurve } from './curve.js';

export function renderSteps(result, onEvidence) {
  const coverage = result.steps.filter(({ state }) => state === 'matched').length;
  $('coverage').textContent = `${coverage} / ${result.steps.length} 步已对齐`;
  const labels = Object.fromEntries(result.steps.map(({ id, label }) => [id, label]));
  $('issues').replaceChildren(...(result.issues.length ? [el('div', { class: 'issues' }, '当前无法判定',
    el('ul', {}, result.issues.map(({ code, step }) => el('li', {}, `${labels[step] ?? step}：${stateLabels[code]}`))))] : []));
  const segmented = new Set(result.steps.map(({ segment }) => segment)).size > 1;
  const segmentLabel = (segment) => segment === 'rise' ? '升程段' : segment === 'fall' ? '回程段' : '—';
  const rows = result.steps.map((step) => {
    const selected = step.candidates.find(({ id }) => id === step.selected);
    return [step.label, badge(step.state), mono(selected?.observed_at.slice(11, 19) ?? '—'), mono(step.reference_mg),
      mono(selected?.indicated_mg ?? '—'), mono(mg(step.error)), segmented ? segmentLabel(step.segment) : null,
      button(`证据 (${step.candidates.length})`, () => onEvidence(step), 'quiet', { disabled: !step.candidates.length })];
  });
  const headers = ['加载步骤', '状态', '采集 UTC', '参考 mg', '示值 mg', '误差 mg',
    ...(segmented ? ['分段'] : []), '原始行'];
  $('steps').replaceChildren(table(headers, rows));
  showCurve(result);
}
