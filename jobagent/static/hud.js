/* ANIMUS // JOBAGENT — HUD front-end */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const md = t => DOMPurify.sanitize(marked.parse(t || ''));
const KINDS = {job:'Job', internship:'Internship', research:'Research', collaborator:'Postdoc host', hackathon:'Hackathon', funding:'Funding', fellowship:'Fellowship', startup_funding:'Startup funding', target:'Spontaneous target', intel:'Intel', conference:'Conference', event:'Event', trend:"What's hot"};
const KCOL = k => `var(--k-${KINDS[k] ? k : 'job'})`;
const STATUSES = ['new','saved','applying','applied','interview','offer','rejected','archived'];
const BOARD = ['saved','applying','applied','interview','offer','rejected'];
let S = {}, CATS = [], SECS = {}, view = localStorage.getItem('view') || 'home';
const today = () => new Date().toISOString().slice(0, 10);
const daysTo = d => d ? Math.round((new Date(d) - new Date(today())) / 864e5) : null;

async function api(p, opt = {}) {
  const o = {headers: {}};
  if (opt.body && !(opt.body instanceof FormData)) { o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(opt.body); }
  else if (opt.body) o.body = opt.body;
  o.method = opt.method || (opt.body ? 'POST' : 'GET');
  const r = await fetch(p, o); const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText); return j;
}
function toast(m) { const d = document.createElement('div'); d.className = 'toast'; d.textContent = m; document.body.appendChild(d); setTimeout(() => d.remove(), 3600); }
async function run(btn, fn) { const t = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<span class="ld"></span> PROCESSING'; try { return await fn(); } catch (e) { toast('⚠ ' + e.message); } finally { btn.disabled = false; btn.innerHTML = t; } }
const sc = v => v >= 70 ? 's-hi' : v >= 50 ? 's-md' : 's-lo';
const kindTag = k => `<span class="kind"><i style="background:${KCOL(k)}"></i>${esc(KINDS[k] || k)}</span>`;
const catName = id => (CATS.find(c => c.id === id) || {}).label || id;
const catChips = list => (list || []).map(id => `<span class="chip cat">${esc((CATS.find(c => c.id === id) || {}).glyph || '')} ${esc(catName(id))}</span>`).join('');
function dlTag(d) { if (!d) return ''; const n = daysTo(d); if (n < 0) return `<span class="dl">closed ${esc(d)}</span>`; return `<span class="dl ${n <= 7 ? 'hot' : ''}">⏱ ${n === 0 ? 'TODAY' : n + 'd'} · ${esc(d)}</span>`; }
function agentSel(id) { return `<select id="${id}"><option value="">Auto (best available)</option>${Object.entries(S.agents || {}).map(([k, a]) => `<option value="${k}" ${a.ready ? '' : 'disabled'}>${a.label}${a.ready ? '' : ' — offline'}</option>`).join('')}</select>`; }
function radarAgentSel(id) { const allowed = ['gemini', 'claude_cli', 'codex']; const cur = (S.settings && S.settings.routes && S.settings.routes.radar) || ''; return `<select id="${id}" style="width:165px;margin-right:6px"><option value="">Radar: Auto</option>${allowed.map(k => { const a = (S.agents || {})[k] || {label: k, ready: false}; return `<option value="${k}" ${k === cur ? 'selected' : ''} ${a.ready ? '' : 'disabled'}>${esc(a.label)}${a.ready ? '' : ' (offline)'}</option>`; }).join('')}</select>`; }
function out(el, text, agent) { el.innerHTML = `<div class="panel out"><div class="ptitle">Output <span class="right">by ${esc(agent || '?')} · <a href="#" class="cp">copy</a></span></div><div class="md">${md(text)}</div></div>`; el.querySelector('.cp').onclick = e => { e.preventDefault(); navigator.clipboard.writeText(text); toast('Copied'); }; }
async function jobOptions(blank = '— paste a description instead —') { const js = await api('/api/jobs?limit=120'); return `<option value="">${blank}</option>` + js.map(j => `<option value="${esc(j.id)}">${Math.round(j.score)} · ${esc(j.title)} — ${esc(j.company)}</option>`).join(''); }
const H = (title, sub = '', right = '') => `<div class="h"><h2 title="${esc(String(sub).replace(/<[^>]+>/g, ''))}">${title}</h2><div class="right">${right}</div></div>`;

/* ---------- chrome ---------- */
setInterval(() => { const d = new Date(); $('#clock').textContent = d.toLocaleDateString(undefined, {day: '2-digit', month: 'short'}).toUpperCase() + ' · ' + d.toLocaleTimeString(); }, 1000);
let _refAt = 0, GAME = null;
const AG_SHORT = {claude_cli: 'OPUS', codex: 'CODEX', gemini: 'GEMINI', anthropic_api: 'API'};
async function loadGame(prev) {
  const g = await api('/api/game'); const old = GAME; GAME = g;
  $('#lvl').textContent = 'LV ' + g.level; $('#rank').textContent = g.rank;
  $('#xpfill').style.width = Math.round(100 * (g.xp - g.level_from) / Math.max(1, g.level_to - g.level_from)) + '%';
  $('#xpnum').textContent = `${g.xp - g.level_from}/${g.level_to - g.level_from} XP`;
  $('#streak').textContent = g.streak ? `🔥${g.streak}` : '';
  $('#agentLights').innerHTML = Object.entries(g.energy).map(([k, e]) => `<span class="nrg" title="${esc(e.detail)}${e.budget ? ` · ${e.used}/${e.budget} calls today` : ''}">
    ${AG_SHORT[k] || k}<i class="nbar ${e.state}"><b style="width:${e.pct}%"></b></i></span>`).join('') + `<span class="nrg" title="Email"><i class="led ${S.email ? 'on' : 'off'}"></i>MAIL</span>`;
  if (old) { const gained = g.xp - old.xp; if (gained > 0) xpPop(`+${gained} XP`);
    if (g.level > old.level) xpPop(`LEVEL UP · ${g.rank}`, true);
    g.quests.forEach((q, i) => { if (q.done && old.quests[i] && !old.quests[i].done) xpPop(`QUEST COMPLETE · ${q.name} +${q.xp}`, true); }); }
}
function xpPop(text, big) { const d = document.createElement('div'); d.className = 'xppop' + (big ? ' big' : ''); d.textContent = text; document.body.appendChild(d); setTimeout(() => d.remove(), big ? 2600 : 1400); }
let _gameT; function gameSoon() { clearTimeout(_gameT); _gameT = setTimeout(() => loadGame(), 700); }
async function refresh(force) {
  if (!force && Date.now() - _refAt < 20000 && S.settings) return;
  [S, CATS, SECS] = await Promise.all([api('/api/state'), api('/api/categories'), api('/api/sections')]); _refAt = Date.now();
  $$('nav .badge').forEach(b => { const x = SECS[b.dataset.sec]; b.textContent = x && x.count ? x.count : ''; });
  const short = {claude_cli: 'OPUS', codex: 'ASTRA', gemini: 'GEMINI', anthropic_api: 'API'};
  $('#agentLights').innerHTML = Object.entries(S.agents).filter(([k, a]) => k !== 'anthropic_api' || a.ready).map(([k, a]) => `<span title="${esc(a.detail)}"><i class="led ${a.ready ? 'on' : 'off'}"></i>${short[k]}</span>`).join('') + `<span title="Email alerts"><i class="led ${S.email ? 'on' : 'off'}"></i>MAIL</span>`;
  const usOff = (S.settings.excluded_countries || []).includes('US'); const ut = $('#usToggle');
  ut.textContent = usOff ? 'US ✕ HIDDEN' : 'US ● SHOWN'; ut.className = 'geo ' + (usOff ? 'off' : 'on');
  ut.onclick = async () => { const ex = (S.settings.excluded_countries || []).filter(c => c !== 'US'); if (!usOff) ex.push('US'); await api('/api/settings', {body: {excluded_countries: ex}}); toast(usOff ? 'United States shown' : 'United States hidden'); go(view); };
  const mods = S.settings.modules || {};
  $('#grp-academia').style.display = mods.academia ? '' : 'none';
  $('#grp-community').style.display = mods.community ? '' : 'none';
  loadGame();
}
function go(v, arg) { view = v; localStorage.setItem('view', v); $$('nav button').forEach(b => b.classList.toggle('on', b.dataset.v === v)); closeDrawer(); $('#main').innerHTML = '<span class="ld"></span>'; V[v](arg); }
$$('nav button').forEach(b => b.onclick = () => go(b.dataset.v));
$$('nav .navh[data-fold]').forEach(h => { const g = h.nextElementSibling, k = 'fold:' + h.dataset.fold;
  const set = c => { g.classList.toggle('folded', c); h.classList.toggle('closed', c); try { localStorage.setItem(k, c ? '1' : ''); } catch (e) {} };
  set((() => { try { return localStorage.getItem(k) !== ''; } catch (e) { return true; } })());
  h.onclick = () => set(!g.classList.contains('folded')); });
const V = {};

/* ---------- item rows & drawer ---------- */

const AGENT_NAME = {claude_cli: 'Opus', claude: 'Opus', anthropic_api: 'Opus', codex: 'Codex', gemini: 'Gemini'};
const SOURCE_NAME = {openalex: 'OpenAlex', 'eu-funding': 'EU portal', devpost: 'Devpost', 'france-travail': 'France Travail', manual: 'you',
  arbeitnow: 'Arbeitnow', remotive: 'Remotive', remoteok: 'RemoteOK', jobicy: 'Jobicy', themuse: 'The Muse', greenhouse: 'Greenhouse', lever: 'Lever', ashby: 'Ashby'};
function addedBy(j, x) { const fb = (x.found_by || '').split('+')[0]; if (fb) return AGENT_NAME[fb] || fb;
  const s = j.source || ''; return s.startsWith('alert-') ? s.slice(6) + ' alert' : (SOURCE_NAME[s] || s); }
function verTag(x) { const v = x.verified; if (!v || !v.status) return '';
  const who = AGENT_NAME[v.by] || v.by || '?', d = (v.on || '').slice(5);
  if (v.status === 'open') return `<span class="vt ok" title="Verified open by ${esc(who)} on ${esc(v.on)}">✓ ${esc(who)} ${esc(d)}</span>`;
  if (['closed', 'not_found', 'mismatch'].includes(v.status)) return `<span class="vt bad" title="${esc(v.evidence || '')}">✕ ${esc(v.status.replace('_', ' '))} · ${esc(who)} ${esc(d)}</span>`;
  return `<span class="vt" title="${esc(v.evidence || '')}">? unconfirmed</span>`; }

const RAR = {legendary: 'LEGENDARY', epic: 'EPIC', rare: 'RARE', uncommon: 'UNCOMMON', common: 'COMMON'};
const fitOf = (j, x) => Math.round(x.fit ?? j.score);
function fitBadge(j, x, big) { const r = x.rarity || 'common'; return `<div class="score r-${r}${big ? ' big' : ''}" title="${RAR[r]} · fit ${fitOf(j, x)}/100 · rank ${Math.round(j.score)}"><b>${fitOf(j, x)}</b><small>${RAR[r]}</small></div>`; }
function itemRow(j) {
  const v = j.ai_verdict ? JSON.parse(j.ai_verdict) : null;
  const ex = JSON.parse(j.extra || '{}');
  const lc = ex.link_check;
  const flags = (ex.gem ? '<span class="gem" title="Priority lane">💎</span>' : '') + (ex.star ? '<span class="gem" title="Starred">★</span>' : '')
    + (lc && !lc.valid ? `<span class="warn" title="${esc(lc.reason)}">⚠</span>` : '');
  const cats = JSON.parse(j.categories || '[]').slice(0, 2);
  return `<div class="item r-${ex.rarity || 'common'}" data-id="${esc(j.id)}">${fitBadge(j, ex)}
  <div class="mid"><div class="t">${flags}${esc(j.title)}</div>
  <div class="m"><span class="by">${esc(addedBy(j, ex))}</span>${verTag(ex)} ${esc(j.company)}${j.location ? ' · ' + esc(j.location) : ''}${v ? ` · <b class="vd ${esc(v.verdict || '')}">${esc((v.verdict || '').toUpperCase())}</b>` : ''}${cats.length ? ' · ' + cats.map(c => esc(catName(c))).join(', ') : ''}</div></div>
  <div class="end">${dlTag(j.deadline)}${j.status !== 'new' ? `<span class="status">${esc(j.status)}</span>` : ''}</div></div>`;
}
const bindItems = (root = document) => root.querySelectorAll('.item').forEach(e => e.onclick = () => openItem(e.dataset.id));
function drawer(h) { const d = $('#drawer'); d.innerHTML = `<div class="row"><span class="right"><button class="btn ghost" onclick="closeDrawer()">✕ Close</button></span></div>` + h; d.classList.remove('hidden'); d.scrollTop = 0; }
function closeDrawer() { $('#drawer').classList.add('hidden'); }
async function openItem(id) {
  const j = await api('/api/job?id=' + encodeURIComponent(id)); const v = j.ai_verdict ? JSON.parse(j.ai_verdict) : null; const ex = JSON.parse(j.extra || '{}');
  const special = j.kind === 'collaborator' ? `<button class="btn gold" data-mail="postdoc_inquiry">✉ Draft postdoc inquiry</button>` : j.kind === 'target' ? `<button class="btn gold" data-mail="spontaneous">✉ Spontaneous application</button>` : '';
  const country = j.country || '';
  const m = JSON.parse(j.matched || '[]'), x = JSON.parse(j.missing || '[]');
  const lc = ex.link_check;
  const linkBadge = lc ? (lc.valid ? `<span class="chip" style="color:var(--good);border-color:var(--good);padding:1px 6px">✓ active</span>` : `<span class="chip miss" style="padding:1px 6px" title="${esc(lc.reason)}">⚠ ${esc(lc.status || 'broken')}: ${esc(lc.reason)}</span>`) : '';
  drawer(`<div class="row">${kindTag(j.kind)} ${dlTag(j.deadline)}</div><h2>${esc(j.title)}</h2>
  <div class="small" style="color:var(--ink2)">${esc(j.company)} · ${esc(j.location)} · <a href="${esc(j.url)}" target="_blank">open source ↗</a> ${linkBadge} <button class="btn ghost small" id="jchk" style="padding:1px 7px;font-size:11px;margin-left:6px" title="Verify if this link is alive and not expired">⟳ check link</button></div>
  <div class="prov"><span class="by">added by ${esc(addedBy(j, ex))}</span>${verTag(ex) || '<span class="vt">not yet model-verified</span>'}<button class="btn ghost" id="vwb">✓ Verify with AI</button><button class="btn ghost" id="tplb">⊕ Use as template</button><button class="btn gold" id="appb">🚀 Apply</button>
   ${ex.verified && ex.verified.evidence ? `<div class="small muted" style="flex-basis:100%">“${esc(ex.verified.evidence)}”</div>` : ''}</div>
  <div style="margin:8px 0">${catChips(JSON.parse(j.categories || '[]'))}</div>
  <div class="grid g4" style="margin-top:10px">
   <div><span class="lbl">Match</span><div class="score ${sc(j.score)}" style="width:70px">${Math.round(j.score)}</div></div>
   <div><span class="lbl">Status</span><select id="jst">${STATUSES.map(s => `<option ${s === j.status ? 'selected' : ''}>${s}</option>`).join('')}</select></div>
   <div><span class="lbl">Deadline</span><input type="date" id="jdl" value="${esc(j.deadline || '')}"></div>
   <div><span class="lbl">Applied on</span><input disabled value="${esc(j.applied_at || '—')}"></div></div>
  <div class="grid g2"><div><span class="lbl">Next action</span><input id="jna" value="${esc(j.next_action || '')}" placeholder="e.g. follow up with recruiter"></div>
   <div><span class="lbl">Next action date</span><input type="date" id="jnd" value="${esc(j.next_date || '')}"></div></div>
  <div style="margin-top:8px">${m.map(s => `<span class="chip">${esc(s)}</span>`).join('')}${x.map(s => `<span class="chip miss">${esc(s)}</span>`).join('')}</div>
  <div class="row" style="margin-top:8px"><button class="fb up ${ex.feedback === 'up' ? 'on' : ''}" id="fbu" title="More like this">👍</button><button class="fb down ${ex.feedback === 'down' ? 'on' : ''}" id="fbd" title="Less like this">👎</button>
   <span class="why">score: ${esc((ex.score_why || []).join(' · '))}</span></div>
  ${v ? `<div class="panel gold" style="margin-top:12px"><div class="ptitle" style="color:var(--gold)">Agent verdict <span class="right">${esc(v.agent)}</span></div><b>${esc((v.verdict || '').toUpperCase())} · fit ${esc(v.fit)}</b><p>${esc(v.why)}</p><p><i>Lead with:</i> ${esc(v.angle)}</p>${v.salary_estimate ? `<p>💶 <b>Salary estimate:</b> ${esc(v.salary_estimate)}</p>` : ''}${v.visa_note ? `<p>🛂 <b>Visa:</b> ${esc(v.visa_note)}</p>` : ''}${(v.red_flags || []).length ? `<p style="color:var(--warn)">⚠ ${esc(v.red_flags.join(' · '))}</p>` : ''}</div>` : ''}
  <span class="lbl">Agent</span>${agentSel('jag')}
  <div class="row" style="margin-top:10px">${special}<button class="btn gold" data-a="review">◈ Deep review</button>${country && !['EU', ''].includes(country) ? `<button class="btn" data-cb="${esc(country)}">🛂 ${esc(country)} visa · salary brief</button>` : ''}<button class="btn gold" data-a="cheatsheet">🎯 Cheat-Sheet</button><button class="btn gold" data-a="tailor_resume">📄 Tailored resume</button><button class="btn" data-a="salary_advisor">💶 Salary & CDI</button><button class="btn" data-a="cover_letter">Cover letter</button>
  <button class="btn" data-a="email">Outreach email</button><button class="btn" data-a="improve_resume">CV fixes</button><button class="btn" data-a="ats">ATS check</button><button class="btn" data-a="interview">Interview prep</button>${['job', 'internship', 'research', 'target', 'fellowship'].includes(j.kind) ? `<button class="btn" id="packb">▤ Light pack</button><button class="btn" onclick="go('interview','${esc(id)}')">◎ Mock interview</button>` : ''}<button class="btn" style="color:var(--warn);border-color:var(--warn);margin-left:auto" id="jdel" title="Delete this opportunity">🗑 Delete</button></div>
  <div id="rel"></div>
  <span class="lbl">Notes</span><textarea id="jn" style="min-height:60px">${esc(j.notes || '')}</textarea>
  <div id="jo"></div>
  ${j.docs.length ? `<span class="lbl">Generated for this item</span>${j.docs.map(d => `<a class="chip" onclick="openDoc(${d.id})">${esc(d.title)}</a>`).join('')}` : ''}
  <span class="lbl">Description</span><div class="small" style="white-space:pre-wrap;color:var(--ink2)">${esc(j.description)}</div>`);
  const save = async (body, msg) => { await api('/api/job/update', {body: {id, ...body}}); toast(msg); };
  $('#appb').onclick = e => run(e.target, async () => { const mode = S.settings.apply_mode || 'assisted';
    const r = await api('/api/apply', {body: {id, mode}});
    if (r.queued) { $('#jo').innerHTML = `<div class="panel gold out"><div class="ptitle" style="color:var(--gold)">✉ Application queued → ${esc(r.to)}</div><b>${esc(r.subject)}</b><p class="small">${esc(r.note)}</p><button class="btn ghost" onclick="go('tracker')">Open queue</button></div>`; }
    else { window.open(r.url, '_blank'); $('#jo').innerHTML = `<div class="panel gold out"><div class="ptitle" style="color:var(--gold)">${r.mode === 'web_assist' ? '🧭 Web assist' : '🚀 Ready to apply'}</div>${r.note ? `<p class="small">${esc(r.note)}</p>` : ''}
      <p class="small">The posting is open in a new tab. Your letter, email and CV edits are in:</p><div class="small" style="font-family:var(--mono)">${esc(r.pack_folder)}</div><button class="btn" id="rvp">Open folder</button></div>`;
      $('#rvp').onclick = () => api('/api/reveal', {body: {path: r.pack_folder}}); }
    gameSoon(); });
  $('#tplb').onclick = e => run(e.target, async () => { await api('/api/templates', {body: {job_id: id}}); toast('Added to your template jobs'); });
  $('#vwb').onclick = e => run(e.target, async () => { const r = await api('/api/verify/web', {body: {ids: [id]}}); const v = r.results[0] || {}; toast(`${(v.status || 'error').replace('_', ' ')} · ${AGENT_NAME[v.by] || v.by || ''}`); openItem(id); });
  $('#jst').onchange = () => save({status: $('#jst').value}, 'Status → ' + $('#jst').value);
  $('#jdl').onchange = () => save({deadline: $('#jdl').value}, 'Deadline saved');
  $('#jna').onchange = () => save({next_action: $('#jna').value}, 'Next action saved');
  $('#jnd').onchange = () => save({next_date: $('#jnd').value}, 'Next date saved');
  $('#jn').onchange = () => save({notes: $('#jn').value}, 'Notes saved');
  const fb = async val => { await api('/api/job/feedback', {body: {id, value: ex.feedback === val ? null : val}}); toast(val === 'up' ? 'Noted: more like this' : 'Noted: less like this'); openItem(id); };
  api('/api/job/related?id=' + encodeURIComponent(id)).then(r => { const el = $('#rel'); if (!el) return;
    el.innerHTML = (r.people.length ? `<span class="lbl">People finder · recruiters, hiring managers, alumni</span>${r.people.map(l => `<a class="chip" target="_blank" href="${esc(l.url)}">${esc(l.label)}</a>`).join('')}` : '')
      + (r.fellowships.length ? `<span class="lbl">Fellowships you could apply for with this host</span>${r.fellowships.map(f => `<a class="chip cat" onclick="openItem('${esc(f.id)}')">${esc(f.title.slice(0, 60))} ${f.deadline ? '· ' + esc(f.deadline) : ''}</a>`).join('')}` : ''); });
  if ($('#packb')) $('#packb').onclick = e => run(e.target, async () => { const r = await api('/api/pack', {body: {job_id: id, agent: $('#jag').value || undefined}});
    $('#jo').innerHTML = `<div class="panel gold out"><div class="ptitle" style="color:var(--gold)">▤ Pack saved <span class="right">${esc(r.agent)}</span></div><div class="small" style="font-family:var(--mono)">${esc(r.folder)}</div><div>${r.files.map(f => `<span class="chip">${esc(f)}</span>`).join('')}</div><div class="row" style="margin-top:8px"><button class="btn" id="rv">Open folder</button></div><div class="md out">${md(r.text)}</div></div>`;
    $('#rv').onclick = () => api('/api/reveal', {body: {path: r.folder}}); });
  $('#fbu').onclick = () => fb('up'); $('#fbd').onclick = () => fb('down');
  if ($('#jchk')) $('#jchk').onclick = e => run(e.target, async () => {
    const r = await api('/api/job/verify?id=' + encodeURIComponent(id));
    if (r.valid) {
      toast(`✓ Link verified: HTTP ${r.http_status} (${r.reason})`);
    } else {
      toast(`⚠ Link issue: ${r.status} (${r.reason})`);
    }
    openItem(id);
  });
  if ($('#jdel')) $('#jdel').onclick = async () => {
    if (!confirm(`Delete "${j.title}"?`)) return;
    await api('/api/job/delete', {body: {id}});
    toast('Deleted');
    closeDrawer();
    if (V[view]) V[view]();
  };
  $$('#drawer [data-mail]').forEach(b => b.onclick = e => run(e.target, async () => { const r = await api('/api/ai/email', {body: {kind: b.dataset.mail, job_id: id, agent: $('#jag').value || undefined}}); out($('#jo'), r.text, r.agent); }));
  $$('#drawer [data-cb]').forEach(b => b.onclick = e => run(e.target, async () => { const r = await api('/api/country_brief', {body: {country: b.dataset.cb}}); out($('#jo'), r.text, r.agent); }));
  $$('#drawer [data-a]').forEach(b => b.onclick = e => run(e.target, async () => {
    const a = b.dataset.a, ag = $('#jag').value || undefined;
    if (a === 'review') { await api('/api/job/review', {body: {id, agent: ag}}); return openItem(id); }
    const r = await api('/api/ai/' + a, {body: {job_id: id, agent: ag}});
    if (a === 'ats') return out($('#jo'), atsMd(r), r.agent); out($('#jo'), r.text, r.agent);
  }));
}
function atsMd(r) { const R = r.rules; return `## ATS score: ${R.score}/100${R.keyword_coverage != null ? ` · keyword coverage ${R.keyword_coverage}%` : ''}\n\n` + R.checks.map(c => `- ${c.ok ? '✅' : '❌'} **${c.name}**${c.ok ? '' : ': ' + c.tip}`).join('\n') + (R.missing ? `\n\n**Missing skills:** ${R.missing.join(', ') || 'none'}\n\n**JD terms not in resume:** ${(R.jd_terms_missing || []).join(', ')}` : '') + `\n\n---\n\n${r.ai || ''}`; }

/* ---------- COMMAND ---------- */
function ring(val, max, label) {
  const r = 46, c = 2 * Math.PI * r, f = Math.min(val / Math.max(max, 1), 1);
  return `<div class="ring"><svg width="120" height="120" viewBox="0 0 120 120" role="img" aria-label="${label}: ${val}">
  <g class="spin"><circle cx="60" cy="60" r="56" fill="none" stroke="rgba(63,224,255,.25)" stroke-dasharray="2 6"/></g>
  <circle cx="60" cy="60" r="${r}" fill="none" stroke="rgba(63,224,255,.12)" stroke-width="8"/>
  <circle cx="60" cy="60" r="${r}" fill="none" stroke="var(--cyan)" stroke-width="8" stroke-dasharray="${c * f} ${c}" transform="rotate(-90 60 60)" stroke-linecap="round"/>
  <text x="60" y="64" text-anchor="middle" fill="#fff" font-family="Orbitron" font-size="24" font-weight="700">${val}</text>
  <text x="60" y="82" text-anchor="middle" fill="var(--ink2)" font-family="Orbitron" font-size="7" letter-spacing="2">${label}</text></svg></div>`;
}
V.home = async () => {
  await refresh(); const c = S.counts || {}, r = S.resume;
  if (!S.settings.setup_done) return go('setup');
  const t = today(), end = new Date(Date.now() + 30 * 864e5).toISOString().slice(0, 10);
  const [cal, top, dk, stalled] = await Promise.all([
    api(`/api/calendar?start=${t}&end=${end}`), api('/api/jobs?section=jobs&limit=6&status=new&min_score=50'),
    api('/api/deck?scope=jobs&n=60'), api('/api/tracker/stalled?days=7').catch(() => [])]);
  const pipe = ['saved', 'applying', 'applied', 'interview', 'offer'].reduce((a, s) => a + (c[s] || 0), 0);
  const gems = dk.cards.filter(x => x._why_card === 'gem').length;
  $('#main').innerHTML = H('Command', '', `<button class="btn gold" id="scanBtn">⟳ Scan</button><button class="btn" id="radarBtn">◈ Radar</button><button class="btn ghost" id="t5b">⚑ Top 5</button>`) + `
  ${!r ? `<div class="panel gold" style="margin-bottom:16px">Upload your resume to start → <button class="btn gold" onclick="go('resume')">Upload</button></div>` : ''}
  <div class="grid g4">
   <div class="panel stat"><span>Strong matches</span><b>${S.top}</b></div>
   <div class="panel stat"><span>Pipeline</span><b>${pipe}</b></div>
   <div class="panel stat"><span>Applied · interviews</span><b>${(c.applied || 0) + (c.interview || 0) + (c.offer || 0)} · ${c.interview || 0}</b></div>
   <div class="panel stat"><span>Key deadlines ≤ 14 d</span><b style="color:var(--gold)" title="Saved/applying items, or strong matches (60+), due within 14 days">${cal.filter(x => x.type === 'deadline' && daysTo(x.date) <= 14 && (x.status !== 'new' || x.score >= 60)).length}</b></div>
  </div>
  <div class="panel gold hero" style="margin-top:16px"><div><div class="hero-n">${dk.remaining}</div><div class="hero-l">to review · ${gems ? `💎 ${gems} gems in the next deck` : 'swipe to triage'}</div></div>
   <div class="row right">${['jobs', ...(S.settings.modules?.academia ? ['academia'] : []), ...(S.settings.modules?.community ? ['community'] : [])].map(x => `<button class="btn ${x === 'jobs' ? 'gold' : 'ghost'}" data-scope="${x}">${x === 'jobs' ? '⇆ Swipe jobs' : x}</button>`).join('')}</div></div>
  <div class="grid g2" style="margin-top:16px"><div class="panel"><div class="ptitle">⚔ Daily quests <span class="right" id="qxp"></span></div><div id="quests"></div></div>
   <div class="panel"><div class="ptitle">🏆 Achievements <span class="right" id="achn"></span></div><div class="ach" id="ach"></div></div></div>
  ${stalled && stalled.length ? `<div class="panel" style="margin-top:16px"><div class="ptitle">⏱ No reply for 7+ days <span class="right"><a href="#" onclick="go('tracker');return false">tracker →</a></span></div>${stalled.slice(0, 4).map(s => `<a class="chip" onclick="openItem('${esc(s.id)}')">${esc(s.company)} · ${s.days_stalled}d</a>`).join('')}</div>` : ''}
  <div class="grid g3" style="margin-top:16px">
   <div class="panel span2"><div class="ptitle">Top matches <span class="right"><a href="#" onclick="go('tracks');return false">all →</a></span></div><div id="topj">${top.map(itemRow).join('') || '<p class="muted">Nothing yet. Run a scan.</p>'}</div></div>
   <div class="panel"><div class="ptitle">Upcoming <span class="right"><a href="#" onclick="go('calendar');return false">calendar →</a></span></div>
    ${cal.slice(0, 7).map(x => `<div class="check" style="cursor:pointer" ${x.job_id ? `onclick="openItem('${esc(x.job_id)}')"` : ''}><span class="dl ${daysTo(x.date) <= 7 ? 'hot' : ''}">${daysTo(x.date)}d</span><div style="color:#fff">${esc(x.title)}</div></div>`).join('') || '<p class="muted small">No dates yet.</p>'}
    <details style="margin-top:10px"><summary class="small">system log</summary><div class="term" id="log">${esc(S.scan.last || 'Idle.')}</div></details></div>
  </div><div id="t5o"></div>`;
  $$('.sec').forEach(e => e.onclick = () => go(e.dataset.s));
  $$('[data-scope]').forEach(b => b.onclick = () => go('discover', b.dataset.scope));
  const g = GAME || await api('/api/game');
  $('#qxp').textContent = `+${g.today_xp} XP today`;
  $('#quests').innerHTML = g.quests.map(q => `<div class="quest ${q.done ? 'done' : ''}"><div class="qt"><b>${q.done ? '✓' : '◇'} ${esc(q.name)}</b><span>${esc(q.goal)}</span><em>+${q.xp}</em></div>
    <div class="qbar"><i style="width:${Math.round(100 * q.progress / q.target)}%"></i></div><small>${q.progress}/${q.target}</small></div>`).join('');
  $('#achn').textContent = `${g.achievements.filter(a => a.unlocked).length}/${g.achievements.length}`;
  $('#ach').innerHTML = g.achievements.map(a => `<span class="badge3 ${a.unlocked ? 'on' : ''}" title="${esc(a.desc)}">${a.unlocked ? '★' : '☆'} ${esc(a.name)}</span>`).join('');
  $('#t5b').onclick = e => run(e.target, async () => { const r = await api('/api/top5', {body: {}}); out($('#t5o'), r.text, r.agent); });
  bindItems($('#topj'));
  $('#scanBtn').onclick = e => run(e.target, async () => { await api('/api/scan', {body: {}}); toast('Scan launched'); $('details').open = true; pollLog(); });
  $('#radarBtn').onclick = e => run(e.target, async () => { await api('/api/radar', {body: {}}); toast('Radar launched'); $('details').open = true; pollLog(); });
  if (S.scan.running) pollLog();
};

/* ---------- DISCOVER (swipe) ---------- */
let DECK = {cards: [], i: 0, scope: 'all', hist: [], stats: {like: 0, nope: 0, super: 0, later: 0}};
V.discover = async (scope) => {
  DECK = {cards: [], i: 0, scope: scope || (DECK.scope !== 'all' && DECK.scope) || 'jobs', hist: [], stats: {like: 0, nope: 0, super: 0, later: 0}};
  $('#main').innerHTML = H('Discover', 'Right = save · Left = dismiss · Up = star · Down = later. Keyboard: ← → ↑ ↓, Z = undo. Every swipe trains your scoring.',
    ['jobs', ...(S.settings.modules?.academia ? ['academia'] : []), ...(S.settings.modules?.community ? ['community'] : [])].map(x => `<button class="btn ${x === DECK.scope ? 'gold' : 'ghost'}" data-scope="${x}">${x}</button>`).join('')) + `
  <div class="deckwrap"><div class="deck" id="deck"></div>
   <div class="swipebar"><button class="sw nope" data-a="nope" title="Dismiss (←)">✕</button><button class="sw later" data-a="later" title="Later (↓)">↓</button>
    <button class="sw undo" id="undo" title="Undo (Z)">↺</button><button class="sw super" data-a="super" title="Star (↑)">★</button><button class="sw like" data-a="like" title="Save (→)">♥</button></div>
   <div class="deckstats small muted" id="dstats"></div></div>`;
  $$('[data-scope]').forEach(b => b.onclick = () => go('discover', b.dataset.scope));
  $$('.sw[data-a]').forEach(b => b.onclick = () => swipeTop(b.dataset.a));
  $('#undo').onclick = undoSwipe;
  await loadDeck();
};
async function loadDeck() {
  const d = await api(`/api/deck?scope=${DECK.scope}&n=30`);
  DECK.cards = d.cards; DECK.i = 0; DECK.remaining = d.remaining; renderDeck();
}
function cardHtml(j, k) {
  const ex = JSON.parse(j.extra || '{}'), v = j.ai_verdict ? JSON.parse(j.ai_verdict) : null;
  const cats = JSON.parse(j.categories || '[]').slice(0, 3);
  const tag = j._why_card === 'gem' ? '<span class="ctag gem">💎 priority lane</span>' : j._why_card === 'explore' ? '<span class="ctag">🧭 explore</span>' : '';
  const blurb = (v && v.why) || (j.description || '').replace(/\s+/g, ' ').slice(0, 260);
  return `<div class="card3 r-${ex.rarity || 'common'}" data-k="${k}" style="z-index:${100 - k};transform:translateY(${k * 10}px) scale(${1 - k * .04})">
    <div class="crow">${fitBadge(j, ex, true)}${tag}${v ? `<span class="ctag vd ${esc(v.verdict || '')}">${esc((v.verdict || '').toUpperCase())} ${esc(v.fit ?? '')}</span>` : ''}<span class="right">${kindTag(j.kind)}</span></div>
    <h3>${esc(j.title)}</h3>
    <div class="cmeta">${esc(j.company)}${j.location ? ' · ' + esc(j.location) : ''}</div>
    <div class="cprov"><span class="by">added by ${esc(addedBy(j, ex))}</span>${verTag(ex) || '<span class="vt">not yet model-verified</span>'}</div>
    <div class="cchips">${cats.map(c => `<span class="chip cat">${esc(catName(c))}</span>`).join('')}${j.salary ? `<span class="chip">${esc(j.salary)}</span>` : ''}${dlTag(j.deadline)}</div>
    <p class="cblurb">${esc(blurb)}</p>
    <div class="row cact"><a class="btn ghost" href="${esc(j.url)}" target="_blank" onclick="event.stopPropagation()">Open ↗</a><button class="btn ghost" onclick="event.stopPropagation();openItem('${esc(j.id)}')">Details</button></div>
    <div class="stamp like">SAVE</div><div class="stamp nope">NOPE</div><div class="stamp super">STAR</div><div class="stamp later">LATER</div></div>`;
}
function renderDeck() {
  const el = $('#deck'); if (!el) return;
  const rest = DECK.cards.slice(DECK.i, DECK.i + 3);
  const s = DECK.stats;
  $('#dstats').textContent = `${DECK.cards.length - DECK.i} in this deck · ${DECK.remaining} total · ♥ ${s.like} ★ ${s.super} ✕ ${s.nope} ↓ ${s.later}`;
  if (!rest.length) { el.innerHTML = `<div class="empty">Deck cleared ✓<br><button class="btn gold" style="margin-top:12px" id="more">Next deck</button></div>`; $('#more').onclick = loadDeck; return; }
  el.innerHTML = rest.map((j, k) => cardHtml(j, k)).reverse().join('');
  dragify(el.querySelector('.card3[data-k="0"]'));
}
function dragify(card) {
  if (!card) return; let sx = 0, sy = 0, dx = 0, dy = 0, down = false;
  const dir = () => Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'like' : 'nope') : (dy < 0 ? 'super' : 'later');
  card.onpointerdown = e => { if (e.target.closest('a,button')) return; down = true; sx = e.clientX; sy = e.clientY; card.setPointerCapture(e.pointerId); card.style.transition = 'none'; };
  card.onpointermove = e => { if (!down) return; dx = e.clientX - sx; dy = e.clientY - sy; card.style.transform = `translate(${dx}px,${dy}px) rotate(${dx / 18}deg)`;
    const d = dir(), strength = Math.min(1, Math.max(Math.abs(dx), Math.abs(dy)) / 120); card.querySelectorAll('.stamp').forEach(s => s.style.opacity = s.classList.contains(d) ? strength : 0); };
  card.onpointerup = () => { if (!down) return; down = false; card.style.transition = '';
    if (Math.max(Math.abs(dx), Math.abs(dy)) > 110) swipeTop(dir()); else { card.style.transform = ''; card.querySelectorAll('.stamp').forEach(s => s.style.opacity = 0); } dx = dy = 0; };
}
async function swipeTop(action) {
  const j = DECK.cards[DECK.i]; if (!j) return;
  const card = $('#deck .card3[data-k="0"]');
  if (card) { const off = {like: 'translate(140%,0) rotate(20deg)', nope: 'translate(-140%,0) rotate(-20deg)', super: 'translate(0,-140%)', later: 'translate(0,140%)'}[action];
    card.querySelector('.stamp.' + action).style.opacity = 1; card.style.transform = off; card.style.opacity = 0; }
  DECK.i++; DECK.stats[action]++; DECK.hist.push({id: j.id, action});
  setTimeout(renderDeck, 220);
  try { await api('/api/swipe', {body: {id: j.id, action}}); gameSoon(); } catch (e) { toast('⚠ ' + e.message); }
}
async function undoSwipe() {
  const h = DECK.hist.pop(); if (!h) return toast('Nothing to undo');
  await api('/api/swipe/undo', {body: {id: h.id}}); DECK.i = Math.max(0, DECK.i - 1); DECK.stats[h.action]--; renderDeck(); toast('Undone');
}
document.addEventListener('keydown', e => {
  if (view !== 'discover' || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName) || !$('#deck')) return;
  const m = {ArrowRight: 'like', ArrowLeft: 'nope', ArrowUp: 'super', ArrowDown: 'later'}[e.key];
  if (m) { e.preventDefault(); swipeTop(m); } else if (e.key === 'z' || e.key === 'Z') undoSwipe();
});

