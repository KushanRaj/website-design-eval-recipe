/* ============================================================
   GEMOLOGY REFERENCE DATABASE — Main JavaScript
   ============================================================ */

(function () {
  'use strict';

  /* ---------- Utility ---------- */
  const qs  = (sel, ctx = document) => ctx.querySelector(sel);
  const qsa = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));

  /* ---------- NAV TOGGLE (mobile) ---------- */
  function initNavToggle() {
    const toggle = qs('.nav-toggle');
    const navLinks = qs('.nav-links');
    if (!toggle || !navLinks) return;
    toggle.addEventListener('click', () => {
      const open = navLinks.classList.toggle('mobile-open');
      toggle.setAttribute('aria-expanded', open);
    });
    // Close on outside click
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.site-nav')) {
        navLinks.classList.remove('mobile-open');
      }
    });
  }

  /* ---------- ACTIVE NAV LINK ---------- */
  function initActiveNav() {
    const path = window.location.pathname.replace(/\/$/, '') || '/index.html';
    qsa('.nav-links a').forEach(link => {
      const href = link.getAttribute('href').replace(/\/$/, '');
      if (path.endsWith(href) || (path === '' && href === 'index.html')) {
        link.classList.add('active');
      }
    });
  }

  /* ---------- FILTER GROUPS (collapsible) ---------- */
  function initFilterGroups() {
    qsa('.filter-group-header').forEach(header => {
      header.addEventListener('click', () => {
        const group = header.closest('.filter-group');
        group.classList.toggle('collapsed');
      });
    });
  }

  /* ---------- GEM CARD FILTER (minerals page) ---------- */
  function initGemFilter() {
    const checkboxes = qsa('.filter-option input[type="checkbox"]');
    const cards = qsa('.gem-classification-card');
    const resultCount = qs('.result-count strong');
    const activeFiltersRow = qs('.active-filters');

    if (!checkboxes.length || !cards.length) return;

    function applyFilters() {
      const active = {};
      checkboxes.forEach(cb => {
        if (cb.checked) {
          const group = cb.closest('.filter-group').dataset.group;
          if (!active[group]) active[group] = [];
          active[group].push(cb.value);
        }
      });

      let visible = 0;
      cards.forEach(card => {
        let show = true;
        for (const [group, values] of Object.entries(active)) {
          const cardVal = card.dataset[group];
          if (cardVal && !values.includes(cardVal)) {
            show = false;
            break;
          }
        }
        card.style.display = show ? '' : 'none';
        if (show) visible++;
      });

      if (resultCount) resultCount.textContent = visible;
      renderActiveChips(active);
    }

    function renderActiveChips(active) {
      if (!activeFiltersRow) return;
      activeFiltersRow.innerHTML = '';
      for (const [group, values] of Object.entries(active)) {
        values.forEach(val => {
          const chip = document.createElement('span');
          chip.className = 'active-filter-chip';
          chip.innerHTML = `${val} <span class="remove">×</span>`;
          chip.addEventListener('click', () => {
            const cb = qs(`.filter-option input[value="${val}"]`);
            if (cb) { cb.checked = false; applyFilters(); }
          });
          activeFiltersRow.appendChild(chip);
        });
      }
    }

    checkboxes.forEach(cb => cb.addEventListener('change', applyFilters));

    // Mobile filter toggle
    const mobileFilterBtn = qs('.mobile-filter-btn');
    const filterSidebar = qs('.filter-sidebar');
    if (mobileFilterBtn && filterSidebar) {
      mobileFilterBtn.addEventListener('click', () => {
        filterSidebar.classList.toggle('mobile-open');
      });
    }
  }

  /* ---------- GEM TABS (grading page) ---------- */
  function initGemTabs() {
    const tabs = qsa('.gem-tab');
    const panels = qsa('.tab-panel');
    if (!tabs.length) return;

    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        tabs.forEach(t => t.classList.remove('active'));
        panels.forEach(p => p.classList.remove('active'));
        tab.classList.add('active');
        const target = qs(`#panel-${tab.dataset.tab}`);
        if (target) target.classList.add('active');
      });
    });
  }

  /* ---------- CUTS GALLERY — filter + drawer ---------- */
  function initCutsGallery() {
    const filterBtns = qsa('.cut-filter-btn');
    const cards = qsa('.cut-card');
    const drawer = qs('.cut-drawer');
    const drawerClose = qs('.drawer-close');

    if (!cards.length) return;

    // Filter
    filterBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        filterBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const filter = btn.dataset.filter;
        cards.forEach(card => {
          if (filter === 'all' || card.dataset.category === filter) {
            card.style.display = '';
          } else {
            card.style.display = 'none';
          }
        });
      });
    });

    // Drawer
    if (!drawer) return;
    cards.forEach(card => {
      card.addEventListener('click', () => {
        const name = card.dataset.cutName || qs('.cut-card-name', card)?.textContent;
        const facets = card.dataset.facets || '–';
        const category = card.dataset.category || '–';
        const bestFor = card.dataset.bestFor || '–';
        const notes = card.dataset.notes || 'A classic faceting style prized for brilliance and light return.';

        const drawerTitle = qs('.drawer-cut-name', drawer);
        const drawerFacets = qs('.drawer-facets', drawer);
        const drawerCategory = qs('.drawer-category', drawer);
        const drawerBestFor = qs('.drawer-best-for', drawer);
        const drawerNotes = qs('.drawer-notes', drawer);

        if (drawerTitle) drawerTitle.textContent = name;
        if (drawerFacets) drawerFacets.textContent = facets;
        if (drawerCategory) drawerCategory.textContent = category;
        if (drawerBestFor) drawerBestFor.textContent = bestFor;
        if (drawerNotes) drawerNotes.textContent = notes;

        drawer.classList.add('open');
      });
    });

    if (drawerClose) {
      drawerClose.addEventListener('click', () => drawer.classList.remove('open'));
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && drawer) drawer.classList.remove('open');
    });
  }

  /* ---------- ORIGINS MAP — deposit markers ---------- */
  function initOriginsMap() {
    const markers = qsa('.map-deposit-dot');
    const depositPanel = qs('.deposit-panel');
    if (!markers.length || !depositPanel) return;

    markers.forEach(marker => {
      marker.addEventListener('click', () => {
        const data = marker.dataset;
        const emptyMsg = qs('.deposit-panel-empty', depositPanel);
        const infoPanels = qsa('.deposit-info', depositPanel);
        infoPanels.forEach(p => p.classList.remove('active'));
        if (emptyMsg) emptyMsg.style.display = 'none';

        const target = qs(`#deposit-${data.depositId}`, depositPanel);
        if (target) {
          target.classList.add('active');
        } else {
          // Build dynamic panel
          const div = document.createElement('div');
          div.className = 'deposit-info active';
          div.id = `deposit-${data.depositId}`;
          div.innerHTML = `
            <div class="deposit-country">${data.country || 'Unknown'}</div>
            <div class="deposit-region">${data.region || ''}</div>
            <hr class="gold-rule" style="margin:12px 0">
            <div class="deposit-detail-row">
              <span class="deposit-detail-label">Gem Types</span>
              <span class="deposit-detail-value">${data.gems || '–'}</span>
            </div>
            <div class="deposit-detail-row">
              <span class="deposit-detail-label">Deposit Type</span>
              <span class="deposit-detail-value">${data.depositType || '–'}</span>
            </div>
            <div class="deposit-detail-row">
              <span class="deposit-detail-label">Geological Period</span>
              <span class="deposit-detail-value">${data.period || '–'}</span>
            </div>
            <div class="deposit-detail-row">
              <span class="deposit-detail-label">Notable Mine</span>
              <span class="deposit-detail-value">${data.mine || '–'}</span>
            </div>
          `;
          depositPanel.appendChild(div);
        }

        // Pulse animation on selected marker
        markers.forEach(m => m.setAttribute('r', m.dataset.baseR || '6'));
        marker.setAttribute('r', '9');
      });
    });
  }

  /* ---------- GEOLOGICAL PERIOD CHIPS ---------- */
  function initPeriodChips() {
    const chips = qsa('.period-chip');
    chips.forEach(chip => {
      chip.addEventListener('click', () => {
        chips.forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
      });
    });
  }

  /* ---------- GLOSSARY SEARCH + ALPHA NAV ---------- */
  function initGlossary() {
    const searchInput = qs('.glossary-search');
    const entries = qsa('.glossary-entry');
    const sections = qsa('.glossary-section');
    const alphaLinks = qsa('.alpha-link');

    if (searchInput) {
      searchInput.addEventListener('input', () => {
        const q = searchInput.value.toLowerCase().trim();
        entries.forEach(entry => {
          const term = entry.querySelector('.entry-term')?.textContent.toLowerCase() || '';
          const def  = entry.querySelector('.entry-definition')?.textContent.toLowerCase() || '';
          entry.style.display = (!q || term.includes(q) || def.includes(q)) ? '' : 'none';
        });
        sections.forEach(section => {
          const visibleEntries = qsa('.glossary-entry', section).filter(e => e.style.display !== 'none');
          section.style.display = visibleEntries.length ? '' : 'none';
        });
      });
    }

    // Smooth-scroll alpha links
    alphaLinks.forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        const letter = link.dataset.letter;
        const target = qs(`#glossary-${letter}`);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }

  /* ---------- INIT ALL ---------- */
  document.addEventListener('DOMContentLoaded', () => {
    initNavToggle();
    initActiveNav();
    initFilterGroups();
    initGemFilter();
    initGemTabs();
    initCutsGallery();
    initOriginsMap();
    initPeriodChips();
    initGlossary();
  });

})();
