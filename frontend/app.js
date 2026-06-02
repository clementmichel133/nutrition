// ════════════════════════════════════════════════════════════════════════════
// STATE
// ════════════════════════════════════════════════════════════════════════════
const API = window.location.origin;

const S = {
  today:              null,
  profile:            null,
  mealType:           null,
  pendingItems:       [],
  mediaRecorder:      null,
  audioChunks:        [],
  isRecording:        false,
  gender:             'homme',
  goal:               null,
  historyDays:        7,
  charts:             { kcal: null, macros: null },
  weekPlanConfig:     { meal_types: ['petit_dej', 'dejeuner', 'diner'], batch_size: 4 },
  weeklyPlan:         null,
  addedPlannedMeals:  new Set(),
};

const MEALS = {
  petit_dej: { label: 'Petit déjeuner', emoji: '🌅' },
  dejeuner:  { label: 'Déjeuner',       emoji: '🌞' },
  gouter:    { label: 'Goûter',         emoji: '🍎' },
  diner:     { label: 'Dîner',          emoji: '🌙' },
};

const CIRC = 2 * Math.PI * 66; // circumference for r=66

let _recentMeals  = []; // cache pour la modal de saisie
let _foodLibrary  = []; // cache bibliothèque aliments

// ════════════════════════════════════════════════════════════════════════════
// INIT
// ════════════════════════════════════════════════════════════════════════════
window.addEventListener('DOMContentLoaded', () => {
  const d = new Date();
  document.getElementById('header-date').innerHTML =
    d.toLocaleDateString('fr-FR', { weekday: 'long' }) + '<br>' +
    d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' });

  renderMealCards([]);           // affiche les 4 cards vides immédiatement
  Promise.all([loadToday(), loadProfile()]);
  loadHistory(7);

  document.getElementById('modal-input').addEventListener('click', e => {
    if (e.target === document.getElementById('modal-input')) closeInputModal();
  });
  document.getElementById('modal-confirm').addEventListener('click', e => {
    if (e.target === document.getElementById('modal-confirm'))
      document.getElementById('modal-confirm').classList.add('hidden');
  });
});

// ════════════════════════════════════════════════════════════════════════════
// TABS
// ════════════════════════════════════════════════════════════════════════════
function switchTab(tab) {
  document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.add('active');
  document.getElementById('nav-' + tab).classList.add('active');
  if (tab === 'macros')  renderMacros();
  if (tab === 'history') loadHistory(S.historyDays);
}

// ════════════════════════════════════════════════════════════════════════════
// API HELPER
// ════════════════════════════════════════════════════════════════════════════
async function api(path, opts = {}) {
  const r = await fetch(API + path, opts);
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(e.detail || r.statusText);
  }
  return r.json();
}

// ════════════════════════════════════════════════════════════════════════════
// TODAY / RÉSUMÉ
// ════════════════════════════════════════════════════════════════════════════
async function loadToday() {
  try {
    S.today = await api('/today');
  } catch (e) {
    console.warn('loadToday:', e.message);
  }
  renderResume(); // toujours appelé, même si l'API échoue
}

function renderResume() {
  const tot = S.today?.totals  || {};
  const tgt = S.today?.targets || {};

  const kcal  = Math.round(tot.kcal || 0);
  const tKcal = tgt.kcal || 0;
  const ratio = tKcal > 0 ? tot.kcal / tKcal : 0;

  document.getElementById('ring-num').textContent    = kcal;
  document.getElementById('ring-target').textContent = tKcal ? Math.round(tKcal) : '–';

  const fg = document.getElementById('ring-fg');
  if (ratio <= 1) {
    fg.style.strokeDashoffset = CIRC * (1 - ratio);
    fg.style.stroke           = 'var(--sage)';
  } else {
    fg.style.strokeDashoffset = '0';
    fg.style.stroke           = 'var(--red)';
  }

  setMacroPill('prot', tot.prot, tgt.prot);
  setMacroPill('carb', tot.carb, tgt.carb);
  setMacroPill('fat',  tot.fat,  tgt.fat);

  const kcalPct = tgt.kcal > 0 ? Math.min((tot.kcal / tgt.kcal) * 100, 100) : 0;
  document.getElementById('kcal-val').textContent    = kcal;
  document.getElementById('kcal-target').textContent = tgt.kcal ? Math.round(tgt.kcal) : '–';
  document.getElementById('kcal-bar').style.width    = kcalPct + '%';

  if (kcal > 0) ['mp-prot', 'mp-carb', 'mp-fat'].forEach(triggerBounce);

  // Confetti when calories goal reached (within 5% margin)
  if (tKcal > 0 && ratio >= 0.95 && ratio <= 1.05) launchConfetti();

  renderMealCards(S.today?.meals || []);
}

function setMacroPill(key, val, target) {
  const pct = target > 0 ? Math.min((val / target) * 100, 100) : 0;
  document.getElementById(key + '-val').textContent    = Math.round(val || 0);
  document.getElementById(key + '-target').textContent = target ? Math.round(target) : '–';
  document.getElementById(key + '-bar').style.width    = pct + '%';
}

function triggerBounce(id) {
  const el = document.getElementById(id);
  el.classList.remove('bounce');
  void el.offsetWidth;
  el.classList.add('bounce');
}

