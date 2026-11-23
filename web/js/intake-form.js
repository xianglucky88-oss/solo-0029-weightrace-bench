import { request, sessionPath } from './api.js';
import { button, el, labelled, table } from './dom.js';
import { closeEditor, editorForm, openEditor } from './editor.js';
import { actionLabels, mono } from './labels.js';

export function showIntake(id, onSaved) {
  const body = el('textarea', { name: 'packet', rows: 9, required: true, spellcheck: 'false',
    placeholder: '单分度：{"id":"PACKET-01","rows":[{"id":"R-1","step":"zero_in","observed_at":"…Z","indicated_mg":0}]}\n多分度档：{"id":"PACKET-01","rows":[{"id":"R-1","step":"zero_in","observed_at":"…Z","scale":"G1","grids":0}]}' });
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

export function showEvidence(id, generation, step, onSaved) {
  const multi = step.candidates.some((row) => row.scale !== undefined && row.scale !== null);
  const headers = multi
    ? ['读数', '首次采集包', 'UTC', '档位', '原始格数', '示值 mg', '状态', '复核']
    : ['读数', '首次采集包', 'UTC', '示值 mg', '状态', '复核'];
  const rows = step.candidates.map((row) => {
    const active = row.decision?.action !== 'exclude';
    const action = active ? 'exclude' : 'include';
    const decision = active ? '有效' : '已剔除';
    const base = [mono(row.id), mono(row.origin_packet), mono(row.observed_at)];
    const reading = multi
      ? [...base, mono(row.scale), mono(row.grids), mono(row.indicated_mg), decision]
      : [...base, mono(row.indicated_mg), decision];
    return [...reading, button(actionLabels[action], () => {
      openEditor(`${actionLabels[action]} ${row.id}`, editorForm(labelled('复核说明', el('textarea', {
        name: 'reason', required: true, maxlength: 180, rows: 3,
      })), '提交决定', async (form) => {
        await request(sessionPath(id, '/decisions'), { reading: row.id, action, generation, reason: form.get('reason') });
        closeEditor();
        await onSaved('逐行决定已记录。');
      }));
    })];
  });
  openEditor(step.label, el('div', { class: 'table-wrap' }, table(headers, rows)));
}
