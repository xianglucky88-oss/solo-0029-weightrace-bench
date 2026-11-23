import { fileUrl, request, sessionPath } from './api.js';
import { $, button, el, labelled, table } from './dom.js';
import { closeEditor, editorForm, openEditor } from './editor.js';
import { badge, metricLabels, mg, mono, stateLabels } from './labels.js';

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

function showAdoption(id, item, records, onSaved) {
  const usable = records.filter((record) => !record.reason);
  const title = `${item.status === 'pending' ? '重新接替' : item.release ? '更正接替' : '登记接替'} · ${metricLabels[item.metric]}`;
  if (!usable.length) {
    openEditor(title, el('p', {}, '当前没有可采用的未撤回交付件。'));
    return;
  }
  let expect = item.release ?? null;
  const conflict = el('p', { class: 'dialog-error', role: 'alert' });
  openEditor(title, editorForm([
    el('p', {}, '接替只引用所选交付件中该分项已封存的结论及其读数、基准与限值，不跨版拼算。'),
    labelled('采用交付件', el('select', { name: 'release' }, usable.map((record) =>
      el('option', { value: record.number, selected: record.number === item.release },
        `v${record.number} · ${stateLabels[record.outcome]}`)))),
    labelled('接替事由', el('textarea', { name: 'reason', required: true, maxlength: 180, rows: 3 })),
    conflict,
  ], '确认接替', async (form) => {
    try {
      await request(sessionPath(id, '/adoptions'), {
        metric: item.metric, release: Number(form.get('release')),
        reason: form.get('reason'), expect_release: expect,
      });
    } catch (failure) {
      if (failure.code !== 'adoption_conflict') throw failure;
      const current = failure.details?.current;
      conflict.textContent = current
        ? `该分项现任接替为 v${current.release}（${current.registered_at} 登记：${current.reason}）。核对后如需更正，请再次提交。`
        : '该分项的现任接替与预期不符。核对后如需登记，请再次提交。';
      expect = current?.release ?? null;
      return;
    }
    closeEditor();
    await onSaved('接替已登记。');
  }));
}

function renderAdoptions(id, records, adoptions, onSaved) {
  $('adoptions').replaceChildren(table(['分项', '采用来源', '分项结论', '状态', '登记事由 / UTC', '操作'],
    adoptions.current.map((item) => [
      metricLabels[item.metric],
      item.release ? `v${item.release}${item.status === 'pending' ? ' · 已撤回' : ''}` : '—',
      item.outcome ? badge(item.outcome) : '—',
      badge(item.status),
      item.release ? el('div', {}, el('p', {}, item.reason), el('small', {}, mono(item.registered_at))) : '—',
      button(item.status === 'pending' ? '重新接替' : item.release ? '更正接替' : '登记接替',
        () => showAdoption(id, item, records, onSaved)),
    ])));
  $('adoption-history').replaceChildren(table(['分项', '原采用', '登记事由 / UTC', '停用 UTC', '停用事由'],
    [...adoptions.history].reverse().map((row) => [
      metricLabels[row.metric], `v${row.release}`,
      el('div', {}, el('p', {}, row.reason), el('small', {}, mono(row.registered_at))),
      mono(row.superseded_at), row.supersede_reason,
    ]), '暂无接替变更'));
}

function diffView(diff) {
  const stepValue = (x) => `${x.selected ?? '—'} / ${mg(x.error)} mg`;
  return el('section', {}, el('h2', {}, `对账 · v${diff.left} → v${diff.right}`),
    el('p', {}, badge(diff.outcomes[0]), ' → ', badge(diff.outcomes[1])),
    el('p', {}, `新增采集包：${diff.packets_added.join('、') || '无'}；减少：${diff.packets_removed.join('、') || '无'}`),
    el('div', { class: 'table-wrap' }, table(['加载步骤', '原读数 / 误差', '新读数 / 误差'],
      diff.steps.map((x) => [x.label, mono(stepValue(x.before)), mono(stepValue(x.after))]), '无步骤差异')),
    el('div', { class: 'table-wrap' }, table(['发生变化的分项', '原结论', '新结论'],
      diff.metrics.map((x) => [metricLabels[x.id], badge(x.before.outcome), badge(x.after.outcome)]), '无分项差异')));
}

export function renderReleases(id, records, adoptions, onSaved, run) {
  $('releases').replaceChildren(table(['版本 / 代次', '签出 UTC', '结论', '状态', '操作'], records.map((record) => {
    const path = sessionPath(id, `/releases/${record.number}`);
    return [`v${record.number} / ${record.generation}`, mono(record.published_at), badge(record.outcome),
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
  renderAdoptions(id, records, adoptions, onSaved);
}