// ════════════════════════════════════════════════════════════════════════════
// MEAL CARDS
// ════════════════════════════════════════════════════════════════════════════
function renderMealCards(meals) {
  const byType = {};
  meals.forEach(m => { byType[m.meal_type] = m; });

  document.getElementById('meals-container').innerHTML =
    Object.entries(MEALS).map(([type, meta]) => {
      const meal  = byType[type];
      const items = meal?.items || [];
      const kcal  = meal ? Math.round(meal.total_kcal || 0) : 0;
      return `
        <div class="card">
          <div class="meal-hd">
            <div class="meal-hd-left">
              <span class="meal-emoji">${meta.emoji}</span>
              <span class="meal-name">${meta.label}</span>
            </div>
            <div style="display:flex;align-items:center;gap:10px;">
              <span class="meal-kcal-lbl">${kcal} kcal</span>
              <button class="btn-meal-plus" onclick="openInputModal('${type}')">+</button>
            </div>
          </div>
          ${items.length
            ? items.map(it => `
                <div class="meal-item-row">
                  <div class="item-dot"></div>
                  <span class="item-name">${it.name}</span>
                  <span class="item-info">${it.qty_g}g · ${Math.round(it.kcal)} kcal</span>
                  ${meal ? `<span class="item-del" onclick="deleteMeal(${meal.id})">✕</span>` : ''}
                </div>`).join('')
            : `<p class="meal-empty">Aucun aliment enregistré</p>`
          }
        </div>`;
    }).join('');
}

// ════════════════════════════════════════════════════════════════════════════
// MACROS TAB
// ════════════════════════════════════════════════════════════════════════════
function renderMacros() {
  const tot = S.today?.totals  || {};
  const tgt = S.today?.targets || {};
  const pro = S.profile        || {};

  const pct = (val, target) => target > 0 ? Math.min((val / target) * 100, 100) : 0;
  const r   = v => Math.round(v || 0);

  // Glucides
  const carb = tot.carb || 0, cs = tot.carb_simple || 0, cc = tot.carb_complex || 0;
  document.getElementById('mc-carb-val').textContent    = r(carb);
  document.getElementById('mc-carb-target').textContent = tgt.carb ? r(tgt.carb) : '–';
  document.getElementById('mc-carb-bar').style.width    = pct(carb, tgt.carb) + '%';
  const cSplit = cs + cc || 1;
  document.getElementById('mc-carb-simple-seg').style.flex  = cs / cSplit;
  document.getElementById('mc-carb-complex-seg').style.flex = cc / cSplit;
  document.getElementById('mc-carb-simple-val').textContent  = r(cs) + 'g';
  document.getElementById('mc-carb-complex-val').textContent = r(cc) + 'g';
  document.getElementById('mc-carb-simple-pct').textContent  = cs + cc > 0 ? '(' + r(cs / cSplit * 100) + '%)' : '';
  document.getElementById('mc-carb-complex-pct').textContent = cs + cc > 0 ? '(' + r(cc / cSplit * 100) + '%)' : '';

  // Lipides
  const fat = tot.fat || 0, fs = tot.fat_sat || 0, fu = tot.fat_unsat || 0;
  document.getElementById('mc-fat-val').textContent    = r(fat);
  document.getElementById('mc-fat-target').textContent = tgt.fat ? r(tgt.fat) : '–';
  document.getElementById('mc-fat-bar').style.width    = pct(fat, tgt.fat) + '%';
  const fSplit = fs + fu || 1;
  document.getElementById('mc-fat-sat-seg').style.flex   = fs / fSplit;
  document.getElementById('mc-fat-unsat-seg').style.flex = fu / fSplit;
  document.getElementById('mc-fat-sat-val').textContent   = r(fs) + 'g';
  document.getElementById('mc-fat-unsat-val').textContent = r(fu) + 'g';
  document.getElementById('mc-fat-sat-pct').textContent   = fs + fu > 0 ? '(' + r(fs / fSplit * 100) + '%)' : '';
  document.getElementById('mc-fat-unsat-pct').textContent = fs + fu > 0 ? '(' + r(fu / fSplit * 100) + '%)' : '';

  // Protéines
  const prot = tot.prot || 0;
  document.getElementById('mc-prot-val').textContent    = r(prot);
  document.getElementById('mc-prot-target').textContent = tgt.prot ? r(tgt.prot) : '–';
  document.getElementById('mc-prot-bar').style.width    = pct(prot, tgt.prot) + '%';
  document.getElementById('mc-prot-pkg').textContent    = pro.weight_kg && prot > 0
    ? (prot / pro.weight_kg).toFixed(1) + ' g / kg de poids corporel' : '';

  // Fibres
  const fiber = tot.fiber || 0;
  document.getElementById('mc-fiber-val').textContent = r(fiber);
  document.getElementById('mc-fiber-bar').style.width = pct(fiber, 25) + '%';
  const badge = document.getElementById('mc-fiber-badge');
  badge.classList.remove('hidden');
  if (fiber < 10) {
    badge.style.cssText = 'display:inline-flex;align-items:center;gap:5px;padding:4px 12px;border-radius:20px;font-size:11px;font-weight:800;background:#FFEBEE;color:#c62828;margin-top:8px;';
    badge.textContent = '🔴 Apport insuffisant (< 10g)';
  } else if (fiber < 20) {
    badge.style.cssText = 'display:inline-flex;align-items:center;gap:5px;padding:4px 12px;border-radius:20px;font-size:11px;font-weight:800;background:#FFF8E1;color:#e65100;margin-top:8px;';
    badge.textContent = '🟡 Apport à améliorer';
  } else {
    badge.style.cssText = 'display:inline-flex;align-items:center;gap:5px;padding:4px 12px;border-radius:20px;font-size:11px;font-weight:800;background:var(--sage-bg);color:var(--sage);margin-top:8px;';
    badge.textContent = '🟢 Bon apport en fibres';
  }

  // Micronutriments
  const gender = pro.gender || 'homme';
  const ironT  = gender === 'femme' ? 18 : 8;
  const vitcT  = gender === 'femme' ? 75 : 90;
  document.getElementById('mc-iron-target-lbl').textContent = ironT + ' mg';
  document.getElementById('mc-vitc-target-lbl').textContent = vitcT + ' mg';

  [
    { id: 'sodium',    val: tot.sodium    || 0, target: 2300, color: '#f87171', warnOver: true  },
    { id: 'calcium',   val: tot.calcium   || 0, target: 1000, color: '#64b5f6', warnOver: false },
    { id: 'iron',      val: tot.iron      || 0, target: ironT, color: '#f9a825', warnOver: false },
    { id: 'vitc',      val: tot.vit_c     || 0, target: vitcT, color: '#ff8a65', warnOver: false },
    { id: 'potassium', val: tot.potassium || 0, target: 3500, color: '#81c784', warnOver: false },
  ].forEach(({ id, val, target, color, warnOver }) => {
    const bar = document.getElementById('mc-' + id + '-bar');
    bar.style.width      = pct(val, target) + '%';
    bar.style.background = warnOver && val > target ? 'var(--red)' : color;
    document.getElementById('mc-' + id + '-val').textContent = r(val) + ' mg';
  });
}

