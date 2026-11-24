import { $, table } from './dom.js';
import { actionLabels, mono } from './labels.js';

export function renderRecords({ packets, decisions }) {
  $('packet-count').textContent = `${packets.length} 份采集包`;
  $('packets').replaceChildren(table(['采集包', '加载轮', '接收时间 UTC', 'SHA-256 摘要'], packets.map((packet) => [
    mono(packet.id), mono(`第 ${packet.round ?? 0} 轮`), mono(packet.accepted_at), mono(packet.digest),
  ])));
  $('decisions').replaceChildren(table(['代次', '读数', '决定', '理由', '记录时间 UTC'], [...decisions].reverse().map((record) => [
    record.generation, mono(record.reading), actionLabels[record.action], record.reason, mono(record.made_at),
  ])));
}
