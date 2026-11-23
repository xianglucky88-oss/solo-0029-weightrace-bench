import { $ } from './dom.js';

let current = null;

export function showCurve(result) {
  current = result?.outcome === 'blocked' ? null : result;
  $('curve-figure').hidden = !current;
  paintCurve();
}

export function paintCurve() {
  const canvas = $('curve');
  if (!current || !canvas.clientWidth) return;
  const ratio = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = Math.round(w * ratio);
  canvas.height = Math.round(h * ratio);
  const ctx = canvas.getContext('2d');
  ctx.scale(ratio, ratio);
  const points = current.steps.map((step) => {
    const row = step.candidates.find((candidate) => candidate.id === step.selected);
    const [num, den] = step.error.mg.split('/').map(Number);
    return { x: Date.parse(row.observed_at), y: num / den };
  });
  const left = 32, right = w - 9, top = 9, bottom = h - 18;
  const yMax = Math.ceil(Math.max(1, ...points.map(({ y }) => Math.abs(y))) * 1.15);
  const x = (point) => left + ((point.x - points[0].x) / (points.at(-1).x - points[0].x)) * (right - left);
  const y = (value) => top + (yMax - value) * (bottom - top) / (2 * yMax);
  ctx.font = '11px ui-monospace, monospace';
  for (const mark of [yMax, 0, -yMax]) {
    const at = y(mark);
    ctx.strokeStyle = mark ? '#e1e8e1' : '#9fafa6';
    ctx.beginPath(); ctx.moveTo(left, at); ctx.lineTo(right, at); ctx.stroke();
    ctx.fillStyle = '#465951'; ctx.fillText(String(mark), 1, at + 4);
  }
  ctx.strokeStyle = '#12634f'; ctx.lineWidth = 1.6; ctx.beginPath();
  points.forEach((point, i) => (i ? ctx.lineTo(x(point), y(point.y)) : ctx.moveTo(x(point), y(point.y))));
  ctx.stroke();
  for (const point of points) {
    ctx.beginPath(); ctx.arc(x(point), y(point.y), 3.2, 0, Math.PI * 2); ctx.fillStyle = '#12634f'; ctx.fill();
  }
  ctx.fillStyle = '#465951';
  ctx.fillText('0 s', left, h - 3);
  const tail = `${(points.at(-1).x - points[0].x) / 1000} s`;
  ctx.fillText(tail, right - ctx.measureText(tail).width, h - 3);
}