// ════════════════════════════════════════════════════════════════════════════
// HISTORY + CHARTS
// ════════════════════════════════════════════════════════════════════════════
async function loadHistory(days) {
  S.historyDays = days;
  document.getElementById('btn-7j').classList.toggle('active',  days === 7);
  document.getElementById('btn-30j').classList.toggle('active', days === 30);

  document.getElementById('history-list').innerHTML = '<div class="spinner"></div>';

  try {
    const data = await api('/history?days=' + days);
    renderHistoryCharts(data);
    renderHistoryStats(data);
    renderHistoryList(data);
  } catch (e) {
    _noCharts();
    document.getElementById('history-list').innerHTML =
      '<p style="text-align:center;color:var(--light);font-size:13px;">Impossible de charger l\'historique</p>';
  }
}

function _chartDefaults(tickLimit) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        labels: {
          font: { family: "'Nunito', sans-serif", weight: '700', size: 11 },
          boxWidth: 10, padding: 12, usePointStyle: true,
        },
      },
      tooltip: {
        backgroundColor: '#3A3328',
        titleFont: { family: "'Nunito', sans-serif", size: 11, weight: '800' },
        bodyFont:  { family: "'Nunito', sans-serif", size: 11 },
        padding: 10, cornerRadius: 10, displayColors: true,
      },
    },
    scales: {
      x: {
        border: { display: false },
        grid:   { color: '#E4DCCA' },
        ticks: {
          font: { family: "'Nunito', sans-serif", size: 10, weight: '700' },
          maxRotation: 45, maxTicksLimit: tickLimit,
        },
      },
      y: {
        border: { display: false },
        grid:   { color: '#E4DCCA' },
        ticks: { font: { family: "'Nunito', sans-serif", size: 10, weight: '600' } },
        beginAtZero: true,
      },
    },
  };
}

function renderHistoryCharts(data) {
  if (!data.length) { _noCharts(); return; }

  // Sort oldest → newest for left-to-right reading
  const sorted = [...data].reverse();
  const tickLimit = S.historyDays <= 7 ? 7 : 10;

  const labels = sorted.map(d =>
    new Date(d.date + 'T12:00').toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' })
  );

  // Destroy previous instances
  if (S.charts.kcal)   { S.charts.kcal.destroy();   S.charts.kcal   = null; }
  if (S.charts.macros) { S.charts.macros.destroy(); S.charts.macros = null; }

  // ── Calories bar chart ──────────────────────────────
  const kcalCanvas = document.getElementById('chart-kcal');
  kcalCanvas.style.display = 'block';
  document.getElementById('chart-hint').style.display = 'none';

  const kcalDatasets = [{
    label: 'Calories',
    data: sorted.map(d => Math.round(d.kcal || 0)),
    backgroundColor: 'rgba(125,155,118,0.75)',
    borderColor:     '#7D9B76',
    borderWidth: 0,
    borderRadius: 6,
    borderSkipped: false,
  }];

  if (S.profile?.target_kcal) {
    kcalDatasets.push({
      label: 'Objectif',
      data: sorted.map(() => Math.round(S.profile.target_kcal)),
      type: 'line',
      borderColor:   '#F4A35A',
      borderWidth:   2,
      borderDash:    [6, 4],
      pointRadius:   0,
      fill:          false,
      tension:       0,
    });
  }

  S.charts.kcal = new Chart(kcalCanvas, {
    type: 'bar',
    data: { labels, datasets: kcalDatasets },
    options: {
      ..._chartDefaults(tickLimit),
      plugins: {
        ..._chartDefaults(tickLimit).plugins,
        tooltip: {
          ..._chartDefaults(tickLimit).plugins.tooltip,
          callbacks: { label: ctx => ` ${ctx.dataset.label} : ${ctx.parsed.y} kcal` },
        },
      },
    },
  });

  // ── Macros line chart ───────────────────────────────
  const macrosCanvas = document.getElementById('chart-macros');
  macrosCanvas.style.display = 'block';
  document.getElementById('chart-macros-hint').style.display = 'none';

  S.charts.macros = new Chart(macrosCanvas, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Protéines (g)',
          data: sorted.map(d => Math.round(d.prot || 0)),
          borderColor: '#7D9B76', backgroundColor: 'rgba(125,155,118,0.08)',
          borderWidth: 2.5, tension: 0.4, fill: true,
          pointRadius: 4, pointBackgroundColor: '#7D9B76',
          pointBorderColor: '#fff', pointBorderWidth: 2,
        },
        {
          label: 'Glucides (g)',
          data: sorted.map(d => Math.round(d.carb || 0)),
          borderColor: '#F4A35A', backgroundColor: 'rgba(244,163,90,0.08)',
          borderWidth: 2.5, tension: 0.4, fill: true,
          pointRadius: 4, pointBackgroundColor: '#F4A35A',
          pointBorderColor: '#fff', pointBorderWidth: 2,
        },
        {
          label: 'Lipides (g)',
          data: sorted.map(d => Math.round(d.fat || 0)),
          borderColor: '#F9C784', backgroundColor: 'rgba(249,199,132,0.08)',
          borderWidth: 2.5, tension: 0.4, fill: true,
          pointRadius: 4, pointBackgroundColor: '#F9C784',
          pointBorderColor: '#fff', pointBorderWidth: 2,
        },
      ],
    },
    options: {
      ..._chartDefaults(tickLimit),
      plugins: {
        ..._chartDefaults(tickLimit).plugins,
        tooltip: {
          ..._chartDefaults(tickLimit).plugins.tooltip,
          callbacks: { label: ctx => ` ${ctx.dataset.label} : ${ctx.parsed.y}g` },
        },
      },
    },
  });
}

