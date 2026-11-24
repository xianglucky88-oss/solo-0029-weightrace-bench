import { request, sessionPath } from './api.js';
import { showBulletins } from './bulletins.js';
import { showCatalog } from './catalog.js';
import { paintCurve } from './curve.js';
import { $, el } from './dom.js';
import { closeEditor } from './editor.js';
import { showEvidence, showIntake } from './intake-form.js';
import { badge } from './labels.js';
import { renderMetrics } from './metrics.js';
import { showPlan } from './plan-form.js';
import { renderRecords } from './records.js';
import { renderReleases } from './releases.js';
import { renderSteps } from './steps.js';

const tabs = ['working', 'packets', 'releases'];
let current = null;
let busy = false;

function notice(message = '', error = false) {
  const element = $('notice');
  element.textContent = message;
  element.hidden = !message;
  element.classList.toggle('problem', error);
}

async function run(operation) {
  if (busy) return;
  busy = true;
  notice();
  try { await operation(); }
  catch (error) { notice(error.message || '操作未完成', true); }
  finally { busy = false; }
}

function selectTab(active) {
  for (const tab of tabs) {
    $(`${tab}-tab`).setAttribute('aria-pressed', String(active === tab));
    $(`${tab}-pane`).hidden = active !== tab;
  }
  if (active === 'working') paintCurve();
}

async function refresh(key, tab) {
  const sessions = await request('sessions');
  const id = key ?? sessions[0]?.id;
  current = id ? await request(sessionPath(id)) : null;
  $('sessions').replaceChildren(...sessions.map((session) => el('button', { class: 'session-link',
    'aria-current': String(session.id === id), onclick: () => run(() => refresh(session.id, 'working')),
  }, el('strong', {}, session.bench), el('small', {}, `${session.id} · ${session.measured_on}`))));
  $('workspace').hidden = !current;
  $('empty').hidden = Boolean(current);
  if (!current) return;
  const { plan, generation, state, result, releases } = current;
  const saved = async (message) => {
    try { await refresh(id); notice(message); }
    catch { notice(`${message} 刷新失败，请重新选择测次。`, true); }
  };
  $('work-id').textContent = plan.id;
  $('bench-name').textContent = plan.bench;
  const basis = result.basis;
  const basisText = !basis ? '' : basis.mode === 'own' ? '自带限值'
    : basis.bulletin ? `公告 ${basis.bulletin.id}（${basis.bulletin.effective_from} 起适用）`
      : `缺适用公告（测次日 ${basis.measured_on}）`;
  $('work-facts').replaceChildren(`${plan.measured_on} · 分度 ${plan.resolution_mg} mg · 代次 ${generation} `,
    badge(state), basisText ? ` · 依据：${basisText}` : '');
  const publishedHere = releases[0]?.generation === generation
    && (!basis || basis.mode !== 'bulletin' || releases[0]?.basis_id === basis.bulletin?.id);
  $('publish').disabled = result.outcome === 'blocked' || publishedHere;
  $('import-packet').onclick = () => showIntake(id, saved);
  renderSteps(result, (step) => showEvidence(id, generation, step, saved));
  renderMetrics(result);
  renderRecords(current);
  renderReleases(id, releases, saved, run);
  if (tab) selectTab(tab);
}

$('close-dialog').addEventListener('click', closeEditor);
$('catalog-button').addEventListener('click', () => run(showCatalog));
$('bulletin-button').addEventListener('click', () => run(showBulletins));
$('new-session').addEventListener('click', () => run(() => showPlan((id) => run(() => refresh(id, 'working')))));
$('load-demo').addEventListener('click', () => run(async () => {
  const { id } = await request('demo', {});
  await refresh(id, 'working');
}));
$('publish').addEventListener('click', () => run(async () => {
  const { plan: { id }, generation, result } = current;
  const payload = { generation };
  if (result.basis?.mode === 'bulletin') payload.bulletin_id = result.basis.bulletin.id;
  const { body } = await request(sessionPath(id, '/releases'), payload);
  await refresh(id, 'releases');
  notice(`已取得交付件 v${body.number}。`);
}));
for (const tab of tabs) $(`${tab}-tab`).addEventListener('click', () => selectTab(tab));
new ResizeObserver(paintCurve).observe($('curve-figure'));
run(() => refresh());
