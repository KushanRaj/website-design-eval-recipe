// Meridian Deep-Sea Observatory — interaction layer
(function () {
  'use strict';

  // Mobile sidebar toggle
  const menuBtn = document.querySelector('.menu-btn');
  const sidebar = document.querySelector('.sidebar');
  if (menuBtn && sidebar) {
    menuBtn.addEventListener('click', function () {
      sidebar.classList.toggle('open');
    });
    document.addEventListener('click', function (e) {
      if (window.innerWidth > 800) return;
      if (!sidebar.contains(e.target) && !menuBtn.contains(e.target)) {
        sidebar.classList.remove('open');
      }
    });
  }

  // Collapsible sidebar discipline groups
  document.querySelectorAll('.sidebar h3.toggle').forEach(function (h) {
    h.addEventListener('click', function () {
      const ul = h.nextElementSibling;
      if (ul && ul.tagName === 'UL') {
        ul.style.display = ul.style.display === 'none' ? '' : 'none';
        h.classList.toggle('collapsed');
      }
    });
  });

  // Buoy live tick — micro-update values to suggest a live feed
  function tickBuoy() {
    document.querySelectorAll('.buoy-cell[data-base]').forEach(function (cell) {
      const base = parseFloat(cell.dataset.base);
      const jitter = parseFloat(cell.dataset.jitter || '0.1');
      const decimals = parseInt(cell.dataset.decimals || '1', 10);
      const v = base + (Math.random() - 0.5) * 2 * jitter;
      const valEl = cell.querySelector('.val .num');
      if (valEl) valEl.textContent = v.toFixed(decimals);
    });
    const ts = document.querySelector('.buoy-timestamp .time');
    if (ts) {
      const d = new Date();
      const hh = String(d.getUTCHours()).padStart(2, '0');
      const mm = String(d.getUTCMinutes()).padStart(2, '0');
      const ss = String(d.getUTCSeconds()).padStart(2, '0');
      ts.textContent = hh + ':' + mm + ':' + ss + ' UTC';
    }
  }
  tickBuoy();
  setInterval(tickBuoy, 4500);

  // Filter chips (people page)
  document.querySelectorAll('.chips').forEach(function (group) {
    const chips = group.querySelectorAll('.chip');
    chips.forEach(function (c) {
      c.addEventListener('click', function () {
        chips.forEach(function (x) { x.classList.remove('active'); });
        c.classList.add('active');
        const filter = c.dataset.filter || 'all';
        document.querySelectorAll('[data-people-group]').forEach(function (grid) {
          grid.querySelectorAll('.person-card').forEach(function (card) {
            const tags = (card.dataset.tags || '').split(' ');
            if (filter === 'all' || tags.indexOf(filter) !== -1) {
              card.style.display = '';
            } else {
              card.style.display = 'none';
            }
          });
        });
      });
    });
  });

  // Publication search filter (lightweight)
  const pubSearch = document.querySelector('#pub-search');
  if (pubSearch) {
    pubSearch.addEventListener('input', function () {
      const q = pubSearch.value.toLowerCase().trim();
      document.querySelectorAll('.pub').forEach(function (p) {
        const text = p.textContent.toLowerCase();
        p.style.display = !q || text.indexOf(q) !== -1 ? '' : 'none';
      });
    });
  }

  // Open-data toggle
  const openToggle = document.querySelector('#open-data-only');
  if (openToggle) {
    openToggle.addEventListener('change', function () {
      document.querySelectorAll('.pub').forEach(function (p) {
        if (openToggle.checked) {
          p.style.display = p.dataset.openData === 'true' ? '' : 'none';
        } else {
          p.style.display = '';
        }
      });
    });
  }

  // Expedition row -> drawer scroll
  document.querySelectorAll('.exp-table tr[data-exp]').forEach(function (row) {
    row.addEventListener('click', function () {
      const drawer = document.querySelector('.drawer');
      if (drawer) drawer.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  // Spectrogram play button
  document.querySelectorAll('.spectro-player .play').forEach(function (btn) {
    btn.addEventListener('click', function () {
      btn.textContent = btn.textContent.trim() === '▶' ? '❚❚' : '▶';
    });
  });

  // Year in footer
  const yearEl = document.querySelector('[data-year]');
  if (yearEl) yearEl.textContent = new Date().getFullYear();
})();