function _noCharts() {
  document.getElementById('chart-hint').style.display        = 'block';
  document.getElementById('chart-kcal').style.display        = 'none';
  document.getElementById('chart-macros').style.display      = 'none';
  document.getElementById('chart-macros-hint').style.display = 'none';
  document.getElementById('history-stats').style.display     = 'none';
}

function renderHistoryStats(data) {
  const el = document.getElementById('history-stats');
  if (!data.length) { el.style.display = 'none'; return; }
  const kcals = data.map(d => d.kcal || 0);
  const avg  = Math.round(kcals.reduce((a, b) => a + b, 0) / kcals.length);
  const best = Math.round(Math.max(...kcals));
  document.getElementById('stat-avg').textContent  = avg;
  document.getElementById('stat-best').textContent = best;
  document.getElementById('stat-days').textContent = data.length;
  el.style.display = 'block';
}

function renderHistoryList(data) {
  const list = document.getElementById('history-list');
  if (!data.length) {
    list.innerHTML = '<p style="text-align:center;color:var(--light);font-size:13px;font-weight:600;padding:10px 0;">Aucun repas enregistré pour cette période</p>';
    return;
  }
  list.innerHTML = data.map(d => {
    const label = new Date(d.date + 'T12:00').toLocaleDateString('fr-FR',
      { weekday: 'short', day: 'numeric', month: 'short' });
    return `
      <div class="history-row">
        <div>
          <div class="hist-date">${label}</div>
          <div class="hist-macros">P : ${Math.round(d.prot||0)}g &nbsp;·&nbsp; G : ${Math.round(d.carb||0)}g &nbsp;·&nbsp; L : ${Math.round(d.fat||0)}g</div>
        </div>
        <div class="hist-kcal">${Math.round(d.kcal||0)} kcal</div>
      </div>`;
  }).join('');
}

// ════════════════════════════════════════════════════════════════════════════
// PROFILE
// ════════════════════════════════════════════════════════════════════════════
async function loadProfile() {
  try {
    S.profile = await api('/profile');
    _fillForm(S.profile);
    _showTargetBox(S.profile);
  } catch (_) { /* first launch — no profile yet */ }
}

function _fillForm(p) {
  if (!p) return;
  document.getElementById('p-name').value   = p.name      || '';
  document.getElementById('p-age').value    = p.age       || '';
  document.getElementById('p-weight').value = p.weight_kg || '';
  document.getElementById('p-height').value = p.height_cm || '';
  S.gender = p.gender || 'homme';
  S.goal   = p.goal   || null;
  _syncGender();
  _syncGoal();
}

function setGender(g) { S.gender = g; _syncGender(); }
function _syncGender() {
  document.getElementById('btn-homme').classList.toggle('active', S.gender === 'homme');
  document.getElementById('btn-femme').classList.toggle('active', S.gender === 'femme');
}

function setGoal(g) { S.goal = g; _syncGoal(); }
function _syncGoal() {
  ['masse', 'recompo', 'graisse'].forEach(g =>
    document.getElementById('goal-' + g).classList.toggle('active', S.goal === g));
}

async function saveProfile() {
  const name   = document.getElementById('p-name').value.trim();
  const age    = +document.getElementById('p-age').value;
  const weight = +document.getElementById('p-weight').value;
  const height = +document.getElementById('p-height').value;

  if (!name || !age || !weight || !height || !S.goal) {
    toast('⚠️ Remplis tous les champs et choisis un objectif'); return;
  }
  try {
    S.profile = await api('/profile', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ name, age, weight_kg: weight, height_cm: height, gender: S.gender, goal: S.goal }),
    });
    _showTargetBox(S.profile);
    toast('✅ Profil enregistré !');
    loadToday();
  } catch (e) { toast('❌ ' + e.message); }
}

