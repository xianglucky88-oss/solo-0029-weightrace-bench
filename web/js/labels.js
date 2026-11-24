import { el } from './dom.js';

export const metricLabels = { indication: '示值偏差', hysteresis: '低档回程差', repeatability: '中心重复性',
  eccentricity: '位置偏差', drift: '首尾零漂' };
export const stateLabels = { matched: '已对齐', missing: '缺步', ambiguous: '多候选', out_of_order: '时序异常',
  pass: '通过', fail: '超限', borderline: '临界', blocked: '待补证', draft: '工作中', released: '已签出', amended: '有新资料', withdrawn: '已撤回',
  missing_bulletin: '缺适用公告' };
export const actionLabels = { include: '复纳', exclude: '剔除' };

export const badge = (state) => el('span', { class: `badge ${state}` }, stateLabels[state] ?? state);
export const mg = (quantity) => quantity?.display_mg ?? '—';
export const mono = (text) => el('span', { class: 'mono' }, text);
