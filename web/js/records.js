import { request, sessionPath } from './api.js';
import { $, button, el, labelled, table } from './dom.js';
import { closeEditor, editorForm, openEditor } from './editor.js';
import { actionLabels, mono, basisLabels, pendingLabels } from './labels.js';

function showClaim(id, record, onSaved) {
  const round = el('input', { name: 'round', required: true, maxlength: 64, placeholder: '采集器轮次凭据' });
  const disposition = el('select', { name: 'disposition' },
    el('option', { value: 'claim' }, '认领到该轮次'),
    el('option', { value: 'retransmission' }, '核对为同轮同号同内容的重传，结案'));
  openEditor(`处理待认领包 ${record.id}`, editorForm([
    el('p', {}, `送交回执 ${record.receipt}，摘要 ${record.digest.slice(0, 16)}…。`),
    labelled('补充轮次凭据', round), labelled('处理方式', disposition),
  ], '提交', async (form) => {
    await request(sessionPath(id, '/pending'), {
      receipt: record.receipt, round: form.get('round'), disposition: form.get('disposition'),
    });
    closeEditor();
    await onSaved('待认领采集包已处理。');
  }));
}

export function renderRecords({ plan, packets, pending, decisions }, onSaved) {
  const id = plan.id;
  const waiting = pending.filter((record) => record.status === 'pending').length;
  $('packet-count').textContent = `${packets.length} 份采集包${waiting ? ` · ${waiting} 份待认领` : ''}`;
  $('packets').replaceChildren(table(['采集包', '轮次', '归属依据', '送交回执', '接收时间 UTC', 'SHA-256 摘要'],
    packets.map((packet) => [
      mono(packet.id), mono(packet.round || '—'), basisLabels[packet.round_basis] ?? packet.round_basis,
      mono(packet.receipt || '—'), mono(packet.accepted_at), mono(packet.digest),
    ])));
  $('pending').replaceChildren(table(['采集包', '送交回执', '状态', '归入轮次', '收到时间 UTC', 'SHA-256 摘要', '操作'],
    pending.map((record) => [mono(record.id), mono(record.receipt), pendingLabels[record.status] ?? record.status,
      mono(record.round || '—'), mono(record.received_at), mono(record.digest),
      record.status === 'pending' ? button('处理', () => showClaim(id, record, onSaved)) : null])));
  $('decisions').replaceChildren(table(['代次', '读数', '决定', '理由', '记录时间 UTC'], [...decisions].reverse().map((record) => [
    record.generation, mono(record.reading), actionLabels[record.action], record.reason, mono(record.made_at),
  ])));
}