function _showTargetBox(p) {
  if (!p?.target_kcal) return;
  document.getElementById('target-box').classList.remove('hidden');
  document.getElementById('t-kcal').textContent = Math.round(p.target_kcal) + ' kcal';
  document.getElementById('t-prot').textContent = Math.round(p.target_prot) + ' g';
  document.getElementById('t-carb').textContent = Math.round(p.target_carb) + ' g';
  document.getElementById('t-fat').textContent  = Math.round(p.target_fat)  + ' g';
}

// ════════════════════════════════════════════════════════════════════════════
// DELETE MEAL
// ════════════════════════════════════════════════════════════════════════════
async function deleteMeal(id) {
  try {
    await api('/meals/' + id, { method: 'DELETE' });
    toast('Repas supprimé');
    loadToday();
  } catch (e) { toast('❌ ' + e.message); }
}

// ════════════════════════════════════════════════════════════════════════════
// INPUT MODAL
// ════════════════════════════════════════════════════════════════════════════
function openInputModal(mealType) {
  S.mealType = mealType;
  const meta = MEALS[mealType];
  document.getElementById('modal-title').textContent = meta.emoji + ' ' + meta.label;
  document.getElementById('modal-sub').textContent   = 'Comment saisir ce repas ?';
  document.getElementById('recent-meals-section').classList.add('hidden');
  showMode(null);
  document.getElementById('modal-input').classList.remove('hidden');
  loadRecentMeals(mealType);
}

// ─── Repas récents ────────────────────────────────────────────────────────────

// ─── Planned meals helpers ────────────────────────────────────────────────────

function getPlannedMeals(mealType) {
  if (!S.weeklyPlan?.days) return [];
  const seen = new Set();
  const result = [];
  for (const day of S.weeklyPlan.days) {
    const m = day.meals?.[mealType];
    if (m?.name && !seen.has(m.name)) {
      seen.add(m.name);
      result.push({ ...m, _day: day.day, _added: S.addedPlannedMeals.has(m.name) });
    }
  }
  return result;
}

async function loadRecentMeals(mealType) {
  const section = document.getElementById('recent-meals-section');
  const scroll  = document.getElementById('recent-meals-scroll');

  // Planned meals first
  const planned = getPlannedMeals(mealType)
    .map(p => ({ _type: 'planned', _plan: p, total_kcal: p.kcal || 0 }));

  // Historical meals
  let historical = [];
  try {
    historical = (await api(`/meals/recent/${mealType}?limit=5`))
      .map(h => ({ _type: 'history', ...h }));
  } catch (_) {}

  _recentMeals = [...planned, ...historical];
  if (!_recentMeals.length) { section.classList.add('hidden'); return; }

  const today = new Date();
  scroll.innerHTML = _recentMeals.map((m, i) => {
    if (m._type === 'planned') {
      const p = m._plan;
      const preview = (p.items || []).slice(0, 2).join(' · ')
                    + ((p.items?.length > 2) ? ` +${p.items.length - 2}` : '');
      const isAdded = p._added;
      return `
        <div class="recent-card" style="${isAdded ? 'opacity:.55;' : ''}" onclick="reuseRecentMeal(${i})">
          <div class="recent-kcal">${p.kcal || '–'} kcal</div>
          <div class="recent-items">${preview || p.name}</div>
          <div class="recent-date" style="color:var(--orange);font-weight:800;">📅 ${p._day}</div>
          <button class="btn-recent-add" style="background:var(--orange);"
                  onclick="event.stopPropagation(); reuseRecentMeal(${i})">
            ${isAdded ? '✓ Ajouté' : 'Planifié'}
          </button>
        </div>`;
    }
    // Historical
    const mealDate = new Date(m.date + 'T12:00');
    const diffDays = Math.round((today - mealDate) / 86_400_000);
    const dayLabel = diffDays === 1 ? 'hier' : diffDays === 0 ? 'aujourd\'hui' : `il y a ${diffDays} j`;
    const items = m.items || [];
    const preview = items.slice(0, 3).map(it => it.name).join(' · ')
                  + (items.length > 3 ? ` +${items.length - 3}` : '');
    return `
      <div class="recent-card" onclick="reuseRecentMeal(${i})">
        <div class="recent-kcal">${Math.round(m.total_kcal)} kcal</div>
        <div class="recent-items">${preview}</div>
        <div class="recent-date">${dayLabel}</div>
        <button class="btn-recent-add" onclick="event.stopPropagation(); reuseRecentMeal(${i})">
          Ajouter
        </button>
      </div>`;
  }).join('');

  section.classList.remove('hidden');
}

async function reuseRecentMeal(idx) {
  const m = _recentMeals[idx];
  if (!m) return;

  if (m._type === 'planned') {
    const plan  = m._plan;
    const items = plan.items || [];
    if (!items.length) return;
    closeInputModal();
    try {
      const data = await api('/meals/text', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ text: items.join(', ') }),
      });
      S.addedPlannedMeals.add(plan.name);
      openConfirmModal(data.items);
    } catch (e) { toast('❌ ' + e.message); }
    return;
  }

  if (!m.items?.length) return;
  openConfirmModal(m.items);
}

function closeInputModal() {
  document.getElementById('modal-input').classList.add('hidden');
  stopRecording();
}

