/* Meeple & Mug — small interactivity layer */

// ===== Nav toggle =====
(function () {
  const btn = document.querySelector('.menu-toggle');
  const nav = document.querySelector('.nav-links');
  if (!btn || !nav) return;
  btn.addEventListener('click', () => {
    nav.classList.toggle('is-open');
    btn.setAttribute('aria-expanded', nav.classList.contains('is-open'));
  });
})();

// ===== Library page: filters =====
(function () {
  const grid = document.querySelector('[data-game-grid]');
  if (!grid) return;

  const players = document.getElementById('f-players');
  const playersOut = document.getElementById('f-players-out');
  const timeChips = document.querySelectorAll('[data-time]');
  const complexityDots = document.querySelectorAll('[data-complexity]');
  const moodChips = document.querySelectorAll('[data-mood]');
  const search = document.getElementById('f-search');
  const sort = document.getElementById('f-sort');
  const availOnly = document.getElementById('f-avail');
  const count = document.querySelector('[data-game-count]');

  const state = {
    players: 4,
    time: new Set(),
    complexity: 0,
    moods: new Set(),
    search: '',
    avail: false,
    sort: 'a-z'
  };

  const cards = Array.from(grid.querySelectorAll('.game-card'));

  function timeBucket(min) {
    if (min <= 30) return 'short';
    if (min <= 60) return 'mid';
    if (min <= 120) return 'long';
    return 'epic';
  }

  function apply() {
    const visible = cards.filter(card => {
      const p = parseInt(card.dataset.minPlayers, 10);
      const pmax = parseInt(card.dataset.maxPlayers, 10);
      if (state.players < p || state.players > pmax) return false;

      const t = parseInt(card.dataset.time, 10);
      if (state.time.size > 0 && !state.time.has(timeBucket(t))) return false;

      const c = parseFloat(card.dataset.complexity);
      if (state.complexity > 0 && c < state.complexity) return false;

      const mood = (card.dataset.mood || '').split(',');
      if (state.moods.size > 0 && !mood.some(m => state.moods.has(m))) return false;

      const status = card.dataset.status;
      if (state.avail && status !== 'onshelf') return false;

      if (state.search) {
        const title = (card.dataset.title || '').toLowerCase();
        if (!title.includes(state.search.toLowerCase())) return false;
      }
      return true;
    });

    cards.forEach(c => (c.style.display = 'none'));

    if (state.sort === 'a-z') visible.sort((a, b) => a.dataset.title.localeCompare(b.dataset.title));
    if (state.sort === 'complexity') visible.sort((a, b) => parseFloat(a.dataset.complexity) - parseFloat(b.dataset.complexity));
    if (state.sort === 'time') visible.sort((a, b) => parseInt(a.dataset.time) - parseInt(b.dataset.time));

    visible.forEach(card => {
      card.style.display = '';
      grid.appendChild(card);
    });

    if (count) count.textContent = visible.length;
  }

  players && players.addEventListener('input', () => {
    state.players = parseInt(players.value, 10);
    if (playersOut) playersOut.textContent = state.players;
    apply();
  });

  timeChips.forEach(chip => {
    chip.addEventListener('click', () => {
      const t = chip.dataset.time;
      if (state.time.has(t)) { state.time.delete(t); chip.classList.remove('chip--purple'); }
      else { state.time.add(t); chip.classList.add('chip--purple'); }
      apply();
    });
  });

  complexityDots.forEach(dot => {
    dot.addEventListener('click', () => {
      const v = parseInt(dot.dataset.complexity, 10);
      state.complexity = state.complexity === v ? 0 : v;
      complexityDots.forEach(d => {
        d.classList.toggle('is-on', parseInt(d.dataset.complexity) <= state.complexity);
      });
      apply();
    });
  });

  moodChips.forEach(chip => {
    chip.addEventListener('click', () => {
      const m = chip.dataset.mood;
      if (state.moods.has(m)) { state.moods.delete(m); chip.classList.remove('chip--tangerine'); }
      else { state.moods.add(m); chip.classList.add('chip--tangerine'); }
      apply();
    });
  });

  search && search.addEventListener('input', () => { state.search = search.value; apply(); });
  sort && sort.addEventListener('change', () => { state.sort = sort.value; apply(); });
  availOnly && availOnly.addEventListener('change', () => { state.avail = availOnly.checked; apply(); });

  apply();
})();

