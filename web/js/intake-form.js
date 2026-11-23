import { request, sessionPath } from './api.js';
import { button, el, labelled, table } from './dom.js';
import { closeEditor, editorForm, openEditor } from './editor.js';
import { actionLabels, mono, reviewCauseLabels, reviewStatusLabels } from './labels.js';

export function showIntake(id, onSaved) {
  const body = el('textarea', { name: 'packet', rows: 9, required: true, spellcheck: 'false', placeholder: '{"id":"PACKET-01","rows":[…]}' });
  const file = el('input', { type: 'file', accept: '.json,application/json' });
  const message = el('p', { class: 'dialog-error', role: 'alert' });
  file.addEventListener('change', async () => {
    const source = file.files[0];
    if (!source) return;
    message.textContent = '';
    if (source.size > 256000) {
      message.textContent = '采集包超过 256 KB。';
      return;
    }
    try {
      const text = new TextDecoder('utf-8', { fatal: true }).decode(await source.arrayBuffer());
      if (file.files[0] === source) body.value = text;
    } catch {
      message.textContent = '采集包无法读取为 UTF-8。';
    }
  });
  openEditor('导入采集包', editorForm([labelled('从文件读取', file), message, labelled('采集包原文 JSON', body)],
    '归集', async (form) => {
      const result = await request(sessionPath(id, '/packets'), form.get('packet'), { raw: true });
      closeEditor();
      await onSaved(result.duplicate ? '相同采集包已存在，代次未变。' : '采集包已归集。');
    }));
}

function showDualReview(id, generation, step, review, onSaved) {
  const banner = review.status === 'confirmed'
    ? el('div', { class: 'notice' }, `两名复核员意见一致，保留 ${review.selection}；签出前迟到的新候选会使本步重新待审。`)
    : el('div', { class: 'issues' }, `当前待审：${reviewStatusLabels[review.status]}`);
  const counted = table(['复核员', '保留', '复核说明', '提交 UTC'], review.opinions.map((opinion) => [
    mono(opinion.reviewer), mono(opinion.keep), opinion.reason, mono(opinion.made_at),
  ]), '尚无计票意见');
  const stale = review.stale.length ? [
    el('h3', {}, '已失效意见（保留备查，不再计票）'),
    el('div', { class: 'table-wrap' }, table(['复核员', '保留', '原候选集合', '失效原因', '提交 UTC'],
      review.stale.map((opinion) => [mono(opinion.reviewer), mono(opinion.keep), mono(opinion.candidates.join('、')),
        reviewCauseLabels[opinion.cause], mono(opinion.made_at)]))),
  ] : [];
  openEditor(`${step.label} · 双人复核`,
    banner,
    el('p', { class: 'muted' }, '本步候选达到两条，逐行裁决不再计票；两名不同复核员须针对同一候选集合给出一致意见。'),
    el('div', { class: 'table-wrap' }, table(['读数', '首次采集包', 'UTC', '示值 mg'], step.candidates.map((row) => [
      mono(row.id), mono(row.origin_packet), mono(row.observed_at), mono(row.indicated_mg),
    ]))),
    el('h3', {}, '本次计票意见'), counted, ...stale,
    editorForm([
      labelled('复核员姓名', el('input', { name: 'reviewer', required: true, maxlength: 48 })),
      el('fieldset', {}, el('legend', {}, '保留哪一条候选（其余候选一并剔除）'),
        review.candidates.map((candidate) => el('label', { class: 'check' },
          el('input', { type: 'radio', name: 'keep', value: candidate, required: true }), mono(candidate)))),
      labelled('复核说明', el('textarea', { name: 'reason', required: true, maxlength: 180, rows: 3 })),
    ], '提交复核意见', async (form) => {
      const keep = form.get('keep');
      await request(sessionPath(id, '/reviews'), { reviewer: form.get('reviewer'), candidates: review.candidates,
        keep, drops: review.candidates.filter((candidate) => candidate !== keep), reason: form.get('reason'), generation });
      closeEditor();
      await onSaved('复核意见已记录。');
    }));
}

export function showEvidence(id, generation, step, review, onSaved) {
  if (review?.required && step.id === review.step) {
    showDualReview(id, generation, step, review, onSaved);
    return;
  }
  const rows = step.candidates.map((row) => {
    const active = row.decision?.action !== 'exclude';
    const action = active ? 'exclude' : 'include';
    return [mono(row.id), mono(row.origin_packet), mono(row.observed_at), mono(row.indicated_mg),
      active ? '有效' : '已剔除', button(actionLabels[action], () => {
        openEditor(`${actionLabels[action]} ${row.id}`, editorForm(labelled('复核说明', el('textarea', {
          name: 'reason', required: true, maxlength: 180, rows: 3,
        })), '提交决定', async (form) => {
          await request(sessionPath(id, '/decisions'), { reading: row.id, action, generation, reason: form.get('reason') });
          closeEditor();
          await onSaved('逐行决定已记录。');
        }));
      })];
  });
  openEditor(step.label, el('div', { class: 'table-wrap' }, table(['读数', '首次采集包', 'UTC', '示值 mg', '状态', '复核'], rows)));
}