function showMode(mode) {
  ['mode-select', 'mode-voice', 'mode-photo', 'mode-manual'].forEach(id => {
    document.getElementById(id).classList.toggle('hidden', id !== 'mode-select');
  });
  if (mode === null) return;
  document.getElementById('mode-select').classList.add('hidden');
  document.getElementById('mode-' + mode).classList.remove('hidden');

  if (mode === 'voice') {
    document.getElementById('transcription-area').classList.add('hidden');
    document.getElementById('voice-loader').classList.add('hidden');
    document.getElementById('waveform').classList.add('hidden');
    document.getElementById('record-btn').classList.remove('rec');
    document.getElementById('record-btn').textContent     = '🎤';
    document.getElementById('record-status').textContent  = 'Appuie pour enregistrer';
    S.isRecording = false;
  }
  if (mode === 'photo')  document.getElementById('photo-loader').classList.add('hidden');
  if (mode === 'manual') {
    document.getElementById('manual-text').value = '';
    document.getElementById('manual-loader').classList.add('hidden');
    document.getElementById('food-lib-search').value = '';
    loadFoodLibrary();
  }
}

// ════════════════════════════════════════════════════════════════════════════
// VOICE RECORDING
// ════════════════════════════════════════════════════════════════════════════
async function toggleRecording() {
  S.isRecording ? stopRecording() : await startRecording();
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    S.audioChunks   = [];
    S.mediaRecorder = new MediaRecorder(stream);
    S.mediaRecorder.ondataavailable = e => { if (e.data.size) S.audioChunks.push(e.data); };
    S.mediaRecorder.onstop = _uploadVoice;
    S.mediaRecorder.start(250);
    S.isRecording = true;

    const btn = document.getElementById('record-btn');
    btn.textContent = '⏹';
    btn.classList.add('rec');
    document.getElementById('record-status').textContent = 'Enregistrement… Appuie pour arrêter';
    document.getElementById('waveform').classList.remove('hidden');
  } catch (e) {
    toast('⚠️ Micro non disponible : ' + e.message);
  }
}

function stopRecording() {
  if (S.mediaRecorder && S.isRecording) {
    S.mediaRecorder.stop();
    S.mediaRecorder.stream.getTracks().forEach(t => t.stop());
  }
  S.isRecording = false;
  const btn = document.getElementById('record-btn');
  if (btn) { btn.textContent = '🎤'; btn.classList.remove('rec'); }
  const wf = document.getElementById('waveform');
  if (wf) wf.classList.add('hidden');
}

async function _uploadVoice() {
  document.getElementById('voice-loader').classList.remove('hidden');
  document.getElementById('record-status').textContent = 'Analyse en cours…';

  const blob = new Blob(S.audioChunks, { type: 'audio/webm' });
  const form = new FormData();
  form.append('audio', blob, 'audio.webm');

  try {
    const data = await fetch(API + '/meals/voice', { method: 'POST', body: form })
      .then(r => { if (!r.ok) throw new Error('Erreur API'); return r.json(); });

    document.getElementById('voice-loader').classList.add('hidden');
    document.getElementById('transcription-area').classList.remove('hidden');
    document.getElementById('transcription-text').textContent = data.transcription;
    openConfirmModal(data.items);
  } catch (_) {
    document.getElementById('voice-loader').classList.add('hidden');
    document.getElementById('record-status').textContent = 'Erreur — réessaie';
    toast('❌ Transcription échouée');
  }
}

// ════════════════════════════════════════════════════════════════════════════
// PHOTO
// ════════════════════════════════════════════════════════════════════════════
async function handlePhoto(e) {
  const file = e.target.files[0];
  if (!file) return;
  document.getElementById('photo-loader').classList.remove('hidden');

  const form = new FormData();
  form.append('image', file);
  try {
    const data = await fetch(API + '/meals/photo', { method: 'POST', body: form })
      .then(r => { if (!r.ok) throw new Error(); return r.json(); });
    document.getElementById('photo-loader').classList.add('hidden');
    openConfirmModal(data.items);
  } catch (_) {
    document.getElementById('photo-loader').classList.add('hidden');
    toast('❌ Analyse photo échouée');
  }
}

// ════════════════════════════════════════════════════════════════════════════
// MANUAL TEXT
// ════════════════════════════════════════════════════════════════════════════
async function analyzeManual() {
  const text = document.getElementById('manual-text').value.trim();
  if (!text) { toast('⚠️ Décris ton repas d\'abord'); return; }

  document.getElementById('manual-loader').classList.remove('hidden');
  try {
    const data = await api('/meals/text', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ text }),
    });
    document.getElementById('manual-loader').classList.add('hidden');
    openConfirmModal(data.items);
  } catch (e) {
    document.getElementById('manual-loader').classList.add('hidden');
    toast('❌ ' + e.message);
  }
}

// ════════════════════════════════════════════════════════════════════════════
// CONFIRM MODAL
// ════════════════════════════════════════════════════════════════════════════
function openConfirmModal(items) {
  S.pendingItems = items;
  closeInputModal();

  const total = items.reduce((s, i) => s + (i.kcal || 0), 0);
  document.getElementById('confirm-list').innerHTML = items.map((it, i) => `
    <div class="confirm-row">
      <div class="confirm-num">${i + 1}</div>
      <div class="confirm-info">
        <div class="confirm-name">${it.name}</div>
        <div class="confirm-macros">${it.qty_g}g &nbsp;·&nbsp; P: ${it.prot_g}g &nbsp;G: ${it.carb_g}g &nbsp;L: ${it.fat_g}g</div>
      </div>
      <div class="confirm-kcal">${Math.round(it.kcal)} kcal</div>
    </div>`).join('');

  document.getElementById('confirm-total').textContent = Math.round(total) + ' kcal';
  document.getElementById('modal-confirm').classList.remove('hidden');
}