// ===== Events page: month/list toggle =====
(function () {
  const toggle = document.querySelectorAll('[data-view]');
  const grid = document.querySelector('[data-cal-grid]');
  const list = document.querySelector('[data-cal-list]');
  if (!toggle.length || !grid || !list) return;

  toggle.forEach(b => {
    b.addEventListener('click', () => {
      toggle.forEach(x => x.classList.remove('is-active', 'btn--purple'));
      b.classList.add('is-active', 'btn--purple');
      const v = b.dataset.view;
      grid.style.display = v === 'month' ? '' : 'none';
      list.style.display = v === 'list' ? '' : 'none';
    });
  });
})();

// ===== Booking page: stepper + room selection + addons + total =====
(function () {
  const rooms = document.querySelectorAll('[data-room]');
  const addons = document.querySelectorAll('[data-addon]');
  const steps = document.querySelectorAll('[data-step]');
  const stepNav = document.querySelectorAll('[data-go]');
  const summaryRoom = document.querySelector('[data-sum-room]');
  const summaryDate = document.querySelector('[data-sum-date]');
  const summaryAddons = document.querySelector('[data-sum-addons]');
  const summaryTotal = document.querySelector('[data-sum-total]');
  const summaryDeposit = document.querySelector('[data-sum-deposit]');
  const dateInput = document.getElementById('book-date');
  const hoursInput = document.getElementById('book-hours');
  const partyInput = document.getElementById('book-party');

  if (!rooms.length) return;

  const state = { room: null, hours: 3, addons: new Set() };

  function go(stepId) {
    steps.forEach(s => s.style.display = s.dataset.step === stepId ? '' : 'none');
    document.querySelectorAll('.stepper li').forEach(li => {
      li.classList.remove('is-current', 'is-done');
      if (li.dataset.stepLabel === stepId) li.classList.add('is-current');
      if (parseInt(li.dataset.stepIndex) < parseInt(document.querySelector('[data-step-label="' + stepId + '"]').dataset.stepIndex)) {
        li.classList.add('is-done');
      }
    });
    window.scrollTo({ top: document.querySelector('.stepper').offsetTop - 80, behavior: 'smooth' });
  }

  rooms.forEach(r => {
    r.addEventListener('click', () => {
      rooms.forEach(x => x.classList.remove('is-selected'));
      r.classList.add('is-selected');
      state.room = {
        name: r.dataset.room,
        rate: parseFloat(r.dataset.rate),
        capacity: r.dataset.capacity,
        deposit: parseFloat(r.dataset.deposit)
      };
      recalc();
    });
  });

  addons.forEach(a => {
    a.addEventListener('click', () => {
      const key = a.dataset.addon;
      if (state.addons.has(key)) { state.addons.delete(key); a.classList.remove('is-on'); }
      else { state.addons.add(key); a.classList.add('is-on'); }
      recalc();
    });
  });

  hoursInput && hoursInput.addEventListener('input', () => {
    state.hours = parseInt(hoursInput.value || 1, 10);
    recalc();
  });

  function recalc() {
    if (summaryRoom) summaryRoom.textContent = state.room ? state.room.name : '— not selected —';
    if (summaryDate) summaryDate.textContent = (dateInput && dateInput.value ? dateInput.value : '—') + ' · ' + (state.hours) + 'h';
    if (summaryAddons) {
      summaryAddons.innerHTML = '';
      const addonRates = { 'snack-platter': 38, 'host': 65, 'themed': 45 };
      const addonNames = { 'snack-platter': 'Snack platter', 'host': 'Dedicated host', 'themed': 'Themed setup' };
      state.addons.forEach(k => {
        const row = document.createElement('div');
        row.className = 'line';
        row.innerHTML = '<span>+ ' + addonNames[k] + '</span><span>$' + addonRates[k] + '</span>';
        summaryAddons.appendChild(row);
      });
    }
    let total = 0;
    if (state.room) total += state.room.rate * state.hours;
    const addonRates = { 'snack-platter': 38, 'host': 65, 'themed': 45 };
    state.addons.forEach(k => total += addonRates[k] || 0);
    if (summaryTotal) summaryTotal.textContent = '$' + total.toFixed(0);
    if (summaryDeposit && state.room) summaryDeposit.textContent = '$' + state.room.deposit.toFixed(0);
  }

  stepNav.forEach(b => b.addEventListener('click', e => { e.preventDefault(); go(b.dataset.go); }));
  dateInput && dateInput.addEventListener('change', recalc);
  partyInput && partyInput.addEventListener('input', recalc);

  recalc();
})();

