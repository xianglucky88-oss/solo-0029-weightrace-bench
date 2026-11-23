import { $, table } from './dom.js';
import { actionLabels, mono } from './labels.js';

export function renderRecords({ packets, decisions, reviews }) {
  $('packet-count').textContent = `${packets.length} 份采集包`;
  $('packets').replaceChildren(table(['采集包', '接收时间 UTC', 'SHA-256 摘要'], packets.map((packet) => [
    mono(packet.id), mono(packet.accepted_at), mono(packet.digest),
  ])));
  $('decisions').replaceChildren(table(['代次', '读数', '决定', '理由', '记录时间 UTC'], [...decisions].reverse().map((record) => [
    record.generation, mono(record.reading), actionLabels[record.action], record.reason, mono(record.made_at),
  ])));
  $('reviews').replaceChildren(table(['代次', '复核员', '保留', '剔除', '针对候选', '复核说明', '提交 UTC'],
    [...reviews].reverse().map((opinion) => [
      opinion.generation, mono(opinion.reviewer), mono(opinion.keep), mono(opinion.drops.join('、') || '—'),
      mono(opinion.candidates.join('、')), opinion.reason, mono(opinion.made_at),
    ]), '尚无双人复核意见'));
}