async function confirmMeal() {
  const today = new Date().toISOString().split('T')[0];
  try {
    await api('/meals/confirm', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ date: today, meal_type: S.mealType, description: '', items: S.pendingItems }),
    });
    document.getElementById('modal-confirm').classList.add('hidden');
    toast('✅ Repas enregistré !');
    loadToday();
  } catch (e) { toast('❌ ' + e.message); }
}

// ════════════════════════════════════════════════════════════════════════════
// TOAST
// ════════════════════════════════════════════════════════════════════════════
let _toastTimer;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
}

// ════════════════════════════════════════════════════════════════════════════
// CONFETTI — objectif calorique atteint
// ════════════════════════════════════════════════════════════════════════════
function launchConfetti() {
  const container = document.createElement('div');
  container.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:9000;overflow:hidden;';
  document.body.appendChild(container);

  const colors  = ['#7D9B76', '#F4A35A', '#F9C784', '#A8C4A2', '#F5F0E0', '#fff'];
  const count   = 55;
  const pieces  = [];

  for (let i = 0; i < count; i++) {
    const el    = document.createElement('div');
    const color = colors[i % colors.length];
    const size  = 6 + (i % 7);
    const delay = (i * 60) % 500;
    const dur   = 1600 + (i * 30) % 1200;
    const left  = (i * 37) % 100;
    const round = i % 3 === 0 ? '50%' : '2px';

    el.style.cssText = `
      position:absolute; width:${size}px; height:${size}px;
      background:${color}; border-radius:${round};
      left:${left}%; top:-20px;
      animation: confettiFall ${dur}ms ease-in ${delay}ms forwards;
      transform: rotate(${(i * 47) % 360}deg);
    `;
    container.appendChild(el);
    pieces.push(el);
  }

  toast('🎉 Objectif atteint ! Bravo !');
  setTimeout(() => container.remove(), 4500);
}

// ════════════════════════════════════════════════════════════════════════════
// WEEKLY PLAN
// ════════════════════════════════════════════════════════════════════════════

const DAY_META = [
  { key: 'lundi',     emoji: '🌱', bg: 'var(--sage-bg)'   },
  { key: 'mardi',     emoji: '💪', bg: 'var(--orange-bg)' },
  { key: 'mercredi',  emoji: '🥗', bg: 'var(--peach-bg)'  },
  { key: 'jeudi',     emoji: '🔥', bg: '#F0F0FF'          },
  { key: 'vendredi',  emoji: '🎯', bg: '#FFF0F5'          },
];

const MEAL_TYPE_META = {
  petit_dej: { label: 'Petit déjeuner', emoji: '🌅' },
  dejeuner:  { label: 'Déjeuner',       emoji: '🌞' },
  gouter:    { label: 'Goûter',         emoji: '🍎' },
  diner:     { label: 'Dîner',          emoji: '🌙' },
};

const SHOP_ICONS = {
  'Viandes & Poissons': '🥩',
  'Légumes':            '🥦',
  'Féculents':          '🌾',
  'Produits laitiers':  '🥚',
  'Fruits':             '🍎',
  'Épicerie':           '🫙',
};

function setBatchSize(n) {
  S.weekPlanConfig.batch_size = n;
  document.querySelectorAll('.batch-btn').forEach(btn => {
    btn.classList.toggle('active', +btn.dataset.n === n);
  });
}

async function generateWeeklyPlan() {
  const allTypes = ['petit_dej', 'dejeuner', 'gouter', 'diner'];
  const mealTypes = allTypes.filter(t => document.getElementById('wc-' + t)?.checked);
  if (!mealTypes.length) { toast('⚠️ Sélectionne au moins un repas'); return; }

  S.weekPlanConfig.meal_types = mealTypes;
  S.addedPlannedMeals = new Set();

  const btn = document.getElementById('btn-generate-week');
  btn.disabled = true;
  document.getElementById('week-loader').classList.remove('hidden');
  document.getElementById('week-days').innerHTML = '';
  document.getElementById('week-shopping').classList.add('hidden');

  try {
    const data = await api('/weekly-plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(S.weekPlanConfig),
    });
    S.weeklyPlan = data;
    renderWeeklyPlan(data);
    toast('✅ Plan semaine généré !');
  } catch (e) {
    toast('❌ ' + e.message);
  } finally {
    document.getElementById('week-loader').classList.add('hidden');
    btn.disabled = false;
  }
}

