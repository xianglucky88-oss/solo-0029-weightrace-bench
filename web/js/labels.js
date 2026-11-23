import { el } from './dom.js';

export const metricLabels = { indication: '示值偏差', hysteresis: '低档回程差', repeatability: '中心重复性',
  eccentricity: '位置偏差', drift: '首尾零漂' };
export const stateLabels = { matched: '已对齐', missing: '缺步', ambiguous: '多候选', out_of_order: '时序异常',
  review: '待双人复核', pass: '通过', fail: '超限', borderline: '临界', blocked: '待补证', draft: '工作中',
  released: '已签出', amended: '有新资料', withdrawn: '已撤回' };
export const actionLabels = { include: '复纳', exclude: '剔除' };
export const reviewStatusLabels = { awaiting_first: '等待两名复核员分别给出意见',
  awaiting_second: '一人已确认，等待第二位复核员的一致意见', conflict: '复核意见冲突，待统一',
  confirmed: '两名复核员意见一致' };
export const reviewCauseLabels = { superseded: '本人已更新意见', candidates_changed: '候选集合已变化' };

export const badge = (state) => el('span', { class: `badge ${state}` }, stateLabels[state] ?? state);
export const mg = (quantity) => quantity?.display_mg ?? '—';
export const mono = (text) => el('span', { class: 'mono' }, text);