async function pollLog() { const l = await api('/api/scan/log'); const el = $('#log'); if (el) { el.textContent = l.log.join('\n'); el.scrollTop = 1e9; } if (l.running || (l.log.at(-1) || '').includes('started')) setTimeout(pollLog, 2500); }

/* ---------- TRACKS ---------- */
V.tracks = async (cat = '') => {
  await refresh();
  $('#main').innerHTML = H('Jobs · Tracks', 'Pure Industry & Research Jobs (CDI, CDD, internships, remote). Funding, grants, and events are separated in their own sections.', `<button class=\"btn gold\" onclick=\"go('discover','jobs')\">⇆ Swipe</button><button class="btn" onclick="apifyPanel()">⚡ Apify</button><button class="btn" id="cleanLinksBtn" title="Test links across active jobs, remove 404s and expired postings">🔗 Clean broken links</button> <button class="btn" id="addJ">+ Add manually</button>`) + `
  <div class="panel">  <div class="row"><select id="cat" style="width:260px"><option value="">All tracks</option>${CATS.filter(c => c.count).map(c => `<option value="${c.id}" ${c.id === cat ? 'selected' : ''}>${esc(c.glyph)} ${esc(c.label)} · ${c.count}</option>`).join('')}</select><input id="q" placeholder="Search title, company, skill, place…" style="flex:1;min-width:220px">
   <select id="kd" style="width:170px"><option value="">All job types</option>${Object.entries(KINDS).filter(([k]) => ['job', 'internship', 'research'].includes(k)).map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}</select>
   <select id="st" style="width:150px"><option value="">Any status</option>${STATUSES.map(s => `<option>${s}</option>`).join('')}</select>
   <select id="mn" style="width:120px"><option value="0">Any score</option><option value="40" selected>40+</option><option value="55">55+</option><option value="70">70+</option></select></div>
  <div id="jl" style="margin-top:8px"></div></div>
  <div class="panel" style="margin-top:16px"><div class="ptitle">⌕ Search-engine reconnaissance</div><p class="small muted">Google X-ray queries for ATS boards, LinkedIn, Indeed and hiring managers.</p><div id="xr"></div></div>`;
  const load = async () => { const js = await api(`/api/jobs?section=jobs&q=${encodeURIComponent($('#q').value)}&status=${$('#st').value}&min_score=${$('#mn').value}&category=${cat}&kind=${$('#kd').value}`); $('#jl').innerHTML = `<div class="small muted">${js.length} results</div>` + (js.map(itemRow).join('') || '<p class="muted">Nothing here yet. Run a scan or the AI radar, or lower the score filter.</p>'); bindItems($('#jl')); };
  $('#cat').onchange = () => { cat = $('#cat').value; load(); };
  $('#q').oninput = () => { clearTimeout(window._t); window._t = setTimeout(load, 300); }; ['#st', '#mn', '#kd'].forEach(s => $(s).onchange = load); load();
  if ($('#cleanLinksBtn')) $('#cleanLinksBtn').onclick = e => run(e.target, async () => {
    toast('Testing links across active opportunities (takes ~10–15 sec)...');
    const r = await api('/api/jobs/verify', {body: {prune: true, limit: 300, max_days: 60}});
    toast(`Checked ${r.scanned} links · Pruned ${r.pruned} broken/expired (${r.broken} broken, ${r.expired} expired, ${r.generic} generic)`);
    load();
  });
  $('#addJ').onclick = () => { drawer(`<h2>Add an opportunity</h2><span class="lbl">Title</span><input id="aT"><span class="lbl">Organisation</span><input id="aC"><span class="lbl">Location</span><input id="aL"><span class="lbl">URL</span><input id="aU"><span class="lbl">Deadline</span><input type="date" id="aDl"><span class="lbl">Description</span><textarea id="aD" style="min-height:200px"></textarea><div class="row" style="margin-top:10px"><button class="btn gold" id="aS">Add & score</button></div>`);
    $('#aS').onclick = e => run(e.target, async () => { const j = await api('/api/job/add', {body: {title: $('#aT').value, company: $('#aC').value, location: $('#aL').value, url: $('#aU').value, description: $('#aD').value}}); if ($('#aDl').value) await api('/api/job/update', {body: {id: j.id, deadline: $('#aDl').value}}); openItem(j.id); }); };
  const xr = await api('/api/xray'); $('#xr').innerHTML = xr.map(r => `<div style="margin:8px 0"><b style="color:#fff">${esc(r.role)}</b><br>${r.links.map(l => `<a class="chip" target="_blank" href="${esc(l.url)}">${esc(l.label)}</a>`).join('')}</div>`).join('');
};

