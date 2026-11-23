import { request, sessionPath } from './api.js';
import { button, el, labelled, table } from './dom.js';
import { closeEditor, editorForm, openEditor } from './editor.js';
import { actionLabels, mono } from './labels.js';

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
      if (result.pending) {
        await onSaved(result.duplicate ? '相同回执与内容已在待认领区，未重复挂起。' : '包内未带轮次凭据，已留在待认领区。');
      } else if (result.retransmission) {
        await onSaved('同轮同号同内容，按重传处理，代次未变。');
      } else {
        await onSaved('采集包已归集。');
      }
    }));
}

export function showEvidence(id, generation, step, onSaved) {
  const rows = step.candidates.map((row) => {
    const active = row.decision?.action !== 'exclude';
    const action = active ? 'exclude' : 'include';
    const sources = (row.sources ?? []).map((source) => {
      const round = source.round || '普通收包';
      return `${round} · ${source.packet}${source.receipt ? ` · 回执 ${source.receipt}` : ''}`;
    }).join('；') || row.origin_packet;
    return [mono(row.id), mono(sources), mono(row.observed_at), mono(row.indicated_mg),
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
  openEditor(step.label, el('div', { class: 'table-wrap' }, table(['读数', '采集包与轮次来源', 'UTC', '示值 mg', '状态', '复核'], rows)));
}