// ===== Loyalty calculator =====
(function () {
  const visits = document.getElementById('calc-visits');
  const avg = document.getElementById('calc-spend');
  const out = document.getElementById('calc-out');
  const tier = document.getElementById('calc-tier');
  const fill = document.getElementById('calc-fill');
  if (!visits || !avg) return;

  function recalc() {
    const v = parseFloat(visits.value || 0);
    const a = parseFloat(avg.value || 0);
    const pts = Math.round(v * a * 2); // 2 pts per dollar
    if (out) out.textContent = pts.toLocaleString();
    let t = 'Pawn';
    let pct = Math.min(100, (pts / 250) * 100);
    if (pts >= 1500) { t = 'Queen'; pct = 100; }
    else if (pts >= 500) { t = 'Knight'; pct = Math.min(100, ((pts - 500) / 1000) * 100); }
    if (tier) tier.textContent = t;
    if (fill) fill.style.width = pct + '%';
  }
  visits.addEventListener('input', recalc);
  avg.addEventListener('input', recalc);
  recalc();
})();

// ===== Menu allergen filter =====
(function () {
  const filters = document.querySelectorAll('[data-allergen]');
  const items = document.querySelectorAll('.menu-item');
  if (!filters.length || !items.length) return;

  const active = new Set();
  filters.forEach(f => {
    f.addEventListener('click', () => {
      const key = f.dataset.allergen;
      if (active.has(key)) { active.delete(key); f.classList.remove('chip--purple'); }
      else { active.add(key); f.classList.add('chip--purple'); }
      apply();
    });
  });

  function apply() {
    items.forEach(it => {
      if (active.size === 0) { it.style.display = ''; return; }
      const tags = (it.dataset.diet || '').split(',');
      const ok = [...active].every(a => tags.includes(a));
      it.style.display = ok ? '' : 'none';
    });
  }
})();

// ===== Reviews filter =====
(function () {
  const filters = document.querySelectorAll('[data-rubric]');
  const cards = document.querySelectorAll('[data-review]');
  if (!filters.length || !cards.length) return;

  let active = 'all';
  filters.forEach(f => {
    f.addEventListener('click', () => {
      filters.forEach(x => x.classList.remove('chip--purple'));
      f.classList.add('chip--purple');
      active = f.dataset.rubric;
      cards.forEach(c => {
        const cats = (c.dataset.review || '').split(',');
        c.style.display = (active === 'all' || cats.includes(active)) ? '' : 'none';
      });
    });
  });
})();

// ===== Bracket inline expand =====
(function () {
  document.querySelectorAll('[data-bracket-toggle]').forEach(btn => {
    btn.addEventListener('click', () => {
      const t = document.querySelector(btn.dataset.bracketToggle);
      if (!t) return;
      const open = t.hasAttribute('hidden') ? false : true;
      if (open) { t.setAttribute('hidden', ''); btn.textContent = 'View bracket'; }
      else { t.removeAttribute('hidden'); btn.textContent = 'Hide bracket'; }
    });
  });
})();