/* ---------- SECTIONS (postdocs, fellowships, hackathons, events, contacts) ---------- */
const SECTION_META = {
  postdocs: {title: 'Postdoc Positions', sub: 'Academia · open postdoc and research-fellow posts. PIs to contact are under PI Contacts.', radar: ['collab'], sort: 'score'},
  fellowships: {title: 'Fellowships', sub: 'Academia · open fellowship calls. Use Fellowship Match to find a host.', radar: ['fellowship'], sort: 'deadline', extra: `<button class="btn" onclick="go('match')">⚯ Open Fellowship Match</button>`},
  grants: {title: 'Funding & Grants', sub: 'Academia & Startup funding · EU calls, EIC accelerator/pathfinder, Bpifrance, foundation grants, microgrants and startup innovation funding.', radar: ['indiv_funding', 'startup_funding'], sort: 'deadline'},
  hackathons: {title: 'Hackathons', sub: 'Online only: MedTech, health-AI and vibe-coding events.', radar: ['hackathon'], sort: 'deadline'},
  events: {title: 'Events · Webinars · Job Fairs', sub: 'Webinars, job fairs, career days, meetups and conferences. Dates go on your calendar.', radar: ['events', 'conference'], sort: 'deadline'},
  contacts: {title: 'Contacts', sub: 'Senior researchers (PIs) at European institutes in your field, as postdoc hosts and collaborators. Tick some to write LinkedIn notes.', contacts: true, sort: 'score'},
};
async function sectionView(sec) {
  const M = SECTION_META[sec]; await refresh();
  $('#main').innerHTML = H(M.title, M.sub, `<button class="btn gold" onclick="go('discover','${sec}')">⇆ Swipe</button>${M.extra || ''}${M.radar ? `<span style="display:inline-flex;align-items:center">${radarAgentSel('secRadarAgent')}<button class="btn gold" id="srad">◈ Search the web now</button></span>` : `<button class="btn gold" id="sref">⟳ Refresh from OpenAlex</button>`}`) + `
  <div class="panel"><div class="row"><input id="q" placeholder="Search…" style="flex:1;min-width:220px"><select id="so" style="width:170px"><option value="score">Best match</option><option value="deadline">Soonest deadline</option><option value="new">Newest</option></select>
   <select id="st" style="width:150px"><option value="">Any status</option>${STATUSES.map(s => `<option>${s}</option>`).join('')}</select>${M.contacts ? '<button class="btn" id="cn">⚭ LinkedIn notes for selected</button>' : ''}</div>
  <div id="jl" style="margin-top:8px"></div><div id="cno"></div></div>`;
  $('#so').value = M.sort;
  const load = async () => { const js = await api(`/api/jobs?section=${sec}&q=${encodeURIComponent($('#q').value)}&status=${$('#st').value}&sort=${$('#so').value}&limit=200`);
    $('#jl').innerHTML = `<div class="small muted">${js.length} items</div>` + (js.map(j => M.contacts ? `<div class="row"><input type="checkbox" value="${esc(j.id)}" style="margin:0 4px">${'<div style="flex:1">' + itemRow(j) + '</div>'}</div>` : itemRow(j)).join('') || '<p class="muted">Nothing yet. Use the search button above, or wait for the next scan.</p>'); bindItems($('#jl')); };
  $('#q').oninput = () => { clearTimeout(window._t); window._t = setTimeout(load, 300); }; $('#so').onchange = load; $('#st').onchange = load; load();
  if ($('#srad')) $('#srad').onclick = e => run(e.target, async () => { const ag = $('#secRadarAgent') ? $('#secRadarAgent').value : ''; await api('/api/radar', {body: {categories: M.radar, agent: ag || undefined}}); const agName = ag ? ((S.agents[ag] || {}).label || ag) : 'AI'; toast(`Searching the web with ${agName} (2–5 min). This list refreshes when done.`); const t = setInterval(async () => { const l = await api('/api/scan/log'); if ((l.log.at(-1) || '').includes('Radar done')) { clearInterval(t); if (view === sec) { load(); refresh(); toast('Radar finished'); } } }, 8000); });
  if ($('#sref')) $('#sref').onclick = e => run(e.target, async () => { const r = await api('/api/contacts/refresh', {body: {}}); toast(r.new + ' new contacts'); load(); });
  if ($('#cn')) $('#cn').onclick = e => run(e.target, async () => { const ids = $$('#jl input[type=checkbox]:checked').map(c => c.value); if (!ids.length) return toast('Tick some contacts first');
    const r = await api('/api/linkedin/notes', {body: {ids}}); $('#cno').innerHTML = `<div class="panel gold out"><div class="ptitle" style="color:var(--gold)">Connection notes <span class="right">${esc(r.agent)}</span></div>` + r.notes.map(n => `<div class="note"><b>${esc(n.name)}</b> <span class="small muted">${esc(n.company)}</span><div>${esc(n.note)}</div><a href="#" class="small" data-c="${esc(n.note)}">copy</a> · <a class="small" target="_blank" href="https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(n.name)}">find on LinkedIn ↗</a></div>`).join('') + '</div>';
    $$('#cno [data-c]').forEach(a => a.onclick = ev => { ev.preventDefault(); navigator.clipboard.writeText(a.dataset.c); toast('Copied'); }); });
}
['postdocs', 'fellowships', 'grants', 'hackathons', 'events', 'contacts'].forEach(sec => V[sec] = () => sectionView(sec));

