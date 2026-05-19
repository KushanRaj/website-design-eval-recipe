// Maple Hollow Community Schools - tiny vanilla JS helpers

document.addEventListener('DOMContentLoaded', () => {
  // Set today's date snippet wherever .today-date exists
  document.querySelectorAll('.today-date').forEach(el => {
    const d = new Date();
    const opts = { weekday: 'long', month: 'long', day: 'numeric' };
    el.textContent = d.toLocaleDateString('en-US', opts);
  });

  // Schools directory grid/map toggle
  const toggleGroups = document.querySelectorAll('[data-toggle-group]');
  toggleGroups.forEach(group => {
    const buttons = group.querySelectorAll('button[data-view]');
    buttons.forEach(btn => {
      btn.addEventListener('click', () => {
        const view = btn.dataset.view;
        buttons.forEach(b => b.classList.toggle('active', b === btn));
        const targetSelector = group.dataset.toggleGroup;
        document.querySelectorAll('[' + targetSelector + ']').forEach(panel => {
          const matches = panel.getAttribute(targetSelector) === view;
          panel.style.display = matches ? '' : 'none';
        });
      });
    });
  });

  // Role tabs on portal
  const roleTabs = document.querySelectorAll('.role-tabs button');
  roleTabs.forEach(btn => {
    btn.addEventListener('click', () => {
      roleTabs.forEach(b => b.classList.toggle('active', b === btn));
      const role = btn.dataset.role;
      const help = document.querySelector('#signin-role-help');
      if (help) {
        help.textContent = ({
          parent: 'Parents — use the activation code on the letter mailed home.',
          student: 'Students — sign in with your district Clever or Google account.',
          staff: 'Staff — use your @maplehollow.k12 credentials.'
        })[role] || '';
      }
    });
  });

  // Calendar view switcher (visual only — toggles which view is shown)
  document.querySelectorAll('.cal-view-switch button').forEach(btn => {
    btn.addEventListener('click', () => {
      const parent = btn.parentElement;
      parent.querySelectorAll('button').forEach(b => b.classList.toggle('active', b === btn));
      const view = btn.dataset.view;
      document.querySelectorAll('[data-cal-view]').forEach(panel => {
        panel.style.display = panel.dataset.calView === view ? '' : 'none';
      });
    });
  });

  // Academics grade-band tab strip
  document.querySelectorAll('.tab-strip').forEach(strip => {
    const buttons = strip.querySelectorAll('button');
    buttons.forEach(btn => {
      btn.addEventListener('click', () => {
        buttons.forEach(b => b.classList.toggle('active', b === btn));
        const band = btn.dataset.band;
        const label = document.querySelector('#band-label');
        if (label) label.textContent = btn.textContent.trim();
      });
    });
  });

  // News category filter pills
  const newsPills = document.querySelectorAll('.news-filter .pill');
  newsPills.forEach(pill => {
    pill.addEventListener('click', () => {
      newsPills.forEach(p => p.style.opacity = '0.55');
      pill.style.opacity = '1';
      const cat = pill.dataset.cat;
      document.querySelectorAll('[data-news-cat]').forEach(item => {
        if (!cat || cat === 'all' || item.dataset.newsCat === cat) {
          item.style.display = '';
        } else {
          item.style.display = 'none';
        }
      });
    });
  });

  // Modal: public comment signup
  document.querySelectorAll('[data-open-modal]').forEach(opener => {
    opener.addEventListener('click', (e) => {
      e.preventDefault();
      const id = opener.dataset.openModal;
      const m = document.getElementById(id);
      if (m) m.classList.add('open');
    });
  });
  document.querySelectorAll('.modal-backdrop').forEach(bd => {
    bd.addEventListener('click', (e) => {
      if (e.target === bd || e.target.classList.contains('close')) {
        bd.classList.remove('open');
      }
    });
  });

  // Locale switcher (decorative — sets a banner)
  const sel = document.querySelector('.locale-select');
  if (sel) {
    sel.addEventListener('change', () => {
      const code = sel.value;
      const msg = ({
        en: 'Language set to English.',
        es: 'Idioma cambiado a Español.',
        vi: 'Đã đổi ngôn ngữ sang Tiếng Việt.',
        so: 'Luqadda waxaa loo beddelay Soomaali.'
      })[code] || '';
      let toast = document.querySelector('#locale-toast');
      if (!toast) {
        toast = document.createElement('div');
        toast.id = 'locale-toast';
        toast.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#2d2a3b;color:#fff3a8;padding:10px 18px;border-radius:12px;font-weight:700;z-index:60;box-shadow:0 6px 20px rgba(0,0,0,0.25)';
        document.body.appendChild(toast);
      }
      toast.textContent = msg;
      clearTimeout(window.__localeT);
      window.__localeT = setTimeout(() => toast.remove(), 2400);
    });
  }

  // Lunch week navigator
  document.querySelectorAll('.week-nav button').forEach(b => {
    b.addEventListener('click', () => {
      const lbl = document.querySelector('#week-label');
      if (!lbl) return;
      const weeks = ['May 11 – May 15', 'May 18 – May 22', 'May 25 – May 29', 'June 1 – June 5'];
      const idx = parseInt(lbl.dataset.idx || '1', 10);
      const next = b.dataset.dir === 'next' ? Math.min(idx + 1, weeks.length - 1) : Math.max(idx - 1, 0);
      lbl.dataset.idx = next;
      lbl.textContent = weeks[next];
    });
  });

  // Lunch school-level tabs
  document.querySelectorAll('.lunch-tabs button').forEach(btn => {
    btn.addEventListener('click', () => {
      const tabs = btn.parentElement.querySelectorAll('button');
      tabs.forEach(b => b.classList.toggle('active', b === btn));
    });
  });

  // Rotate alert messages
  const alertList = document.querySelector('.alert-list');
  if (alertList) {
    const messages = JSON.parse(alertList.dataset.alerts || '[]');
    if (messages.length > 1) {
      let i = 0;
      setInterval(() => {
        i = (i + 1) % messages.length;
        alertList.innerHTML = messages[i];
      }, 5000);
    }
  }
});
