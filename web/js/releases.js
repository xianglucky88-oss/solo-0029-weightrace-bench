import { fileUrl, request, sessionPath } from './api.js';
import { $, button, el, labelled, table } from './dom.js';
import { closeEditor, editorForm, openEditor } from './editor.js';
import { badge, metricLabels, mg, mono } from './labels.js';

function showWithdrawal(record, path, onSaved) {
  openEditor(`撤回 v${record.number}`, editorForm([
    el('p', {}, '保留原交付件与复算入口，撤回事由不能覆盖。'),
    labelled('撤回事由', el('textarea', { name: 'reason', required: true, maxlength: 180 })),
  ], '确认撤回', async (form) => {
    await request(`${path}/withdraw`, { reason: form.get('reason') });
    closeEditor();
    await onSaved('交付件已撤回，原始内容保留。');
  }));
}

function diffView(diff) {
  const stepValue = (x) => `${x.selected ?? '—'} / ${mg(x.error)} mg`;
  const basisText = (basis) => basis.mode === 'bulletin' ? `公告 ${basis.bulletin_id ?? '—'}` : '自带限值';
  return el('section', {}, el('h2', {}, `对账 · v${diff.left} → v${diff.right}`),
    el('p', {}, badge(diff.outcomes[0]), ' → ', badge(diff.outcomes[1])),
    el('p', {}, `限值依据：${basisText(diff.basis[0])} → ${basisText(diff.basis[1])}`),
    el('p', {}, `新增采集包：${diff.packets_added.join('、') || '无'}；减少：${diff.packets_removed.join('、') || '无'}`),
    el('div', { class: 'table-wrap' }, table(['加载步骤', '原读数 / 误差', '新读数 / 误差'],
      diff.steps.map((x) => [x.label, mono(stepValue(x.before)), mono(stepValue(x.after))]), '无步骤差异')),
    el('div', { class: 'table-wrap' }, table(['发生变化的分项', '原结论', '新结论'],
      diff.metrics.map((x) => [metricLabels[x.id], badge(x.before.outcome), badge(x.after.outcome)]), '无分项差异')));
}

export function renderReleases(id, records, onSaved, run) {
  $('releases').replaceChildren(table(['版本 / 代次', '签出 UTC', '依据', '结论', '状态', '操作'], records.map((record) => {
    const path = sessionPath(id, `/releases/${record.number}`);
    return [`v${record.number} / ${record.generation}`, mono(record.published_at),
      mono(record.basis_id ? `公告 ${record.basis_id}` : '自带限值'), badge(record.outcome),
      record.reason ? el('div', {}, badge('withdrawn'), el('p', {}, record.reason), el('small', {}, record.withdrawn_at)) : badge('released'),
      el('div', { class: 'actions' }, el('a', { class: 'button quiet', href: fileUrl(id, record.number) }, '下载'),
        button('复算', () => run(async () => {
          const result = await request(`${path}/replay`);
          openEditor(`复算 v${record.number}`, el('p', {}, result.verified ? '封存输入与原判定一致，摘要已核对。' : `未能核验：${result.reason}`),
            el('p', { class: 'mono' }, result.sha256));
        })), record.reason ? null : button('撤回', () => showWithdrawal(record, path, onSaved)))];
  })));
  const target = el('div', { 'aria-live': 'polite' });
  const select = (name, selected) => el('select', { name }, records.map(({ number }) =>
    el('option', { value: number, selected: selected === number }, `v${number}`)));
  $('comparison').replaceChildren(...(records.length < 2 ? [] : [
    el('form', { class: 'compare-form', onsubmit: (event) => {
      event.preventDefault();
      const query = new URLSearchParams(new FormData(event.currentTarget));
      run(async () => {
        const diff = await request(sessionPath(id, `/compare?${query}`));
        target.replaceChildren(diffView(diff));
      });
    } }, labelled('基准版', select('left', records[1].number)), labelled('比较版', select('right', records[0].number)),
    el('button', { type: 'submit' }, '逐步对账')), target,
  ]));
}