/* ---------- WORLD MAP ---------- */
let WORLD = null;
function loadScript(src) { return new Promise((ok, bad) => { if ([...document.scripts].some(x => x.src === src)) return ok(); const e = document.createElement('script'); e.src = src; e.onload = ok; e.onerror = bad; document.head.appendChild(e); }); }
async function mapLibs() { await loadScript('https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js'); await loadScript('https://cdnjs.cloudflare.com/ajax/libs/topojson/3.0.2/topojson.min.js'); }
V.map = async (cat = '') => {
  await mapLibs();
  await refresh();
  $('#main').innerHTML = H('World Map', 'Every opportunity, located. Scroll, pinch, double-click or use the buttons (or + / − / 0 keys) to zoom; drag to pan. Pin size = count · colour = dominant type.',
    `<select id="msec" style="width:170px"><option value="">All sections</option>${['jobs', 'postdocs', 'fellowships', 'grants', 'hackathons', 'events', 'contacts'].map(x => `<option ${x === (window._msec || '') ? 'selected' : ''}>${x}</option>`).join('')}</select><select id="mcat" style="width:240px"><option value="">All tracks</option>${CATS.map(c => `<option value="${c.id}" ${c.id === cat ? 'selected' : ''}>${c.glyph} ${esc(c.label)} (${c.count})</option>`).join('')}</select>`) + `
  <div class="panel mapwrap"><div class="mapctl"><button id="zin" title="Zoom in">+</button><button id="zout" title="Zoom out">−</button><button id="zreset" title="Reset view">⟲</button><button class="txt" id="zeu" title="Zoom to Europe">EU</button><button class="txt" id="zfr" title="Zoom to France">FR</button></div><svg id="map" role="img" aria-label="World map of opportunities"></svg>
   <div class="legend small">${Object.entries(KINDS).map(([k, l]) => `<span class="kind"><i style="background:${KCOL(k)}"></i>${l}</span>`).join('')}</div>
   <div class="maplist" id="ml"><div class="ptitle">◍ Select a location</div><p class="small muted">Click a pin to list its opportunities. Scroll to zoom, drag to pan.</p><div id="virt"></div></div></div>`;
  $('#mcat').onchange = () => V.map($('#mcat').value); $('#msec').onchange = () => { window._msec = $('#msec').value; V.map($('#mcat').value); };
  if (!WORLD) WORLD = await fetch('https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json').then(r => r.json());
  const data = await api('/api/map?category=' + cat + '&section=' + (window._msec || ''));
  const svg = d3.select('#map'), box = $('#map').getBoundingClientRect(), w = Math.max(box.width, 320), h = Math.max(box.height, 300);
  svg.attr('viewBox', `0 0 ${w} ${h}`);
  const proj = d3.geoNaturalEarth1().fitExtent([[50, 20], [w - 10, h - 20]], {type: 'Sphere'}), path = d3.geoPath(proj);
  const g = svg.append('g');
  g.append('path').datum({type: 'Sphere'}).attr('class', 'sphere').attr('d', path);
  g.append('path').datum(d3.geoGraticule10()).attr('class', 'grat').attr('d', path);
  g.append('g').selectAll('path').data(topojson.feature(WORLD, WORLD.objects.countries).features).join('path').attr('class', 'country').attr('d', path);
  const fresh = Date.now() / 1000 - 2 * 86400;
  const pts = data.points.map(p => { const cnt = {}; p.items.forEach(i => cnt[i.kind] = (cnt[i.kind] || 0) + 1); const dom = Object.entries(cnt).sort((a, b) => b[1] - a[1])[0][0]; const [x, y] = proj([p.lon, p.lat]); return {...p, x, y, dom, cnt, top: Math.max(...p.items.map(i => i.score))}; });
  const pg = g.append('g');
  pg.selectAll('circle.pulse').data(pts.filter(p => p.top >= 60)).join('circle').attr('class', 'pulse').attr('cx', d => d.x).attr('cy', d => d.y).attr('stroke', d => KCOL(d.dom));
  pg.selectAll('circle.pin').data(pts).join('circle').attr('class', 'pin').attr('cx', d => d.x).attr('cy', d => d.y)
    .attr('r', d => 4 + Math.sqrt(d.items.length) * 2.2).attr('fill', d => KCOL(d.dom))
    .on('mousemove', (ev, d) => { const t = $('#tip'); t.innerHTML = `<b style="color:#fff">${esc(d.place)}</b> · ${d.items.length} items<br>${Object.entries(d.cnt).map(([k, n]) => `${kindTag(k)} ${n}`).join('<br>')}<br><span class="muted">best match ${Math.round(d.top)}</span>`; t.style.left = ev.clientX + 14 + 'px'; t.style.top = ev.clientY + 14 + 'px'; t.classList.remove('hidden'); })
    .on('mouseleave', () => $('#tip').classList.add('hidden'))
    .on('click', (ev, d) => { $('#ml').innerHTML = `<div class="ptitle">◍ ${esc(d.place)} <span class="right">${d.items.length}</span></div><button class="btn" id="mcb" style="margin-bottom:8px">🛂 Visa · salary · relocation brief</button>` + d.items.sort((a, b) => b.score - a.score).map(i => `<div class="check" style="cursor:pointer" data-id="${esc(i.id)}"><span class="score ${sc(i.score)}" style="min-width:40px;font-size:13px;padding:4px">${Math.round(i.score)}</span><div><div style="color:#fff">${esc(i.title)}</div><div class="small">${kindTag(i.kind)} · ${esc(i.company)} ${dlTag(i.deadline)}</div></div></div>`).join(''); $$('#ml [data-id]').forEach(e => e.onclick = () => openItem(e.dataset.id));
      $('#mcb').onclick = e2 => run(e2.target, async () => { const r = await api('/api/country_brief', {body: {country: d.place}}); drawer(`<h2>${esc(d.place)}</h2><div id="cbo"></div>`); out($('#cbo'), r.text, r.agent); }); });
  pg.selectAll('text').data(pts.slice(0, 12)).join('text').attr('x', d => d.x + 9).attr('y', d => d.y + 4).attr('fill', 'var(--ink2)').attr('font-size', 10).attr('font-family', 'Rajdhani').attr('pointer-events', 'none').text(d => `${d.place} ${d.items.length}`);
  const zoom = d3.zoom().scaleExtent([1, 40]).on('zoom', e => { g.attr('transform', e.transform); const k = e.transform.k;
    pg.selectAll('circle.pin').attr('r', d => (4 + Math.sqrt(d.items.length) * 2.2) / Math.sqrt(k)).attr('stroke-width', 1.5 / k);
    pg.selectAll('text').attr('font-size', 10 / k).attr('x', d => d.x + 9 / k).attr('y', d => d.y + 4 / k); g.selectAll('.country').attr('stroke-width', .5 / k); });
  svg.call(zoom).on('dblclick.zoom', null).on('dblclick', ev => svg.transition().duration(500).call(zoom.scaleBy, 2, d3.pointer(ev)));
  const focus = (lon1, lat1, lon2, lat2) => { const [[x0, y0], [x1, y1]] = [proj([lon1, lat2]), proj([lon2, lat1])]; const k = Math.min(40, 0.9 / Math.max((x1 - x0) / w, (y1 - y0) / h));
    svg.transition().duration(750).call(zoom.transform, d3.zoomIdentity.translate(w / 2, h / 2).scale(k).translate(-(x0 + x1) / 2, -(y0 + y1) / 2)); };
  $('#zin').onclick = () => svg.transition().duration(350).call(zoom.scaleBy, 1.8);
  $('#zout').onclick = () => svg.transition().duration(350).call(zoom.scaleBy, 1 / 1.8);
  $('#zreset').onclick = () => svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
  $('#zeu').onclick = () => focus(-11, 35, 30, 61); $('#zfr').onclick = () => focus(-5, 42, 8.5, 51.3);
  document.onkeydown = e => { if (view !== 'map' || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return; if (e.key === '+' || e.key === '=') $('#zin').click(); if (e.key === '-') $('#zout').click(); if (e.key === '0') $('#zreset').click(); };
  $('#virt').innerHTML = `<div class="ptitle" style="margin-top:12px">⌁ Remote / Online <span class="right">${data.virtual_count}</span></div>` + data.virtual.slice(0, 40).map(i => `<div class="check" style="cursor:pointer" data-id="${esc(i.id)}"><span class="score ${sc(i.score)}" style="min-width:40px;font-size:13px;padding:4px">${Math.round(i.score)}</span><div><div style="color:#fff">${esc(i.title)}</div><div class="small">${kindTag(i.kind)} · ${esc(i.company)}</div></div></div>`).join('');
  $$('#virt [data-id]').forEach(e => e.onclick = () => openItem(e.dataset.id));
};

/* ---------- TRACKER (kanban) ---------- */
async function applyQueuePanel() {
  const q = await api('/api/apply/queue'); if (!q.queue.length && q.mode !== 'email_auto') return '';
  return `<div class="panel" style="margin-bottom:14px"><div class="ptitle">✉ Application emails <span class="right">${q.sent_today}/${q.limit} sent today · mode: ${esc(q.mode)}</span></div>
   ${q.queue.map(x => `<div class="check small"><span class="status">${esc(x.status)}</span><b style="color:#fff">${esc(x.title || '')}</b><span class="muted">${esc(x.company || '')} → ${esc(x.to_addr)}</span>
     <span class="right">${x.status === 'queued' ? `<a href="#" data-cq="${x.id}">cancel</a>` : esc(x.error || '')}</span></div>`).join('') || '<p class="small muted">Nothing queued.</p>'}
   <div class="row" style="margin-top:8px"><button class="btn" id="sendq">Send queued now (within today's limit)</button></div></div>`;
}
V.tracker = async () => {
  const [items, stalled, aq] = await Promise.all([
    api('/api/tracker'),
    api('/api/tracker/stalled?days=7').catch(() => []), applyQueuePanel().catch(() => '')
  ]);
  $('#main').innerHTML = H('Application Tracker', 'Drag cards between columns. Applied dates are logged automatically. Open a card to set deadlines and next actions.',
    `<button class="btn gold" id="trkSync">✉ Auto-Track Inbox</button> <button class="btn" id="trkDedup">⚡ Deduplicate</button> <button class="btn" id="trkVerify">🔗 Verify Links</button> <button class="btn" id="trkClean">🧹 Cleanup Stale</button>`) + `
  ${stalled && stalled.length ? `<div class="panel gold" style="margin-bottom:16px;background:rgba(255,183,3,.07);border-color:var(--gold)"><div class="ptitle" style="color:var(--gold)">⏱ Watchdog: ${stalled.length} Application${stalled.length > 1 ? 's' : ''} Stalled &gt; 7 Days without Response</div>
  <p class="small muted">Send a polite, value-driven follow-up note highlighting your relevant research/industry match to prompt a response.</p>
  <div class="grid g2" style="margin-top:8px">${stalled.map(s => `<div class="card" style="border-left:3px solid var(--gold);display:flex;flex-direction:column;justify-content:space-between"><div><b style="color:#fff">${esc(s.company)}</b> — ${esc(s.title)}<div class="small muted">Applied on ${esc(s.applied_at || '')} (${s.days_stalled} days ago)</div></div><div class="row" style="margin-top:8px"><button class="btn small gold" data-fu="${esc(s.id)}">✉ Draft Follow-Up Note</button><button class="btn small ghost" onclick="openItem('${esc(s.id)}')">View Job</button></div></div>`).join('')}</div></div>` : ''}
  ${aq}<div class="kanban">${BOARD.map(s => `<div class="col" data-s="${s}"><h4>${s}<span>${items.filter(i => i.status === s).length}</span></h4>
   ${items.filter(i => i.status === s).map(i => `<div class="card" draggable="true" data-id="${esc(i.id)}" style="border-left-color:${KCOL(i.kind)}"><b>${esc(i.title)}</b><span class="small muted">${esc(i.company)}</span><div>${dlTag(i.deadline)}</div>${i.next_action ? `<div class="small" style="color:var(--gold)">→ ${esc(i.next_action)} ${esc(i.next_date || '')}</div>` : ''}${i.applied_at ? `<div class="small muted">applied ${esc(i.applied_at)}</div>` : ''}</div>`).join('')}</div>`).join('')}</div>
  ${items.length ? '' : '<p class="muted" style="margin-top:12px">Empty. Open any opportunity and set its status to “saved” to start tracking it.</p>'}`;
  $$('[data-fu]').forEach(b => b.onclick = () => draftFollowUp(b.dataset.fu));
  $$('[data-cq]').forEach(a => a.onclick = async ev => { ev.preventDefault(); await api('/api/apply/cancel', {body: {id: a.dataset.cq}}); toast('Cancelled'); V.tracker(); });
  if ($('#sendq')) $('#sendq').onclick = e => run(e.target, async () => { const r = await api('/api/apply/send', {body: {}}); toast(`${r.sent} sent · ${r.left_today} left today`); V.tracker(); });
  if ($('#trkSync')) $('#trkSync').onclick = e => run(e.target, async () => {
    const res = await api('/api/tracker/sync');
    if (!res.ok) return toast('Tracker: ' + (res.error || 'Failed'));
    toast(`Checked ${res.checked} emails · ${res.matched} updates found`);
    V.tracker();
  });
  if ($('#trkDedup')) $('#trkDedup').onclick = e => run(e.target, async () => {
    const res = await api('/api/jobs/dedup');
    toast(`Deduplicated: removed ${res.deleted_duplicates} duplicate(s)`);
    V.tracker();
  });
  if ($('#trkVerify')) $('#trkVerify').onclick = e => run(e.target, async () => {
    toast('Testing links across active opportunities...');
    const r = await api('/api/jobs/verify', {body: {prune: true, limit: 300, max_days: 60}});
    toast(`Checked ${r.scanned} links · Pruned ${r.pruned} broken/expired`);
    V.tracker();
  });
  if ($('#trkClean')) $('#trkClean').onclick = e => run(e.target, async () => {
    if (!confirm('Clean up rejected applications older than 30 days and expired stale jobs?')) return;
    const res = await api('/api/jobs/cleanup');
    toast(`Cleanup: deleted ${res.total} stale item(s)`);
    V.tracker();
  });
  $$('.card').forEach(c => { c.ondragstart = e => e.dataTransfer.setData('id', c.dataset.id); c.onclick = () => openItem(c.dataset.id); });
  $$('.col').forEach(col => { col.ondragover = e => { e.preventDefault(); col.classList.add('over'); }; col.ondragleave = () => col.classList.remove('over');
    col.ondrop = async e => { e.preventDefault(); col.classList.remove('over'); await api('/api/job/update', {body: {id: e.dataTransfer.getData('id'), status: col.dataset.s}}); toast('Moved → ' + col.dataset.s); V.tracker(); }; });
};

/* ---------- CALENDAR ---------- */
let calMonth = new Date(); calMonth.setDate(1);
V.calendar = async () => {
  const y = calMonth.getFullYear(), m = calMonth.getMonth(), first = new Date(y, m, 1), startOff = (first.getDay() + 6) % 7;
  const start = new Date(y, m, 1 - startOff), cells = [...Array(42)].map((_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const items = await api(`/api/calendar?start=${iso(cells[0])}&end=${iso(cells[41])}`);
  const by = {}; items.forEach(i => (by[i.date] = by[i.date] || []).push(i));
  $('#main').innerHTML = H('Deadline Calendar', 'Deadlines, next actions, applications and your own events. Reminders are emailed 7 days and 1 day before.',
    `<button class="btn ghost" id="pm">◂</button> <b style="font:700 14px Orbitron;letter-spacing:.15em;margin:0 10px">${first.toLocaleString(undefined, {month: 'long', year: 'numeric'}).toUpperCase()}</b> <button class="btn ghost" id="nm">▸</button> <a class="btn gold" href="/api/calendar.ics" download style="text-decoration:none">⇩ Export .ics</a>`) + `
  <div class="grid" style="grid-template-columns:1fr 300px"><div class="panel"><div class="cal">${['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'].map(d => `<div class="dow">${d}</div>`).join('')}
   ${cells.map(d => { const k = iso(d); return `<div class="day ${d.getMonth() !== m ? 'other' : ''} ${k === today() ? 'today' : ''}" data-d="${k}"><div class="d">${d.getDate()}</div>${(by[k] || []).slice(0, 4).map(i => `<span class="ev ${esc(i.type)} ${i.done ? 'done' : ''}" title="${esc(i.title + ' — ' + (i.sub || ''))}">${esc(i.title)}</span>`).join('')}${(by[k] || []).length > 4 ? `<span class="small muted">+${by[k].length - 4} more</span>` : ''}</div>`; }).join('')}</div></div>
   <div><div class="panel gold"><div class="ptitle" style="color:var(--gold)">+ Add event</div><span class="lbl">Title</span><input id="et" placeholder="Interview with Siemens"><span class="lbl">Date</span><input type="date" id="ed" value="${today()}"><span class="lbl">Time</span><input type="time" id="eti">
    <span class="lbl">Type</span><select id="ek"><option value="interview">Interview</option><option value="event">Event</option><option value="deadline">Deadline</option><option value="call">Call</option><option value="conference">Conference</option></select><span class="lbl">Notes</span><input id="en">
    <div class="row" style="margin-top:10px"><button class="btn gold" id="eb">Add</button></div></div>
    <div class="panel" style="margin-top:16px" id="dayp"><div class="ptitle">Day detail</div><p class="small muted">Click a day.</p></div></div></div>`;
  $('#pm').onclick = () => { calMonth.setMonth(calMonth.getMonth() - 1); V.calendar(); }; $('#nm').onclick = () => { calMonth.setMonth(calMonth.getMonth() + 1); V.calendar(); };
  $('#eb').onclick = e => run(e.target, async () => { await api('/api/events', {body: {title: $('#et').value, date: $('#ed').value, time: $('#eti').value, kind: $('#ek').value, notes: $('#en').value}}); toast('Event added'); V.calendar(); });
  $$('.day').forEach(d => d.onclick = () => { const k = d.dataset.d, L = by[k] || []; $('#ed').value = k;
    $('#dayp').innerHTML = `<div class="ptitle">${k}</div>` + (L.map((i, n) => `<div class="check"><span class="ev ${esc(i.type)}" style="flex:none">${esc(i.type)}</span><div style="flex:1;cursor:pointer" data-n="${n}"><div style="color:#fff">${esc(i.title)}</div><div class="small muted">${esc(i.time || '')} ${esc(i.sub || '')}</div></div>${i.event_id ? `<a href="#" data-del="${i.event_id}">✕</a>` : ''}</div>`).join('') || '<p class="small muted">Nothing on this day.</p>');
    $$('#dayp [data-n]').forEach(e => e.onclick = () => { const it = L[+e.dataset.n]; if (it.job_id) openItem(it.job_id); });
    $$('#dayp [data-del]').forEach(e => e.onclick = async ev => { ev.preventDefault(); await api('/api/events?id=' + e.dataset.del, {method: 'DELETE'}); V.calendar(); }); });
};

/* ---------- SKILLS ---------- */
function radar(sk) {
  const n = sk.length, R = 120, cx = 160, cy = 150; if (n < 3) return '';
  const pt = (i, v) => { const a = -Math.PI / 2 + 2 * Math.PI * i / n; return [cx + Math.cos(a) * R * v, cy + Math.sin(a) * R * v]; };
  const poly = f => sk.map((s, i) => pt(i, f(s)).join(',')).join(' ');
  return `<svg viewBox="0 0 320 300" width="100%" role="img" aria-label="Skill radar: your level vs target vs market demand">
   ${[.25, .5, .75, 1].map(r => `<polygon points="${sk.map((_, i) => pt(i, r).join(',')).join(' ')}" fill="none" stroke="rgba(63,224,255,.15)"/>`).join('')}
   ${sk.map((_, i) => `<line x1="${cx}" y1="${cy}" x2="${pt(i, 1)[0]}" y2="${pt(i, 1)[1]}" stroke="rgba(63,224,255,.12)"/>`).join('')}
   <polygon points="${poly(s => s.demand / 100)}" fill="rgba(57,135,229,.12)" stroke="var(--k-job)" stroke-width="2"/>
   <polygon points="${poly(s => s.target / 5)}" fill="none" stroke="var(--gold)" stroke-width="2" stroke-dasharray="4 3"/>
   <polygon points="${poly(s => s.level / 5)}" fill="rgba(63,224,255,.18)" stroke="var(--cyan)" stroke-width="2"/>
   ${sk.map((s, i) => { const [x, y] = pt(i, 1.13); return `<text x="${x}" y="${y}" fill="var(--ink2)" font-size="9" font-family="Rajdhani" text-anchor="middle">${esc(s.name.slice(0, 16))}</text>`; }).join('')}</svg>
   <div class="row small"><span class="kind"><i style="background:var(--cyan)"></i>Your level</span><span class="kind"><i style="background:var(--gold)"></i>Target</span><span class="kind"><i style="background:var(--k-job)"></i>Market demand</span></div>`;
}
V.skills = async () => {
  const [sk, g] = await Promise.all([api('/api/skills'), api('/api/gaps')]);
  $('#main').innerHTML = H('Skill Ranker', 'Ranked by market demand across your matched opportunities × the gap to your target. Click the pips to rate yourself; progress is logged over time.') + `
  <div class="grid" style="grid-template-columns:1.5fr 1fr">
   <div class="panel"><div class="ptitle">⬡ Priority ranking <span class="right">demand · your level / target · priority</span></div>
    <div class="skrow small muted" style="border:0"><span>#</span><span>Skill</span><span>Market demand</span><span>Level (pips) · target ◇</span><span>Priority</span></div>
    ${sk.map((s, i) => `<div class="skrow" data-n="${esc(s.name)}"><span class="rank">${String(i + 1).padStart(2, '0')}</span><span style="color:#fff">${esc(s.name)} ${s.in_resume ? '' : '<span class="chip miss">not in CV</span>'}</span>
     <div class="bar" title="demand ${s.demand}"><i class="d" style="width:${s.demand}%"></i></div>
     <div class="pips">${[1, 2, 3, 4, 5].map(p => `<i data-l="${p}" class="${p <= s.level ? 'on' : ''} ${p === s.target ? 'tgt' : ''}" title="${p === s.target ? 'target' : 'set level ' + p}"></i>`).join('')}</div>
     <b style="font-family:Orbitron;color:${s.priority >= 50 ? 'var(--red)' : s.priority >= 25 ? 'var(--gold)' : 'var(--ink2)'}">${s.priority}</b></div>`).join('') || '<p class="muted">Run a scan first so there is market data to rank.</p>'}
    <div class="row" style="margin-top:10px"><input id="nsk" placeholder="Add a skill to track…" style="flex:1"><button class="btn" id="nskb">Track</button></div></div>
   <div><div class="panel">${radar(sk.slice(0, 8))}</div>
    <div class="panel gold" style="margin-top:16px"><div class="ptitle" style="color:var(--gold)">◈ Train</div><span class="lbl">Skill</span><input id="ts" value="${esc((sk[0] || {}).name || '')}">
     <div class="row"><select id="tm" style="flex:1"><option value="quiz">Quiz</option><option value="lesson">Lesson</option><option value="project">Portfolio project</option><option value="interview">Interview Qs</option></select><select id="tl" style="flex:1"><option>beginner</option><option selected>intermediate</option><option>advanced</option></select></div>
     <div class="row" style="margin-top:10px"><button class="btn gold" id="tb">Train me</button><button class="btn" id="db">Dev plan</button><label class="row small"><input type="checkbox" id="dc"> council</label></div></div></div></div>
  <div id="to"></div><div id="gradebox" class="hidden panel" style="margin-top:12px"><span class="lbl">Your answers</span><textarea id="ta"></textarea><button class="btn" id="tg" style="margin-top:6px">Grade</button><div id="tgo"></div></div>`;
  $$('.skrow[data-n] .pips i').forEach(p => { p.onclick = async () => { const row = p.closest('.skrow'), name = row.dataset.n, s = sk.find(x => x.name === name); await api('/api/skills', {body: {name, level: +p.dataset.l, target: s.target}}); toast(`${name} → level ${p.dataset.l}`); V.skills(); };
    p.oncontextmenu = async e => { e.preventDefault(); const name = p.closest('.skrow').dataset.n, s = sk.find(x => x.name === name); await api('/api/skills', {body: {name, level: s.level, target: +p.dataset.l}}); toast(`${name} target → ${p.dataset.l}`); V.skills(); }; });
  $('#nskb').onclick = async () => { if (!$('#nsk').value) return; await api('/api/skills', {body: {name: $('#nsk').value, level: 1, target: 4}}); V.skills(); };
  let last = '';
  $('#tb').onclick = e => run(e.target, async () => { const r = await api('/api/ai/train', {body: {skill: $('#ts').value, mode: $('#tm').value, level: $('#tl').value}}); last = r.text; out($('#to'), $('#tm').value === 'quiz' ? r.text.split(/###\s*Answers/i)[0] : r.text, r.agent); $('#gradebox').classList.remove('hidden'); });
  $('#tg').onclick = e => run(e.target, async () => { const r = await api('/api/ai/grade', {body: {skill: $('#ts').value, exercise: last, answers: $('#ta').value}}); out($('#tgo'), r.text, r.agent); });
  $('#db').onclick = e => run(e.target, async () => { const r = await api('/api/ai/dev_plan', {body: {weeks: 8, hours: 8, council: $('#dc').checked}}); out($('#to'), r.text, r.agent); });
};

/* ---------- FELLOWSHIP MATCHMAKER ---------- */
V.match = async () => {
  const m = await api('/api/matchmaker');
  $('#main').innerHTML = H('Fellowship Match', 'Open fellowships paired with European PIs who could host you, based on eligible host countries and topic overlap. Costs no AI tokens.') +
  (m.map(x => `<div class="panel" style="margin-bottom:14px"><div class="ptitle"><a href="#" data-id="${esc(x.fellowship.id)}" style="color:var(--cyan)">✧ ${esc(x.fellowship.title)}</a><span class="right">${dlTag(x.fellowship.deadline)}</span></div>
    <div class="small muted">${esc(x.fellowship.company)} · eligible hosts: ${esc(x.host_countries.join(', '))}</div>
    ${x.hosts.map(h => `<div class="check"><span class="score ${sc(h.fit)}" style="min-width:42px;font-size:13px;padding:4px">${h.fit}</span><div style="flex:1;cursor:pointer" data-id="${esc(h.id)}"><b style="color:#fff">${esc(h.name)}</b><div class="small muted">${esc(h.inst)} · ${esc(h.country)}</div></div><button class="btn" data-pi="${esc(h.id)}" data-f="${esc(x.fellowship.title)}">✉ Joint-application email</button></div>`).join('') || '<p class="small muted">No matching PIs in eligible countries yet. More arrive with each scan.</p>'}
    <div class="pmo"></div></div>`).join('') || '<div class="panel"><p class="muted">No open fellowships tracked yet. Run a scan or the AI radar.</p></div>');
  $$('[data-id]').forEach(e => e.onclick = ev => { ev.preventDefault(); openItem(e.dataset.id); });
  $$('[data-pi]').forEach(b => b.onclick = e => run(e.target, async () => { const r = await api('/api/ai/email', {body: {kind: 'postdoc_inquiry', job_id: b.dataset.pi, context: `Propose co-applying for: ${b.dataset.f}, with them as host supervisor.`}}); out(b.closest('.panel').querySelector('.pmo'), r.text, r.agent); }));
};

/* ---------- LINKEDIN STUDIO ---------- */
V.linkedin = async () => {
  const [pis, tg, intel, hot] = await Promise.all([api('/api/jobs?kind=collaborator&limit=30'), api('/api/jobs?kind=target&limit=20'), api('/api/jobs?kind=intel&limit=10'), api('/api/jobs?kind=trend&limit=12&sort=new')]);
  const people = [...pis, ...tg];
  $('#main').innerHTML = H('LinkedIn Studio', 'Drafts only. Nothing is posted for you: copy, edit and post yourself.') + `
  <div class="panel" style="margin-bottom:16px"><div class="ptitle" style="color:#e66767">🔥 What's hot in your field <span class="right"><button class="btn" id="hotb">⟳ Refresh (web search)</button></span></div>
   ${hot.map(h => `<div class="hot"><div class="row"><b style="color:#fff">${esc(h.title)}</b><span class="small muted">${esc(h.company)} · ${esc(h.posted_at || '')}</span><span class="right"><a class="small" target="_blank" href="${esc(h.url)}">source ↗</a> · <a href="#" class="small" data-hot="${esc(h.title + ': ' + h.description.slice(0, 500))}">✎ draft a post on this</a></span></div><div class="small" style="white-space:pre-wrap;color:var(--ink2)">${esc(h.description.slice(0, 400))}</div></div>`).join('') || '<p class="small muted">Nothing yet. Press Refresh to search LinkedIn and industry news for trending topics.</p>'}</div>
  <div class="grid g2"><div class="panel"><div class="ptitle">✎ Post drafter</div><span class="lbl">Post type</span><select id="lk"><option value="research_highlight">Research highlight</option><option value="open_to_work">Open to opportunities</option><option value="news_take">Take on industry news</option><option value="event">Event / hackathon takeaways</option><option value="lesson">Lessons learned</option></select>
    <span class="lbl">Context (optional)</span><textarea id="lc" style="min-height:70px" placeholder="paper, event, or pick a news item →"></textarea>
    ${intel.length ? `<span class="lbl">…or react to intel</span><select id="li"><option value="">—</option>${intel.map(i => `<option value="${esc(i.title + ' — ' + i.company + ': ' + i.description.slice(0, 300))}">${esc(i.title.slice(0, 80))}</option>`).join('')}</select>` : ''}
    <div class="row"><div style="flex:1"><span class="lbl">Language</span><select id="ll"><option>English</option><option>French</option></select></div></div>
    <div class="row" style="margin-top:10px"><button class="btn gold" id="lb">Draft post</button><button class="btn" id="lp">Optimise my profile</button><a class="btn ghost" target="_blank" href="https://www.linkedin.com/feed/" style="text-decoration:none">Open LinkedIn ↗</a></div></div>
  <div class="panel"><div class="ptitle">⚭ Connection notes <span class="right">one AI call for all selected</span></div><p class="small muted">Tick PIs or target companies, then generate personalised notes under 300 characters.</p>
    <div style="max-height:300px;overflow:auto">${people.map(p => `<label class="check small"><input type="checkbox" value="${esc(p.id)}"> ${kindTag(p.kind)} <b style="color:#fff">${esc(p.title.slice(0, 50))}</b> <span class="muted">${esc(p.company.slice(0, 40))}</span></label>`).join('') || '<p class="muted small">No PIs or targets yet.</p>'}</div>
    <div class="row" style="margin-top:10px"><button class="btn gold" id="ln">Write notes</button></div><div id="lno"></div></div></div><div id="lo"></div>`;
  $('#hotb').onclick = e => run(e.target, async () => { await api('/api/radar', {body: {categories: ['trends']}}); toast("Searching what's hot (2–4 min)"); const t = setInterval(async () => { const l = await api('/api/scan/log'); if ((l.log.at(-1) || '').includes('Radar done')) { clearInterval(t); if (view === 'linkedin') V.linkedin(); } }, 8000); });
  $$('[data-hot]').forEach(a => a.onclick = e => { e.preventDefault(); $('#lc').value = a.dataset.hot; $('#lk').value = 'news_take'; $('#lc').scrollIntoView({block: 'center'}); toast('Topic loaded. Press "Draft post"'); });
  if ($('#li')) $('#li').onchange = () => { if ($('#li').value) { $('#lc').value = $('#li').value; $('#lk').value = 'news_take'; } };
  $('#lb').onclick = e => run(e.target, async () => { const r = await api('/api/linkedin/post', {body: {kind: $('#lk').value, context: $('#lc').value, language: $('#ll').value}}); out($('#lo'), r.text, r.agent); });
  $('#lp').onclick = e => run(e.target, async () => { const r = await api('/api/linkedin/profile', {body: {}}); out($('#lo'), r.text, r.agent); });
  $('#ln').onclick = e => run(e.target, async () => { const ids = $$('#main input[type=checkbox]:checked').map(c => c.value); if (!ids.length) return toast('Select at least one');
    const r = await api('/api/linkedin/notes', {body: {ids}}); $('#lno').innerHTML = r.notes.map(n => `<div class="note"><b>${esc(n.name)}</b> <span class="small muted">${esc(n.company)} · ${n.note.length} chars</span><div>${esc(n.note)}</div><a href="#" class="small" data-c="${esc(n.note)}">copy</a> · <a class="small" target="_blank" href="https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(n.name)}">find on LinkedIn ↗</a></div>`).join('');
    $$('#lno [data-c]').forEach(a => a.onclick = ev => { ev.preventDefault(); navigator.clipboard.writeText(a.dataset.c); toast('Copied'); }); });
};

/* ---------- MOCK INTERVIEW ---------- */
let MOCK = null;
V.interview = async (jobId = '') => {
  $('#main').innerHTML = H('Mock Interview', 'One question at a time with a score, feedback and a better answer outline. Type or speak your answers.') + `
  <div class="panel"><div class="grid g4"><div class="span2"><span class="lbl">Role</span><select id="mj"></select></div>
   <div><span class="lbl">Style</span><select id="ms"><option value="mixed">Mixed</option><option value="behavioral">Behavioral (STAR)</option><option value="technical">Technical</option><option value="case">Case / product</option><option value="academic">Academic (postdoc / PI)</option></select></div>
   <div><span class="lbl">Questions · language</span><div class="row"><select id="mn" style="flex:1"><option>4</option><option selected>6</option><option>8</option></select><select id="ml" style="flex:1"><option>English</option><option>French</option></select></div></div></div>
   <div class="row" style="margin-top:10px"><button class="btn gold" id="mst">▶ Start interview</button><label class="row small"><input type="checkbox" id="mtts" checked> read questions aloud</label><span class="right" id="msc"></span></div></div>
  <div class="panel" style="margin-top:14px"><div id="mlog"><p class="muted">Choose a role and start.</p></div>
   <textarea id="mans" placeholder="Your answer… (or press 🎙 and speak)" style="margin-top:10px"></textarea>
   <div class="row" style="margin-top:8px"><button class="btn mic" id="mmic">🎙 Speak</button><button class="btn gold" id="msend">Submit answer</button><button class="btn ghost" id="mfin">Finish & scorecard</button></div></div>`;
  $('#mj').innerHTML = (await jobOptions('General interview for my target roles')); if (jobId) $('#mj').value = jobId;
  const log = (who, text) => { $('#mlog').insertAdjacentHTML('beforeend', `<div class="qa ${who === 'me' ? 'me' : ''}">${who === 'me' ? esc(text) : md(text)}</div>`); $('#mlog').lastElementChild.scrollIntoView({block: 'nearest'}); };
  const say = t => { if (!$('#mtts').checked || !window.speechSynthesis) return; const q = (t.match(/NEXT QUESTION:\s*([\s\S]*)/i) || [, t])[1].slice(0, 600); speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(q.replace(/[*#_`]/g, '')); u.lang = $('#ml').value === 'French' ? 'fr-FR' : 'en-GB'; speechSynthesis.speak(u); };
  const scores = r => { $('#msc').innerHTML = (r.scores || []).map(x => `<span class="chip ${x >= 7 ? '' : 'miss'}">${x}/10</span>`).join('') + (r.done ? ' <b style="color:var(--gold)">DONE</b>' : ''); };
  $('#mst').onclick = e => run(e.target, async () => { $('#mlog').innerHTML = ''; MOCK = await api('/api/mock/start', {body: {job_id: $('#mj').value || null, style: $('#ms').value, questions: +$('#mn').value, language: $('#ml').value}}); log('ai', MOCK.text); say(MOCK.text); });
  const send = finish => run($('#msend'), async () => { if (!MOCK) return toast('Start an interview first'); const a = $('#mans').value.trim(); if (!a && !finish) return; if (a) log('me', a); $('#mans').value = '';
    const r = await api('/api/mock/answer', {body: {id: MOCK.id, answer: a || '(no answer)', finish}}); log('ai', r.text); scores(r); if (!r.done) say(r.text); });
  $('#msend').onclick = () => send(false); $('#mfin').onclick = () => send(true);
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition; let rec = null;
  $('#mmic').onclick = () => { if (!SR) return toast('Speech recognition is not available in this browser. Use Chrome.');
    if (rec) { rec.stop(); return; } rec = new SR(); rec.lang = $('#ml').value === 'French' ? 'fr-FR' : 'en-GB'; rec.continuous = true; rec.interimResults = true; const base = $('#mans').value;
    rec.onresult = ev => { $('#mans').value = base + ' ' + [...ev.results].map(x => x[0].transcript).join(' '); };
    rec.onend = () => { rec = null; $('#mmic').classList.remove('on'); $('#mmic').textContent = '🎙 Speak'; };
    rec.start(); $('#mmic').classList.add('on'); $('#mmic').textContent = '■ Stop'; };
};




/* ---------- APIFY (manual, budget-guarded) ---------- */
async function apifyPanel() {
  drawer('<h2>⚡ Apify scan</h2><p class="small muted">Checking your Apify account…</p>');
  const st = await api('/api/apify/status');
  if (!st.token) {
    drawer(`<h2>⚡ Apify scan</h2><p class="small">Needs an Apify API token: <a href="https://console.apify.com/settings/integrations" target="_blank">console.apify.com → Settings → API &amp; Integrations</a>. It is stored only in your private .env.</p>
      <div class="row"><input id="apt" type="password" placeholder="apify_api_…" style="flex:1"><button class="btn gold" id="aps">Save token</button></div>`);
    $('#aps').onclick = e => run(e.target, async () => { await api('/api/setup/key', {body: {APIFY_TOKEN: $('#apt').value}}); toast('Token saved'); apifyPanel(); });
    return;
  }
  if (st.error) return drawer(`<h2>⚡ Apify scan</h2><p style="color:var(--red)">${esc(st.error)}</p>`);
  const b = st.budget, pct = Math.round(100 * (b.used_usd + b.outstanding_caps_usd) / Math.max(b.allowance_usd, .01));
  drawer(`<h2>⚡ Apify scan</h2>
   <div class="panel"><div class="ptitle">Monthly budget <span class="right">live from your Apify account</span></div>
    <div class="qbar" style="height:10px"><i style="width:${Math.min(100, pct)}%;background:${pct > 80 ? 'var(--red)' : 'var(--gold)'}"></i></div>
    <div class="row small" style="margin-top:6px"><b style="color:#fff">$${b.used_usd.toFixed(2)}</b> used · $${b.outstanding_caps_usd.toFixed(2)} reserved by running runs · $${b.reserve_usd.toFixed(2)} safety reserve
     <span class="right"><b style="color:var(--good)">$${b.remaining_usd.toFixed(2)} left</b> of $${b.allowance_usd.toFixed(2)}</span></div>
    <div class="small muted">Cycle ${esc((b.cycle_start || '').slice(0, 10))} → ${esc((b.cycle_end || '').slice(0, 10))}</div></div>
   <span class="lbl">Sources</span><div class="row">${Object.entries(st.sources).map(([k, l]) => `<label class="row small"><input type="checkbox" class="aps" value="${k}" checked> ${esc(l)}</label>`).join('')}</div>
   <span class="lbl">Searches (one per line, last 7 days)</span><textarea id="apq" style="min-height:80px">${esc(st.queries.join('\n'))}</textarea>
   <div class="grid g2"><div><span class="lbl">Results per run</span><input id="api" type="number" value="20" min="5" max="100"></div><div><span class="lbl">Max $ per run (hard cap)</span><input id="apc" type="number" value="0.15" step="0.05" min="0.05"></div></div>
   <div class="row" style="margin-top:10px"><button class="btn" id="apd">Preview cost</button><button class="btn gold" id="apr">Run scan</button></div><div id="apo" class="small"></div>
   ${st.recent.length ? `<span class="lbl">Recent runs (ledger snapshot)</span>${st.recent.map(r => `<div class="check small"><span>${esc(r.key)}</span><span class="muted">${esc(r.query)}</span><span class="right">${r.items} items · $${(+r.cost_usd).toFixed(3)} · ${esc(r.status)}</span></div>`).join('')}` : ''}`);
  const body = dry => ({dry, sources: $$('.aps').filter(c => c.checked).map(c => c.value), queries: $('#apq').value.split('\n').map(x => x.trim()).filter(Boolean),
    items_per_run: +$('#api').value, cap_per_run: +$('#apc').value});
  $('#apd').onclick = e => run(e.target, async () => { const p = await api('/api/apify/scan', {body: body(true)});
    $('#apo').innerHTML = `${p.runs} runs × max $${p.cap_per_run_usd} = <b>at most $${p.max_total_usd.toFixed(2)}</b> of $${p.budget.remaining_usd.toFixed(2)} left. Then Codex/Claude review each listing; only fit &gt; 50 is imported.`; });
  $('#apr').onclick = e => run(e.target, async () => { const p = await api('/api/apify/scan', {body: body(true)});
    if (!confirm(`Run ${p.runs} Apify searches, spending at most $${p.max_total_usd.toFixed(2)} (you have $${p.budget.remaining_usd.toFixed(2)} left this month)?`)) return;
    await api('/api/apify/scan', {body: body(false)}); toast('Apify scan started. Progress in Command → system log'); closeDrawer(); });
}


/* ---------- ACADEMIA DASHBOARD (module) ---------- */
V.academia = async () => {
  await refresh(); if (!S.settings.modules?.academia) return go('settings');
  const t = today(), end = new Date(Date.now() + 60 * 864e5).toISOString().slice(0, 10);
  const [cal, pd, fe, gr] = await Promise.all([api(`/api/calendar?start=${t}&end=${end}`), api('/api/jobs?section=postdocs&limit=5'),
    api('/api/jobs?section=fellowships&limit=5&sort=deadline'), api('/api/jobs?section=grants&limit=5&sort=deadline')]);
  const secs = [['postdocs', '⌬ Postdocs'], ['fellowships', '✧ Fellowships'], ['grants', '✦ Grants'], ['contacts', '⚭ PIs'],
    ...(S.settings.modules?.community ? [['events', '✺ Events'], ['hackathons', '⚡ Hackathons']] : [])];
  $('#main').innerHTML = H('Academia', 'Postdocs, fellowships, grants and host PIs — separate from your industry dashboard.',
    `<button class="btn gold" onclick="go('discover','academia')">⇆ Swipe academia</button><button class="btn" onclick="go('match')">⚯ Fellowship match</button>`) + `
  <div class="secs">${secs.map(([k, l]) => { const x = SECS[k] || {}; return `<div class="sec" data-s="${k}"><span>${l}</span><b>${x.count || 0}</b>${x.next_deadline ? `<div class="small muted">next ${esc(x.next_deadline.slice(5))}</div>` : ''}</div>`; }).join('')}</div>
  <div class="grid g3" style="margin-top:16px">
   <div class="panel"><div class="ptitle">Top postdocs</div><div class="il">${pd.map(itemRow).join('') || '<p class="muted small">None yet.</p>'}</div></div>
   <div class="panel"><div class="ptitle">Fellowships by deadline</div><div class="il">${fe.map(itemRow).join('') || '<p class="muted small">None yet.</p>'}</div></div>
   <div class="panel"><div class="ptitle">Grants by deadline</div><div class="il">${gr.map(itemRow).join('') || '<p class="muted small">None yet.</p>'}</div></div></div>
  <div class="panel" style="margin-top:16px"><div class="ptitle">Academic deadlines (60 days)</div>
   ${cal.filter(x => ['fellowship', 'funding', 'research', 'conference', 'collaborator'].includes(x.kind)).slice(0, 10).map(x => `<div class="check" style="cursor:pointer" ${x.job_id ? `onclick="openItem('${esc(x.job_id)}')"` : ''}><span class="dl ${daysTo(x.date) <= 7 ? 'hot' : ''}">${daysTo(x.date)}d</span><div style="color:#fff">${esc(x.title)}</div></div>`).join('') || '<p class="muted small">No academic deadlines.</p>'}</div>`;
  $$('.sec').forEach(e => e.onclick = () => go(e.dataset.s)); $$('.il').forEach(el => bindItems(el));
};

/* ---------- TEMPLATE JOBS ---------- */
V.templates = async () => {
  const ts = await api('/api/templates');
  $('#main').innerHTML = H('Template Jobs', 'Postings you found yourself that show what you want. Similar opportunities get up to +20 and appear in the 💎 slots of the swipe deck.',
    '<button class="btn gold" id="tplan">◈ What do these need? Plan my gaps</button>') + `
  <div class="grid" style="grid-template-columns:1.2fr 1fr"><div class="panel"><div class="ptitle">+ Add a template</div>
    <span class="lbl">Link</span><input id="tu" placeholder="https://… (the text is fetched if the page allows it)">
    <div class="grid g2"><div><span class="lbl">Title</span><input id="tt"></div><div><span class="lbl">Organisation</span><input id="tc"></div></div>
    <span class="lbl">Posting text (paste it if the link is behind a login)</span><textarea id="tx" style="min-height:120px"></textarea>
    <div class="row" style="margin-top:10px"><button class="btn gold" id="ta">Add template</button><span class="small muted">Tip: in any item's details, press “⊕ Use as template”.</span></div></div>
   <div class="panel"><div class="ptitle">Your templates <span class="right">${ts.length}</span></div>
    ${ts.map(t => `<div class="check"><div style="flex:1"><b style="color:#fff">${esc(t.title)}</b><div class="small muted">${esc(t.company || '')} ${t.url ? `· <a href="${esc(t.url)}" target="_blank">link ↗</a>` : ''}</div>
      <div>${Object.keys(JSON.parse(t.terms || '{}')).slice(0, 8).map(w => `<span class="chip">${esc(w)}</span>`).join('')}</div></div><a href="#" data-del="${t.id}">✕</a></div>`).join('') || '<p class="muted small">None yet.</p>'}</div></div>
  <div id="tpo"></div>`;
  $('#ta').onclick = e => run(e.target, async () => { await api('/api/templates', {body: {url: $('#tu').value, title: $('#tt').value, company: $('#tc').value, text: $('#tx').value}}); toast('Template added. Rescoring'); V.templates(); });
  $$('[data-del]').forEach(a => a.onclick = async ev => { ev.preventDefault(); await api('/api/templates?id=' + a.dataset.del, {method: 'DELETE'}); V.templates(); });
  $('#tplan').onclick = e => run(e.target, async () => { const r = await api('/api/templates/plan', {body: {}}); out($('#tpo'), r.text, r.agent); });
};

/* ---------- SETUP WIZARD ---------- */
let SETUP = {step: 0};
const STEPS = ['CV', 'Field', 'AI', 'Email', 'Go'];
V.setup = async (step) => {
  const st = await api('/api/setup/status'); SETUP.st = st; if (step !== undefined) SETUP.step = +step;
  const bar = `<div class="steps">${STEPS.map((x, i) => `<span class="${i === SETUP.step ? 'on' : i < SETUP.step ? 'done' : ''}" data-st="${i}"><b>${i < SETUP.step ? '✓' : i + 1}</b>${x}</span>`).join('<i></i>')}</div>`;
  const nav = (back = true, next = 'Next') => `<div class="row" style="margin-top:16px">${back && SETUP.step ? '<button class="btn ghost" id="sb">Back</button>' : ''}<span class="right"></span><button class="btn gold" id="sn">${next}</button></div>`;
  let body = '';
  if (SETUP.step === 0) body = `<div class="lbl">Your CV</div><p class="small muted">${st.resume ? '✓ CV loaded. Upload again to replace it.' : 'PDF, DOCX or TXT. It never leaves this computer except in prompts to your own AI accounts.'}</p>
    <input type="file" id="wf" accept=".pdf,.docx,.txt,.md">` + nav(false, st.resume ? 'Next' : 'Upload & continue');
  if (SETUP.step === 1) body = `<div class="lbl">Field pack</div><p class="small muted">Current: <b>${esc(st.pack || 'none')}</b>. A pack defines your field lanes, searches, companies and conferences.</p>
    <div class="choices"><label class="choice"><input type="radio" name="pk" value="" checked><b>✦ Build from my CV with AI</b><span>about a minute</span></label>
    ${st.builtin_packs.map(b => `<label class="choice"><input type="radio" name="pk" value="${esc(b.id)}" ${b.id === st.pack ? 'checked' : ''}><b>${esc(b.name)}</b><span>built-in</span></label>`).join('')}</div><div id="po"></div>` + nav();
  if (SETUP.step === 2) body = `<div class="lbl">Connect your AI subscriptions</div><p class="small muted">JobAgent uses the AI accounts you already pay for, via their official command-line tools. At least one is needed.</p>
    ${Object.entries(st.agents).map(([k, a]) => `<div class="agentrow"><i class="led ${a.ready ? 'on' : 'off'}"></i><b>${esc(a.name)}</b><span class="small muted">${a.ready ? 'connected' : a.state === 'budget' ? 'installed · daily budget used' : a.state === 'limit' ? 'installed · usage limit, resting' : esc(a.state)}</span>
      ${a.ready || ['budget', 'limit'].includes(a.state) ? '' : `<div class="cmds"><code>${esc(a.install)}</code><button class="btn ghost cp" data-c="${esc(a.install)}">copy</button><code>${esc(a.login)}</code><button class="btn ghost cp" data-c="${esc(a.login)}">copy</button></div>`}</div>`).join('')}
    <div class="row" style="margin-top:8px"><input id="gk" placeholder="Optional: Gemini API key (free at aistudio.google.com)" style="flex:1"><button class="btn ghost" id="gks">Save key</button><button class="btn" id="rt">Re-check</button></div>` + nav();
  if (SETUP.step === 3) body = `<div class="lbl">Email (optional)</div><p class="small muted">Used to send you alerts and to read job-alert emails (LinkedIn, Indeed, APEC…) read-only. Skip it to use in-app notifications only.</p>
    <div class="grid g2"><div><span class="lbl">Provider</span><select id="ep">${Object.keys(st.email_presets).map(k => `<option>${k}</option>`).join('')}</select><p class="small muted" id="eh"></p></div>
    <div><span class="lbl">Address</span><input id="ea" value="${esc(st.default_email || '')}"><span class="lbl">App password</span><input id="ew" type="password" autocomplete="off"></div></div>
    <div class="row"><button class="btn" id="et">Test & save</button><span id="er" class="small"></span></div>${st.email ? '<p class="small" style="color:var(--good)">✓ Email already connected.</p>' : ''}` + nav(true, 'Next');
  if (SETUP.step === 4) body = `<div class="lbl">How should applying work?</div><div class="choices">
    ${[['assisted', 'Assisted', 'Tailored CV, letter and answers prepared; you press Submit.'], ['email_auto', 'Auto-send email applications', 'Email applications go out from your account within daily limits; web forms stay manual.'], ['web_assist', 'Web assist', 'The posting opens with your letter and answers ready to copy; you submit. (JobAgent never submits web forms by itself.)']].map(([v, t, d]) => `<label class="choice"><input type="radio" name="am" value="${v}" ${(st.apply_mode || 'assisted') === v ? 'checked' : ''}><b>${t}</b><span>${d}</span></label>`).join('')}</div>
    <div class="grid g2"><div><span class="lbl">Home country</span><input id="hc" value="${esc(st.home_country || '')}" placeholder="e.g. France"></div><div><span class="lbl">Hide countries (comma-separated codes)</span><input id="xc" value="${esc((S.settings && S.settings.excluded_countries || []).join(', '))}" placeholder="e.g. US"></div></div>
    <div class="lbl">Optional modules</div><label class="row small"><input type="checkbox" id="wac"> 🎓 Academia (postdocs, fellowships, grants, PIs)</label>
    <label class="row small"><input type="checkbox" id="wco"> ⚡ Community (hackathons, events, job fairs)</label>
    <label class="row small" style="margin-top:10px"><input type="checkbox" id="fs" checked> run the first scan now</label>` + nav(true, 'Finish ▸');
  $('#main').innerHTML = H('Setup', `Data folder: ${st.app_home}`) + `<div class="panel wizard">${bar}${body}</div>`;
  $$('.steps [data-st]').forEach(e => e.onclick = () => V.setup(e.dataset.st));
  if ($('#sb')) $('#sb').onclick = () => V.setup(SETUP.step - 1);
  $$('.cp').forEach(b => b.onclick = () => { navigator.clipboard.writeText(b.dataset.c); toast('Copied. Paste it in a terminal'); });
  const next = () => V.setup(SETUP.step + 1);
  if (SETUP.step === 0) $('#sn').onclick = e => run(e.target, async () => { const f = $('#wf').files[0]; if (f) { const fd = new FormData(); fd.append('file', f); await api('/api/resume', {body: fd}); toast('CV analysed'); } else if (!st.resume) return toast('Choose your CV first'); next(); });
  if (SETUP.step === 1) $('#sn').onclick = e => run(e.target, async () => { const v = ($$('input[name=pk]').find(x => x.checked) || {}).value; const r = await api('/api/setup/pack', {body: v ? {builtin: v} : {}});
    $('#po').innerHTML = `<div class="panel out"><b>${esc(r.name)}</b> · ${esc(r.field)}<div>${r.lanes.map(l => `<span class="chip cat">${esc(l)}</span>`).join('')}</div></div>`; _refAt = 0; setTimeout(next, 1200); });
  if (SETUP.step === 2) { $('#rt').onclick = () => V.setup(2); $('#gks').onclick = async () => { if (!$('#gk').value) return; await api('/api/setup/key', {body: {GEMINI_API_KEY: $('#gk').value}}); toast('Key saved'); V.setup(2); };
    $('#sn').onclick = () => Object.values(st.agents).some(a => a.ready) ? next() : toast('Connect at least one AI first'); }
  if (SETUP.step === 3) { const hp = () => $('#eh').textContent = st.email_presets[$('#ep').value]; $('#ep').onchange = hp; hp();
    $('#et').onclick = e => run(e.target, async () => { const r = await api('/api/setup/email', {body: {provider: $('#ep').value, address: $('#ea').value, password: $('#ew').value}}); $('#ew').value = '';
      $('#er').innerHTML = r.smtp ? `<span style="color:var(--good)">✓ sending works${r.imap ? ' · ✓ alert reading works' : ''}</span>` : `<span style="color:var(--red)">✕ ${esc(r.error)}</span>`; });
    $('#sn').onclick = next; }
  if (SETUP.step === 4) $('#sn').onclick = e => run(e.target, async () => { await api('/api/setup/finish', {body: {apply_mode: ($$('input[name=am]').find(x => x.checked) || {}).value, home_country: $('#hc').value,
      excluded_countries: $('#xc').value.split(',').map(x => x.trim().toUpperCase()).filter(Boolean), modules: {academia: $('#wac').checked, community: $('#wco').checked}, scan: $('#fs').checked}}); _refAt = 0; toast('Setup complete'); go('home'); });
};

/* ---------- RESUME & ATS ---------- */
V.resume = async () => {
  await refresh(); const r = S.resume, p = r?.profile || {};
  $('#main').innerHTML = H('Resume · ATS', 'Your master resume powers matching, letters and coaching.',
    r ? `<a class="btn gold" target="_blank" href="/api/resume/export" style="text-decoration:none">🖨 Print / Export PDF CV ↗</a>` : '') + `
  <div class="grid g2"><div class="panel"><div class="ptitle">▣ Master resume</div><p class="small muted">${r ? `Loaded: ${esc(r.name)} (${r.chars} chars)` : 'None uploaded'}</p>
   <input type="file" id="rf" accept=".pdf,.docx,.txt,.md"><div class="row" style="margin-top:8px"><button class="btn gold" id="ru">Upload & analyse</button>${r ? '<button class="btn" id="rpf">◈ Rebuild profile with AI</button>' : ''}${r ? '<a class="btn" target="_blank" href="/api/resume/export" style="text-decoration:none">🖨 Print / PDF</a>' : ''}</div>
   <details style="margin-top:10px"><summary class="small">…or paste text</summary><textarea id="rt"></textarea><button class="btn ghost" id="rp" style="margin-top:6px">Save</button></details></div>
  <div class="panel gold"><div class="ptitle" style="color:var(--gold)">◉ Operative profile <span class="right">${esc(p._agent || '')}</span></div>${r ? `<b style="color:#fff">${esc(p.headline || '')}</b><p class="small">${esc(p.summary || '')}</p>
   <span class="lbl">Strengths</span>${(p.strengths || []).map(s => `<span class="chip">${esc(s)}</span>`).join('')}<span class="lbl">Gaps</span>${(p.gaps || []).map(s => `<span class="chip miss">${esc(s)}</span>`).join('')}
   ${p._error ? `<p class="small" style="color:var(--warn)">AI profile unavailable — local detection used.</p>` : ''}` : '<p class="muted">Upload to see it.</p>'}</div></div>
  <div class="panel" style="margin-top:16px"><div class="ptitle">✓ ATS checker</div><span class="lbl">Tracked item</span><select id="aj"></select><span class="lbl">…or job description</span><textarea id="ajd"></textarea>
   <span class="lbl">Agent</span>${agentSel('aag')}<div class="row" style="margin-top:10px"><button class="btn ghost" id="aq">Quick scan</button><button class="btn gold" id="aa">Full ATS review</button></div><div id="ao"></div></div>
  <div class="panel" style="margin-top:16px"><div class="ptitle">✎ Improve / tailor resume</div><span class="lbl">Tracked item (optional)</span><select id="ij"></select><span class="lbl">…or job description</span><textarea id="ijd" style="min-height:70px"></textarea>
   <span class="lbl">Focus</span><input id="if" placeholder="e.g. industry pivot, 1 page, French version, emphasise PET physics"><span class="lbl">Agent</span>${agentSel('iag')}
   <div class="row" style="margin-top:10px"><button class="btn gold" id="ib">Improve resume</button></div><div id="io"></div></div>`;
  const o = await jobOptions(); $('#aj').innerHTML = o; $('#ij').innerHTML = o;
  $('#ru').onclick = e => run(e.target, async () => { const f = $('#rf').files[0]; if (!f) return toast('Choose a file'); const fd = new FormData(); fd.append('file', f); await api('/api/resume', {body: fd}); toast('Resume analysed'); V.resume(); });
  if ($('#rpf')) $('#rpf').onclick = e => run(e.target, async () => { const r = await api('/api/resume/reprofile', {body: {}}); toast('Profile rebuilt by ' + r.profile._agent); V.resume(); });
  $('#rp').onclick = e => run(e.target, async () => { await api('/api/resume/text', {body: {text: $('#rt').value}}); V.resume(); });
  $('#aq').onclick = e => run(e.target, async () => { const r = await api('/api/ats/quick', {body: {jd: $('#ajd').value}}); out($('#ao'), atsMd({rules: r}), 'local rules'); });
  $('#aa').onclick = e => run(e.target, async () => { const r = await api('/api/ai/ats', {body: {jd: $('#ajd').value, job_id: $('#aj').value || null, agent: $('#aag').value || undefined}}); out($('#ao'), atsMd(r), r.agent); });
  $('#ib').onclick = e => run(e.target, async () => { const r = await api('/api/ai/improve_resume', {body: {job_id: $('#ij').value || null, jd: $('#ijd').value, focus: $('#if').value, agent: $('#iag').value || undefined}}); out($('#io'), r.text, r.agent); });
};

/* ---------- LETTERS & EMAIL ---------- */
V.write = async () => {
  await refresh();
  $('#main').innerHTML = H('Letters · Email', 'Drafts built from your real experience; everything is archived.') + `
  <div class="grid g2"><div class="panel"><div class="ptitle">✎ Cover letter</div><span class="lbl">Tracked item</span><select id="cj"></select><span class="lbl">…or description</span><textarea id="cjd" style="min-height:80px"></textarea>
   <div class="row"><div style="flex:1"><span class="lbl">Language</span><select id="cl"><option>English</option><option>French</option><option>Spanish</option><option>German</option></select></div><div style="flex:1"><span class="lbl">Tone</span><select id="ct"><option>confident, warm, concise</option><option>formal and academic</option><option>enthusiastic startup</option><option>executive, crisp</option></select></div></div>
   <span class="lbl">Mention</span><input id="cx" placeholder="referral, relocation, visa, availability…"><span class="lbl">Agent</span>${agentSel('cag')}<div class="row" style="margin-top:10px"><button class="btn gold" id="cb">Write letter</button></div></div>
  <div class="panel"><div class="ptitle">✉ Email / message</div><span class="lbl">Type</span><select id="ek"><option value="recruiter_outreach">Recruiter / hiring-manager outreach</option><option value="referral_request">Referral request</option><option value="networking">Collaboration / networking request</option><option value="follow_up">Follow-up after applying</option><option value="thank_you">Post-interview thank-you</option><option value="negotiation">Offer negotiation</option><option value="withdraw">Withdraw politely</option><option value="postdoc_inquiry">Postdoc inquiry to a PI</option><option value="spontaneous">Spontaneous application</option></select>
   <span class="lbl">Tracked item</span><select id="ej"></select><span class="lbl">Recipient</span><input id="er" placeholder="Name, role"><span class="lbl">Context</span><textarea id="ec" style="min-height:60px"></textarea>
   <div class="row"><div style="flex:1"><span class="lbl">Language</span><select id="el"><option>English</option><option>French</option><option>Spanish</option></select></div><div style="flex:1"><span class="lbl">Agent</span>${agentSel('eag')}</div></div><div class="row" style="margin-top:10px"><button class="btn gold" id="eb">Draft</button></div></div></div><div id="wo"></div>`;
  const o = await jobOptions(); $('#cj').innerHTML = o; $('#ej').innerHTML = o.replace('— paste a description instead —', '— none —');
  $('#cb').onclick = e => run(e.target, async () => { const r = await api('/api/ai/cover_letter', {body: {job_id: $('#cj').value || null, jd: $('#cjd').value, language: $('#cl').value, tone: $('#ct').value, extra: $('#cx').value, agent: $('#cag').value || undefined}}); out($('#wo'), r.text, r.agent); });
  $('#eb').onclick = e => run(e.target, async () => { const r = await api('/api/ai/email', {body: {kind: $('#ek').value, job_id: $('#ej').value || null, recipient: $('#er').value, context: $('#ec').value, language: $('#el').value, agent: $('#eag').value || undefined}}); out($('#wo'), r.text, r.agent); });
};

/* ---------- COACH ---------- */
V.coach = async () => {
  await refresh();
  $('#main').innerHTML = H('Coach', 'Strategy, salary, prioritisation, positioning, visas — it knows your resume and pipeline.') + `
  <div class="panel"><div class="chat" id="ch"></div><textarea id="cm" style="min-height:60px;margin-top:10px" placeholder="Transmit… (Enter to send, Shift+Enter for newline)"></textarea>
  <div class="row" style="margin-top:6px"><div style="width:260px">${agentSel('chag')}</div><label class="row small"><input type="checkbox" id="chc"> council mode</label><span class="right"></span><button class="btn ghost" id="cc">Clear</button><button class="btn gold" id="cs">Send</button></div></div>`;
  const render = async () => { const h = await api('/api/chat'); $('#ch').innerHTML = h.map(m => `<div class="msg ${m.role}">${m.role === 'assistant' ? `<div class="md">${md(m.content)}</div><div class="small muted">${esc(m.agent)}</div>` : esc(m.content)}</div>`).join('') || '<p class="muted">Try: “Which 3 opportunities should I prioritise this week and why?”</p>'; $('#ch').scrollTop = 1e9; }; render();
  const send = () => run($('#cs'), async () => { const m = $('#cm').value.trim(); if (!m) return; $('#cm').value = ''; $('#ch').insertAdjacentHTML('beforeend', `<div class="msg user">${esc(m)}</div><div class="msg assistant"><span class="ld"></span></div>`); $('#ch').scrollTop = 1e9; await api('/api/chat', {body: {message: m, agent: $('#chag').value || undefined, council: $('#chc').checked}}).catch(e => toast(e.message)); render(); });
  $('#cs').onclick = send; $('#cm').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }; $('#cc').onclick = async () => { await api('/api/chat', {method: 'DELETE'}); render(); };
};

/* ---------- COUNCIL ---------- */
V.agents = async () => {
  await refresh();
  $('#main').innerHTML = H('Council', 'Opus, Astra (Codex) and Gemini answer in parallel; the lead merges the best of each.', '<button class="btn" id="pb">Test connections</button>') + `
  <div class="grid g4">${Object.entries(S.agents).map(([k, a]) => `<div class="panel"><div class="row"><i class="led ${a.ready ? 'on' : 'off'}"></i><b style="font-family:Orbitron;font-size:12px;letter-spacing:.1em">${esc(a.label)}</b></div><div class="small muted" style="word-break:break-all;margin-top:6px">${esc(a.detail).slice(0, 140)}</div></div>`).join('')}</div><div id="po"></div>
  <div class="panel gold" style="margin-top:16px"><div class="ptitle" style="color:var(--gold)">⇄ Model switching <span class="right">today's usage resets at midnight</span></div>
   <p class="small muted">Each request goes to the agent routed for that task. If it is offline, over its daily budget, or hits a usage limit, JobAgent switches to the next agent in the fallback order and rests the limited one for the cooldown period.</p>
   <div class="rt small muted"><span>Agent</span><span>State</span><span>Today (calls · ~tokens)</span><span>Daily call budget (0 = ∞)</span><span>Fallback #</span></div>
   ${Object.entries(S.agents).map(([k, a]) => `<div class="rt"><b style="color:#fff">${esc(a.label)}</b><span class="st ${esc(a.state)}" title="${esc(a.detail)}">${esc(a.state === 'limit' ? 'cooldown' : a.state).toUpperCase()}</span>
    <span class="small">${a.usage.calls} · ~${Math.round((a.usage.tokens_in + a.usage.tokens_out) / 1000)}k${a.usage.fails ? ` · <span style="color:var(--red)">${a.usage.fails} fails</span>` : ''}</span>
    <input type="number" min="0" data-budget="${k}" value="${a.budget}"><input type="number" min="1" max="4" data-order="${k}" value="${(S.settings.agent_order || []).indexOf(k) + 1 || 4}"></div>`).join('')}
   <div class="grid g3" style="margin-top:10px">${Object.entries({writing: 'Writing (resume, letters, emails, interview)', review: 'Job reviews in scans', radar: 'Web radar (Gemini, Claude, Codex)', chat: 'Coach chat', training: 'Training & plans', profile: 'Resume profile'}).map(([t, l]) => `<div><span class="lbl">${l}</span><select data-route="${t}">${['auto', ...(t === 'review' ? ['rotate'] : []), 'claude_cli', 'codex', 'gemini', 'anthropic_api'].filter(o => t !== 'radar' || ['gemini', 'claude_cli', 'codex', 'auto'].includes(o)).map(o => `<option ${((S.settings.routes || {})[t] || 'auto') === o ? 'selected' : ''}>${o}</option>`).join('')}</select></div>`).join('')}</div>
   <div class="row" style="margin-top:10px"><span class="lbl" style="margin:0">Cooldown after usage limit (min)</span><input type="number" id="cool" value="${S.settings.limit_cooldown_min || 60}" style="width:90px"><span class="right"></span><button class="btn gold" id="rsave">Save routing</button></div></div>
  <div class="panel" style="margin-top:16px"><span class="lbl">Query the council</span><textarea id="cp" placeholder="e.g. Should I target industry PET application-scientist roles or a MedTech startup CTO path? Compare."></textarea><div class="row" style="margin-top:8px"><button class="btn gold" id="cb">Convene</button></div><div id="co"></div></div>
  <div class="panel" style="margin-top:16px"><div class="ptitle">Run log</div>${S.runs.map(r => `<div class="check"><span>${r.ok ? '✓' : '✕'}</span><span style="color:var(--gold)">${esc(r.kind)}</span><span class="muted small">${new Date(r.started * 1000).toLocaleString()}</span><span class="small">${esc(r.summary)}</span></div>`).join('') || '<p class="muted">None yet.</p>'}</div>`;
  $('#pb').onclick = e => run(e.target, async () => { const r = await api('/api/agents/probe', {body: {}}); $('#po').innerHTML = `<div class="panel" style="margin-top:12px">${Object.entries(r).map(([k, v]) => `<div class="check"><span>${v.ok ? '✓' : '✕'}</span><b>${esc(k)}</b><span class="small muted">${esc(v.ok ? v.reply : v.error).slice(0, 200)}</span></div>`).join('')}</div>`; refresh(); });
  $('#rsave').onclick = e => run(e.target, async () => {
    const budgets = {}; $$('[data-budget]').forEach(i => budgets[i.dataset.budget] = +i.value);
    const order = $$('[data-order]').sort((a, b) => a.value - b.value).map(i => i.dataset.order);
    const routes = {}; $$('[data-route]').forEach(i => routes[i.dataset.route] = i.value);
    await api('/api/settings', {body: {agent_budgets: budgets, agent_order: order, routes, limit_cooldown_min: +$('#cool').value}}); toast('Routing saved'); V.agents(); });
  $('#cb').onclick = e => run(e.target, async () => { const r = await api('/api/council', {body: {prompt: $('#cp').value}}); $('#co').innerHTML = `<div class="panel gold out"><div class="ptitle" style="color:var(--gold)">◈ Merged answer <span class="right">lead: ${esc(r.lead)}</span></div><div class="md">${md(r.synthesis)}</div></div>` + r.answers.map(a => `<details class="panel out"><summary><b>${esc(a.family)}</b> <span class="small muted">${esc(a.agent || 'offline')}</span></summary><div class="md">${md(a.text)}</div></details>`).join(''); });
};

/* ---------- ARCHIVE ---------- */
V.docs = async () => {
  const d = await api('/api/docs');
  $('#main').innerHTML = H('Archive', 'Everything the agents have written for you.') + `<div class="panel">${d.map(x => `<div class="check" style="cursor:pointer" onclick="openDoc(${x.id})"><span class="chip cat">${esc(x.kind)}</span><span style="flex:1;color:#fff">${esc(x.title)}</span><span class="small muted">${esc(x.agent)} · ${new Date(x.created * 1000).toLocaleDateString()}</span></div>`).join('') || '<p class="muted">Empty.</p>'}</div>`;
};
async function openDoc(id) {
  const d = await api('/api/doc?id=' + id);
  const isResume = d.kind && (d.kind.includes('resume') || d.kind.includes('cv'));
  drawer(`<h2>${esc(d.title)}</h2><p class="small muted">${esc(d.agent)} · ${new Date(d.created * 1000).toLocaleString()}</p><div class="row"><button class="btn" id="dcp">Copy</button><button class="btn" id="ddl">Download .md</button><button class="btn" id="dkb">⇢ Save to Obsidian</button>${isResume ? `<a class="btn gold" target="_blank" href="/api/resume/export?id=${id}" style="text-decoration:none">🖨 Print / PDF CV ↗</a>` : ''}<button class="btn ghost" id="ddel">Delete</button></div><div class="md out">${md(d.content)}</div>`);
  $('#dkb').onclick = e => run(e.target, async () => { const r = await api('/api/kb/export', {body: {doc_id: id}}); toast('Saved: ' + r.path); });
  $('#dcp').onclick = () => { navigator.clipboard.writeText(d.content); toast('Copied'); };
  $('#ddl').onclick = () => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([d.content], {type: 'text/markdown'})); a.download = d.title.replace(/[^\w-]+/g, '_') + '.md'; a.click(); };
  $('#ddel').onclick = async () => { await api('/api/doc?id=' + id, {method: 'DELETE'}); closeDrawer(); if (view === 'docs') V.docs(); };
}

async function draftFollowUp(jobId) {
  drawer(`<h2>✉ Drafting Follow-Up Note...</h2><p class="small muted">Generating a polite, value-driven follow-up note referencing your relevant research background...</p><div class="panel gold out"><span class="ld"></span></div>`);
  try {
    const r = await api('/api/tracker/followup', {body: {job_id: jobId}});
    drawer(`<h2>✉ Follow-Up Note · ${esc(r.job.company)}</h2>
      <p class="small muted">Role: <b>${esc(r.job.title)}</b> · Applied: ${esc(r.job.applied_at || '')} (${r.days_stalled} days ago)</p>
      <div class="row" style="margin-bottom:12px"><button class="btn gold" id="fucp">Copy Note</button><button class="btn ghost" onclick="openItem('${esc(jobId)}')">View Opportunity</button></div>
      <div class="panel gold out" style="white-space:pre-wrap;font-family:inherit;line-height:1.6">${esc(r.followup_note)}</div>`);
    $('#fucp').onclick = () => { navigator.clipboard.writeText(r.followup_note); toast('Follow-up note copied to clipboard!'); };
  } catch (e) {
    drawer(`<h2>Error drafting follow-up</h2><p class="small" style="color:var(--warn)">${esc(e.message)}</p>`);
  }
}

/* ---------- CONFIG ---------- */
V.settings = async () => {
  await refresh(); const s = S.settings, L = a => (a || []).join(', ');
  $('#main').innerHTML = H('Config', 'Targets are auto-filled from your resume. Saving re-scores everything.', '<a class="btn ghost" href="/classic" style="text-decoration:none">Classic UI</a>') + `
  <div class="grid g2"><div class="panel"><div class="ptitle">◎ Targeting</div><span class="lbl">Name</span><input id="s_name" value="${esc(s.name)}"><span class="lbl">Target roles</span><textarea id="s_roles" style="min-height:70px">${esc(L(s.target_roles))}</textarea>
   <span class="lbl">Keywords / skills</span><textarea id="s_kw" style="min-height:70px">${esc(L(s.keywords))}</textarea><span class="lbl">Locations</span><input id="s_loc" value="${esc(L(s.locations))}">
   <span class="lbl">Exclude titles containing</span><input id="s_ex" value="${esc(L(s.exclude_keywords))}"><label class="row small" style="margin-top:8px"><input type="checkbox" id="s_rem" ${s.remote_ok ? 'checked' : ''}> Remote OK</label>
   <span class="lbl">Company boards to watch (greenhouse:slug, lever:slug, ashby:slug)</span><textarea id="s_wc" style="min-height:50px">${esc(L(s.watch_companies))}</textarea>
   <span class="lbl">Adzuna countries (free key in .env)</span><input id="s_az" value="${esc(L(s.adzuna_countries))}">
   <span class="lbl">What I want (used in scoring and every AI review)</span><textarea id="s_pref" style="min-height:80px" placeholder="e.g. Prefer Europe (FR, CH, NL, DE). Open to postdoc, product specialist, analyst, CTO/founding roles in MedTech. Not interested in pure software/data jobs outside healthcare.">${esc(s.preferences || '')}</textarea>
   <span class="lbl">Applying</span><select id="s_am">${[['assisted', 'Assisted — prepare, you submit'], ['email_auto', 'Auto-send email applications (daily limit)'], ['web_assist', 'Web assist — answers ready, you submit']].map(([v, l]) => `<option value="${v}" ${(s.apply_mode === v || (v === 'web_assist' && s.apply_mode === 'web_auto')) ? 'selected' : ''}>${l}</option>`).join('')}</select>
   <div class="row small"><span>Max application emails per day</span><input id="s_al" type="number" min="1" max="20" value="${s.apply_daily_limit || 5}" style="width:80px"></div>
   <span class="lbl">Modules</span><label class="row small"><input type="checkbox" id="m_ac" ${s.modules?.academia ? 'checked' : ''}> 🎓 Academia — postdocs, fellowships, grants, PI contacts</label>
   <label class="row small"><input type="checkbox" id="m_co" ${s.modules?.community ? 'checked' : ''}> ⚡ Community — hackathons, events &amp; job fairs</label>
   <span class="lbl">Knowledge base (Obsidian vault or Markdown folder, optional)</span><div class="row"><input id="s_kb" value="${esc(s.kb_path || '')}" placeholder="/Users/you/Documents/MyVault" style="flex:1"><button class="btn ghost" id="kbt">Test</button></div><div id="kbo" class="small muted"></div>
   <span class="lbl">Nationality (for visa briefs)</span><input id="s_nat" value="${esc(s.nationality || '')}">
   <span class="lbl">Companies to watch for intel</span><textarea id="s_intel" style="min-height:60px">${esc(L(s.intel_companies))}</textarea></div>
  <div class="panel"><div class="ptitle">⚭ Agents & alerts</div><span class="lbl">Alert email</span><input id="s_to" value="${esc(s.email_to)}"><div class="row small" style="margin-top:6px"><i class="led ${S.email ? 'on' : 'off'}"></i> SMTP ${S.email ? 'online' : 'offline'} <button class="btn ghost right" id="et">Test email</button></div>
   <div class="grid g2"><div><span class="lbl">Min alert score</span><input id="s_min" type="number" value="${s.min_score}"></div><div><span class="lbl">Scan every (h)</span><input id="s_int" type="number" value="${s.scan_interval_hours}"></div>
   <div><span class="lbl">Agent reviews / scan</span><input id="s_top" type="number" value="${s.ai_review_top_n}"></div><div><span class="lbl">Radar lanes / scan (0 = all)</span><input id="s_rad" type="number" min="0" value="${s.radar_per_scan}"></div>
   <div><span class="lbl">Results per lane</span><input id="s_rmax" type="number" min="5" max="40" value="${s.radar_max_items || 20}"></div>
   <div><span class="lbl">Parallel searches per agent</span><input id="s_rw" type="number" min="1" max="4" value="${s.radar_workers_per_agent || 2}"></div>
   <div><span class="lbl">Weekly plan hour (Mon)</span><input id="s_h" type="number" value="${s.daily_digest_hour}"></div><div><span class="lbl">Primary agent</span><select id="s_ai">${['claude_cli', 'codex', 'gemini', 'anthropic_api', 'auto'].map(x => `<option ${x === s.ai_primary ? 'selected' : ''}>${x}</option>`).join('')}</select></div></div>
   <span class="lbl">Council members</span><input id="s_cn" value="${esc(L(s.council_agents))}"></div></div>
  <div class="row" style="margin-top:16px"><button class="btn gold" id="ss">Save config</button></div>`;
  const sp = v => v.split(',').map(x => x.trim()).filter(Boolean);
  $('#ss').onclick = e => run(e.target, async () => { await api('/api/settings', {body: {name: $('#s_name').value, target_roles: sp($('#s_roles').value), keywords: sp($('#s_kw').value), locations: sp($('#s_loc').value), exclude_keywords: sp($('#s_ex').value), remote_ok: $('#s_rem').checked, watch_companies: sp($('#s_wc').value), adzuna_countries: sp($('#s_az').value), email_to: $('#s_to').value, min_score: +$('#s_min').value, scan_interval_hours: +$('#s_int').value, ai_review_top_n: +$('#s_top').value, radar_per_scan: +$('#s_rad').value, radar_max_items: +$('#s_rmax').value, radar_workers_per_agent: +$('#s_rw').value, preferences: $('#s_pref').value, kb_path: $('#s_kb').value, modules: {academia: $('#m_ac').checked, community: $('#m_co').checked}, apply_mode: $('#s_am').value, apply_daily_limit: +$('#s_al').value, nationality: $('#s_nat').value, intel_companies: sp($('#s_intel').value), daily_digest_hour: +$('#s_h').value, ai_primary: $('#s_ai').value, council_agents: sp($('#s_cn').value)}}); toast('Config saved, re-scoring'); });
  $('#et').onclick = e => run(e.target, async () => { const r = await api('/api/email/test', {body: {}}); toast('Sent to ' + r.sent_to); });
  $('#kbt').onclick = e => run(e.target, async () => { await api('/api/settings', {body: {kb_path: $('#s_kb').value}}); const r = await api('/api/kb/status');
    $('#kbo').innerHTML = r.linked ? `✓ ${r.notes} notes${r.is_obsidian ? ' · Obsidian vault' : ''}` : `✕ ${esc(r.error || 'not linked')}`; });
};

go(view);
