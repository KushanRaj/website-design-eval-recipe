// National Curling Federation — light interactivity
(function () {
  'use strict';

  // Tabs
  document.querySelectorAll('[data-tabs]').forEach(group => {
    const tabs = group.querySelectorAll('.tab');
    const panels = group.querySelectorAll('.tab-panel');
    tabs.forEach((t, i) => {
      t.addEventListener('click', () => {
        tabs.forEach(x => x.classList.remove('active'));
        panels.forEach(x => x.classList.remove('active'));
        t.classList.add('active');
        const k = t.dataset.tab;
        const p = group.querySelector('.tab-panel[data-tab="' + k + '"]');
        if (p) p.classList.add('active');
      });
    });
  });

  // Filter chips (toggle behavior)
  document.querySelectorAll('.chip').forEach(chip => {
    chip.addEventListener('click', () => {
      // chips inside a [data-chip-exclusive] group act as radio
      const grp = chip.closest('[data-chip-exclusive]');
      if (grp) {
        grp.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
      } else {
        chip.classList.toggle('active');
      }
    });
  });

  // Sort tables (numeric vs text)
  document.querySelectorAll('table.data.sortable').forEach(tbl => {
    const ths = tbl.querySelectorAll('thead th');
    ths.forEach((th, idx) => {
      th.addEventListener('click', () => {
        const body = tbl.querySelector('tbody');
        const rows = Array.from(body.querySelectorAll('tr:not(.expand-detail)'));
        const asc = !(th.dataset.sortDir === 'asc');
        th.dataset.sortDir = asc ? 'asc' : 'desc';
        ths.forEach(x => { if (x !== th) delete x.dataset.sortDir; });
        rows.sort((a, b) => {
          const av = (a.children[idx]?.innerText || '').trim();
          const bv = (b.children[idx]?.innerText || '').trim();
          const an = parseFloat(av.replace(/[^\d.\-]/g, ''));
          const bn = parseFloat(bv.replace(/[^\d.\-]/g, ''));
          const numeric = !isNaN(an) && !isNaN(bn) && /\d/.test(av) && /\d/.test(bv);
          if (numeric) return asc ? an - bn : bn - an;
          return asc ? av.localeCompare(bv) : bv.localeCompare(av);
        });
        rows.forEach(r => body.appendChild(r));
      });
    });
  });

  // Expandable rows (results archive)
  document.querySelectorAll('.expand-row').forEach(row => {
    row.addEventListener('click', () => {
      row.classList.toggle('open');
      const id = row.dataset.detail;
      const detail = document.querySelector('.expand-detail[data-detail="' + id + '"]');
      if (detail) detail.classList.toggle('open');
    });
  });

  // Bracket round-robin / playoff toggle
  document.querySelectorAll('[data-bracket-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-bracket-mode]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const mode = btn.dataset.bracketMode;
      const rr = document.getElementById('round-robin-view');
      const po = document.getElementById('playoff-view');
      if (rr && po) {
        if (mode === 'rr') { rr.style.display = ''; po.style.display = 'none'; }
        else { rr.style.display = 'none'; po.style.display = ''; }
      }
    });
  });

  // Club marker → flyout
  document.querySelectorAll('[data-club-marker]').forEach(m => {
    m.addEventListener('click', () => {
      const id = m.dataset.clubMarker;
      document.querySelectorAll('.flyout').forEach(f => f.style.display = 'none');
      const f = document.querySelector('.flyout[data-club-flyout="' + id + '"]');
      if (f) f.style.display = 'block';
      document.querySelectorAll('.club-row').forEach(r => r.classList.remove('selected'));
      const r = document.querySelector('.club-row[data-club-row="' + id + '"]');
      if (r) { r.classList.add('selected'); r.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
    });
  });
  document.querySelectorAll('.flyout .close').forEach(c => {
    c.addEventListener('click', e => {
      e.stopPropagation();
      c.closest('.flyout').style.display = 'none';
    });
  });
  document.querySelectorAll('.club-row').forEach(r => {
    r.addEventListener('click', () => {
      const id = r.dataset.clubRow;
      document.querySelectorAll('.flyout').forEach(f => f.style.display = 'none');
      const f = document.querySelector('.flyout[data-club-flyout="' + id + '"]');
      if (f) f.style.display = 'block';
      document.querySelectorAll('.club-row').forEach(x => x.classList.remove('selected'));
      r.classList.add('selected');
    });
  });

  // Stub subscribe form
  document.querySelectorAll('form.subscribe').forEach(f => {
    f.addEventListener('submit', e => {
      e.preventDefault();
      const note = f.querySelector('.subscribe-note');
      if (note) note.textContent = 'Subscribed — confirmation sent.';
    });
  });
})();