function renderWeeklyPlan(data) {
  const days  = data.days  || [];
  const daysEl = document.getElementById('week-days');

  daysEl.innerHTML = days.map((d, i) => {
    const meta   = DAY_META[i] || { key: d.day.toLowerCase(), emoji: '📈', bg: 'var(--beige)' };
    const meals  = d.meals || {};
    const isFirst = i === 0;

    const batchN    = S.weekPlanConfig.batch_size;
    const mealsHtml = Object.keys(meals).map(type => {
      const m  = meals[type];
      if (!m) return '';
      const mt = MEAL_TYPE_META[type] || { label: type, emoji: '🍽️' };
      const batchBadge = m.batch
        ? `<span class="batch-badge">🍳 Batch ×${batchN}</span>` : '';
      const itemsHtml = (m.items || [])
        .map(it => `<div class="week-meal-item">${it}</div>`).join('');

      return `
        <div class="week-meal-block">
          <div class="week-meal-hd">
            <span>${mt.emoji}</span>
            <span class="week-meal-type">${mt.label}</span>
            ${batchBadge}
          </div>
          <div class="week-meal-name">${m.name}</div>
          ${itemsHtml}
          <div class="week-meal-macros">
            ${m.kcal} kcal &nbsp;·&nbsp; P&nbsp;${m.prot_g}g
            ${m.carb_g != null ? `&nbsp;·&nbsp; G&nbsp;${m.carb_g}g` : ''}
            ${m.fat_g  != null ? `&nbsp;·&nbsp; L&nbsp;${m.fat_g}g`  : ''}
          </div>
        </div>`;
    }).join('');

    return `
      <div class="card" style="margin-bottom:10px;">
        <div class="day-card-hd" onclick="toggleDay('${meta.key}')">
          <div class="day-hd-left">
            <div class="day-dot" style="background:${meta.bg};">${meta.emoji}</div>
            <div>
              <div class="day-name-big">${d.day}</div>
              <div class="day-kcal-hint">${d.total_kcal} kcal &nbsp;·&nbsp; ${d.total_prot}g prot.</div>
            </div>
          </div>
          <span class="day-chevron ${isFirst ? 'open' : ''}" id="chev-${meta.key}">▼</span>
        </div>
        <div class="day-body ${isFirst ? 'open' : ''}" id="body-${meta.key}"
             style="margin-top:${isFirst ? '12' : '0'}px;">
          ${mealsHtml}
        </div>
      </div>`;
  }).join('');

  if (data.shopping_list) {
    renderShoppingList(data.shopping_list);
    document.getElementById('week-shopping').classList.remove('hidden');
  }
}

function toggleDay(key) {
  const body   = document.getElementById('body-' + key);
  const chev   = document.getElementById('chev-' + key);
  const isOpen = body.classList.contains('open');
  body.classList.toggle('open', !isOpen);
  body.style.marginTop = isOpen ? '0' : '12px';
  chev.classList.toggle('open', !isOpen);
}

function renderShoppingList(list) {
  document.getElementById('week-shopping-content').innerHTML =
    Object.entries(list).map(([cat, items]) => {
      const icon = SHOP_ICONS[cat] || '🛒';
      const rows = (items || []).map((it, i) => {
        const id  = `shop-${cat.replace(/[^a-z]/gi, '-')}-${i}`;
        const note = it.note ? `<div class="shop-note">${it.note}</div>` : '';
        return `
          <div class="shop-item" id="shoprow-${id}">
            <input type="checkbox" class="shop-check" id="${id}"
                   onchange="toggleShopItem('${id}')">
            <div class="shop-label">
              <div class="shop-name">${it.item}</div>
              <div class="shop-qty">${it.qty}</div>
              ${note}
            </div>
          </div>`;
      }).join('');

      return `
        <div class="shop-section">
          <div class="shop-cat-title">${icon} ${cat}</div>
          ${rows}
        </div>`;
    }).join('');
}

function toggleShopItem(id) {
  const row = document.getElementById('shoprow-' + id);
  const cb  = document.getElementById(id);
  row.classList.toggle('shop-checked', cb.checked);
}

// ════════════════════════════════════════════════════════════════════════════
// FOOD LIBRARY
// ════════════════════════════════════════════════════════════════════════════

async function loadFoodLibrary() {
  try {
    _foodLibrary = await api('/food-library');
    const countEl = document.getElementById('food-lib-count');
    if (countEl) countEl.textContent = _foodLibrary.length + ' aliments';
    renderFoodLib(_foodLibrary);
  } catch (_) {
    renderFoodLib([]);
  }
}

function filterFoodLib(query) {
  const q = query.toLowerCase().trim();
  renderFoodLib(q
    ? _foodLibrary.filter(f => f.name.toLowerCase().includes(q))
    : _foodLibrary
  );
}

function renderFoodLib(items) {
  const el = document.getElementById('food-lib-list');
  if (!el) return;

  if (!items.length) {
    el.innerHTML = '<p style="text-align:center;color:var(--light);font-size:12px;padding:8px 0;">Aucun aliment trouvé</p>';
    return;
  }

  el.innerHTML = items.slice(0, 40).map(f => {
    const kcalPortion = Math.round((f.kcal || 0) * (f.qty_ref_g || 100) / 100);
    const badge = f.use_count > 2
      ? '<span class="food-lib-badge">✓ connu</span>' : '';
    const safeName = f.name.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    return `
      <div class="food-lib-item" onclick="selectFoodLibItem('${safeName}', ${f.qty_ref_g || 100})">
        <span class="food-lib-name">${f.name}</span>
        <span class="food-lib-meta">${Math.round(f.qty_ref_g || 100)}g · ${kcalPortion} kcal</span>
        ${badge}
      </div>`;
  }).join('');
}

function selectFoodLibItem(name, qtyRef) {
  const ta = document.getElementById('manual-text');
  const current = ta.value.trim();
  const addition = `${name} ${Math.round(qtyRef)}g`;
  ta.value = current ? current + ', ' + addition : addition;

  // Reset search + scroll list back to top
  const searchEl = document.getElementById('food-lib-search');
  if (searchEl) { searchEl.value = ''; filterFoodLib(''); }
  const listEl = document.getElementById('food-lib-list');
  if (listEl) listEl.scrollTop = 0;

  ta.focus();
}
