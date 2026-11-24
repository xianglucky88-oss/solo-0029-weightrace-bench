import { request, sessionPath } from './api.js';
import { el, labelled, table } from './dom.js';
import { closeEditor, editorForm, openEditor } from './editor.js';
import { mono } from './labels.js';

function describe(load) {
  return `${load.items.map((item) => `${item.id} / 修订 ${item.revision}`).join('、')} · 参考 ${load.reference_mg} mg · 半径 ${load.radius_mg} mg`;
}

export function showSwitch(workbench, onSaved) {
  const { plan, generation, current_round: currentRound, rounds } = workbench;
  const lowIds = new Set(plan.loads.low.items.map((item) => item.id));
  const roundRows = rounds.map((round) => [
    `第 ${round.round} 轮`, round.origin === 'plan' ? '开测锁定' : mono(round.origin),
    mono(describe(round.high_load)), mono(round.switched_at)]);
  openEditor('换用高档组合', el('div', {},
    el('p', { class: 'placeholder' },
      `当前第 ${currentRound} 轮。换用成功后须从升高开始整段重采（含回低与尾空盘）；首空盘、升低沿用第 0 轮，已接纳裁决仍可查但不套用于新一轮。`),
    el('h2', {}, '各加载轮高档组合'),
    table(['加载轮', '来源', '高档实物 / 参考区间', '记录时间 UTC'], roundRows),
    editorForm([
      labelled('新高档组合（凭据编号 / 修订的 JSON 数组）',
        el('textarea', { name: 'high', rows: 3, required: true, spellcheck: 'false',
          placeholder: JSON.stringify(plan.loads.high.items.map((item) => ({ id: item.id, revision: item.revision }))) })),
      labelled('换用说明', el('textarea', { name: 'reason', required: true, maxlength: 180, rows: 2 })),
      el('p', { class: 'dialog-error' },
        `低档实物（${[...lowIds].join('、')}）必须以同一修订完整保留；参考增量下界须严格大于零。`),
    ], '提交换用', async (form) => {
      let high;
      try {
        high = JSON.parse(form.get('high'));
      } catch {
        throw new Error('高档组合须为 JSON 数组。');
      }
      const result = await request(sessionPath(plan.id, '/switches'),
        { generation, high, reason: form.get('reason') });
      closeEditor();
      await onSaved(`已进入第 ${result.round} 轮，请从升高开始重采。`);
    })));
}
