/* The Worshipful Guild — interactive states */

document.addEventListener('DOMContentLoaded', () => {
  // ===== mobile menu toggle =====
  const toggle = document.querySelector('.menu-toggle');
  const nav = document.querySelector('.ribbon nav');
  if (toggle && nav) {
    toggle.addEventListener('click', () => {
      nav.classList.toggle('open');
      toggle.textContent = nav.classList.contains('open') ? 'Close' : 'Menu';
    });
  }

  // ===== mark active link =====
  const path = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.ribbon nav a').forEach(a => {
    const href = a.getAttribute('href');
    if (href === path || (path === '' && href === 'index.html')) {
      a.classList.add('active');
    }
  });

  // ===== workshop directory filters =====
  const chipGroups = document.querySelectorAll('[data-filter-group]');
  if (chipGroups.length) {
    const active = { family: 'all', region: 'all', apprentices: 'all' };
    chipGroups.forEach(group => {
      const key = group.dataset.filterGroup;
      group.querySelectorAll('.chip').forEach(chip => {
        chip.addEventListener('click', () => {
          group.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
          chip.classList.add('active');
          active[key] = chip.dataset.value;
          applyFilters(active);
        });
      });
    });
  }

  function applyFilters(active) {
    document.querySelectorAll('.workshop-card').forEach(card => {
      const family = card.dataset.family || '';
      const region = card.dataset.region || '';
      const appr = card.dataset.apprentices || '';
      const matchFamily = active.family === 'all' || family.includes(active.family);
      const matchRegion = active.region === 'all' || region === active.region;
      const matchAppr = active.apprentices === 'all' || appr === active.apprentices;
      card.classList.toggle('dim', !(matchFamily && matchRegion && matchAppr));
    });
  }

  // ===== billet rotator =====
  const rotToggles = document.querySelectorAll('.billet-rotator .toggles button');
  rotToggles.forEach(btn => {
    btn.addEventListener('click', () => {
      const value = btn.dataset.face;
      const stage = btn.closest('.billet-rotator').querySelector('.billet-stage');
      stage.querySelectorAll('.billet-face').forEach(f => {
        f.classList.toggle('active', f.dataset.face === value);
      });
      btn.closest('.toggles').querySelectorAll('button').forEach(b => b.classList.toggle('active', b === btn));
    });
  });

  // ===== materials table sort =====
  const table = document.querySelector('.materials-table');
  if (table) {
    table.querySelectorAll('thead th').forEach((th, idx) => {
      th.addEventListener('click', () => {
        const tbody = table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));
        const asc = !th.classList.contains('sort-asc');
        table.querySelectorAll('thead th').forEach(o => o.classList.remove('sort-asc', 'sort-desc'));
        th.classList.add(asc ? 'sort-asc' : 'sort-desc');
        rows.sort((a, b) => {
          const av = a.children[idx].textContent.trim().toLowerCase();
          const bv = b.children[idx].textContent.trim().toLowerCase();
          return asc ? av.localeCompare(bv) : bv.localeCompare(av);
        });
        rows.forEach(r => tbody.appendChild(r));
      });
    });
  }

  // ===== phonograph play simulation =====
  document.querySelectorAll('.phonograph').forEach(p => {
    p.addEventListener('click', () => {
      p.classList.toggle('playing');
      const label = p.querySelector('.phono-label');
      if (label) {
        label.textContent = p.classList.contains('playing') ? 'Sounding…' : 'Hear the Instrument';
      }
    });
  });

  // ===== soft page-turn on internal navigation =====
  document.querySelectorAll('a[href$=".html"], a[href="index.html"]').forEach(link => {
    link.addEventListener('click', (e) => {
      const href = link.getAttribute('href');
      if (!href || href.startsWith('#') || link.target === '_blank') return;
      e.preventDefault();
      document.body.classList.add('turning');
      setTimeout(() => { window.location.href = href; }, 280);
    });
  });

  // ===== footnote keyboard support =====
  document.querySelectorAll('.footnote-ref').forEach(ref => {
    ref.setAttribute('tabindex', '0');
  });
});

/* fade-in style page turn */
const style = document.createElement('style');
style.textContent = `
  body { transition: opacity 0.28s ease, transform 0.28s ease; opacity: 1; }
  body.turning { opacity: 0; transform: translateY(6px); }
`;
document.head.appendChild(style);
