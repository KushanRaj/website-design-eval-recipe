/* =========================================================
   OceanIndex — Main JavaScript
   ========================================================= */

'use strict';

/* --- Mobile navigation hamburger ----------------------- */
(function () {
  const hamburger = document.querySelector('.hamburger');
  const nav = document.querySelector('.main-nav');
  if (!hamburger || !nav) return;
  hamburger.addEventListener('click', () => {
    nav.classList.toggle('mobile-open');
    hamburger.classList.toggle('is-open');
  });
})();

/* --- Taxonomy Quick-search (home page) ----------------- */
(function () {
  const input = document.getElementById('qs-input');
  const resultsEl = document.getElementById('qs-results');
  if (!input || !resultsEl) return;

  const SPECIES = [
    { binomial: 'Carcharodon carcharias', common: 'Great White Shark', class: 'Chondrichthyes', status: 'VU' },
    { binomial: 'Megaptera novaeangliae', common: 'Humpback Whale', class: 'Mammalia', status: 'LC' },
    { binomial: 'Thunnus thynnus', common: 'Atlantic Bluefin Tuna', class: 'Actinopterygii', status: 'EN' },
    { binomial: 'Dermochelys coriacea', common: 'Leatherback Sea Turtle', class: 'Reptilia', status: 'VU' },
    { binomial: 'Architeuthis dux', common: 'Giant Squid', class: 'Cephalopoda', status: 'DD' },
    { binomial: 'Orcinus orca', common: 'Orca / Killer Whale', class: 'Mammalia', status: 'DD' },
    { binomial: 'Rhincodon typus', common: 'Whale Shark', class: 'Chondrichthyes', status: 'EN' },
    { binomial: 'Mola mola', common: 'Ocean Sunfish', class: 'Actinopterygii', status: 'VU' },
    { binomial: 'Tursiops truncatus', common: 'Bottlenose Dolphin', class: 'Mammalia', status: 'LC' },
    { binomial: 'Hippocampus hippocampus', common: 'Short-snouted Seahorse', class: 'Actinopterygii', status: 'LC' },
    { binomial: 'Balaenoptera musculus', common: 'Blue Whale', class: 'Mammalia', status: 'EN' },
    { binomial: 'Mobula birostris', common: 'Giant Oceanic Manta Ray', class: 'Chondrichthyes', status: 'VU' },
  ];

  function renderResults(matches) {
    if (!matches.length) {
      resultsEl.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px 0;">No matches found.</div>';
      return;
    }
    resultsEl.innerHTML = matches.slice(0, 6).map(s => `
      <div class="qs-result-item">
        <div>
          <div class="qs-binomial">${s.binomial}</div>
          <div class="qs-common">${s.common}</div>
        </div>
        <span class="iucn-pill iucn-${s.status.toLowerCase()}">${s.status}</span>
      </div>
    `).join('');
  }

  renderResults(SPECIES.slice(0, 4));

  input.addEventListener('input', function () {
    const q = this.value.trim().toLowerCase();
    if (!q) { renderResults(SPECIES.slice(0, 4)); return; }
    const matches = SPECIES.filter(s =>
      s.binomial.toLowerCase().includes(q) ||
      s.common.toLowerCase().includes(q) ||
      s.class.toLowerCase().includes(q)
    );
    renderResults(matches);
  });
})();

/* --- Taxonomy Tree expand/collapse --------------------- */
(function () {
  const tree = document.querySelector('.tax-tree');
  if (!tree) return;

  tree.addEventListener('click', function (e) {
    const toggle = e.target.closest('.tax-node-toggle');
    if (toggle) {
      toggle.classList.toggle('open');
      const children = toggle.closest('.tax-node-row').nextElementSibling;
      if (children && children.classList.contains('tax-children')) {
        children.classList.toggle('open');
      }
      return;
    }
    const row = e.target.closest('.tax-node-row');
    if (row) {
      tree.querySelectorAll('.tax-node-row.active').forEach(r => r.classList.remove('active'));
      row.classList.add('active');
    }
  });
})();

/* --- Specimen Detail Panel animation (taxonomy page) --- */
(function () {
  const panel = document.querySelector('.specimen-detail-panel');
  const rows  = document.querySelectorAll('.species-list-row');
  const closeBtn = document.querySelector('.sdp-close');
  if (!panel || !rows.length) return;

  // Species data for the detail panel
  const SPECIMEN_DATA = {
    'carcharodon-carcharias': {
      binomial: 'Carcharodon carcharias',
      common: 'Great White Shark',
      authority: '(Linnaeus, 1758)',
      status: 'VU',
      classification: [
        { rank: 'Kingdom', name: 'Animalia' },
        { rank: 'Phylum', name: 'Chordata' },
        { rank: 'Class', name: 'Chondrichthyes' },
        { rank: 'Order', name: 'Lamniformes' },
        { rank: 'Family', name: 'Lamnidae' },
        { rank: 'Genus', name: 'Carcharodon' },
        { rank: 'Species', name: 'C. carcharias', bold: true },
      ],
      morphology: [
        { label: 'Max Length', value: '6.1 m' },
        { label: 'Max Weight', value: '2,268 kg' },
        { label: 'Depth Range', value: '0–1,200 m' },
        { label: 'Lifespan', value: '~70 years' },
      ],
      depthMin: 0, depthMax: 1200,
      synonyms: ['Squalus carcharias Linnaeus, 1758', 'Carcharias atwoodi Storer, 1848'],
      habitat: ['Pelagic', 'Coastal', 'Epipelagic', 'Mesopelagic'],
      assessYear: 2018,
    },
    'megaptera-novaeangliae': {
      binomial: 'Megaptera novaeangliae',
      common: 'Humpback Whale',
      authority: '(Borowski, 1781)',
      status: 'LC',
      classification: [
        { rank: 'Kingdom', name: 'Animalia' },
        { rank: 'Phylum', name: 'Chordata' },
        { rank: 'Class', name: 'Mammalia' },
        { rank: 'Order', name: 'Artiodactyla' },
        { rank: 'Family', name: 'Balaenopteridae' },
        { rank: 'Genus', name: 'Megaptera' },
        { rank: 'Species', name: 'M. novaeangliae', bold: true },
      ],
      morphology: [
        { label: 'Max Length', value: '16 m' },
        { label: 'Max Weight', value: '36,000 kg' },
        { label: 'Depth Range', value: '0–700 m' },
        { label: 'Lifespan', value: '45–100 years' },
      ],
      depthMin: 0, depthMax: 700,
      synonyms: ['Balaena novaeangliae Borowski, 1781', 'Megaptera longimana (Rudolphi, 1832)'],
      habitat: ['Pelagic', 'Coastal', 'Epipelagic'],
      assessYear: 2018,
    },
    'thunnus-thynnus': {
      binomial: 'Thunnus thynnus',
      common: 'Atlantic Bluefin Tuna',
      authority: '(Linnaeus, 1758)',
      status: 'EN',
      classification: [
        { rank: 'Kingdom', name: 'Animalia' },
        { rank: 'Phylum', name: 'Chordata' },
        { rank: 'Class', name: 'Actinopterygii' },
        { rank: 'Order', name: 'Scombriformes' },
        { rank: 'Family', name: 'Scombridae' },
        { rank: 'Genus', name: 'Thunnus' },
        { rank: 'Species', name: 'T. thynnus', bold: true },
      ],
      morphology: [
        { label: 'Max Length', value: '3.0 m' },
        { label: 'Max Weight', value: '725 kg' },
        { label: 'Depth Range', value: '0–1,000 m' },
        { label: 'Lifespan', value: '35 years' },
      ],
      depthMin: 0, depthMax: 1000,
      synonyms: ['Scomber thynnus Linnaeus, 1758', 'Albacora thynnus (Linnaeus, 1758)'],
      habitat: ['Pelagic', 'Epipelagic', 'Mesopelagic'],
      assessYear: 2021,
    },
    'rhincodon-typus': {
      binomial: 'Rhincodon typus',
      common: 'Whale Shark',
      authority: 'Smith, 1828',
      status: 'EN',
      classification: [
        { rank: 'Kingdom', name: 'Animalia' },
        { rank: 'Phylum', name: 'Chordata' },
        { rank: 'Class', name: 'Chondrichthyes' },
        { rank: 'Order', name: 'Orectolobiformes' },
        { rank: 'Family', name: 'Rhincodontidae' },
        { rank: 'Genus', name: 'Rhincodon' },
        { rank: 'Species', name: 'R. typus', bold: true },
      ],
      morphology: [
        { label: 'Max Length', value: '18.8 m' },
        { label: 'Max Weight', value: '18,700 kg' },
        { label: 'Depth Range', value: '0–1,928 m' },
        { label: 'Lifespan', value: '80–130 years' },
      ],
      depthMin: 0, depthMax: 1928,
      synonyms: ['Rhiniodon typus Smith, 1828'],
      habitat: ['Pelagic', 'Coastal', 'Epipelagic', 'Mesopelagic'],
      assessYear: 2016,
    },
    'balaenoptera-musculus': {
      binomial: 'Balaenoptera musculus',
      common: 'Blue Whale',
      authority: '(Linnaeus, 1758)',
      status: 'EN',
      classification: [
        { rank: 'Kingdom', name: 'Animalia' },
        { rank: 'Phylum', name: 'Chordata' },
        { rank: 'Class', name: 'Mammalia' },
        { rank: 'Order', name: 'Artiodactyla' },
        { rank: 'Family', name: 'Balaenopteridae' },
        { rank: 'Genus', name: 'Balaenoptera' },
        { rank: 'Species', name: 'B. musculus', bold: true },
      ],
      morphology: [
        { label: 'Max Length', value: '33.6 m' },
        { label: 'Max Weight', value: '199,000 kg' },
        { label: 'Depth Range', value: '0–500 m' },
        { label: 'Lifespan', value: '80–110 years' },
      ],
      depthMin: 0, depthMax: 500,
      synonyms: ['Balaena musculus Linnaeus, 1758', 'Sibbaldus musculus (Linnaeus, 1758)'],
      habitat: ['Pelagic', 'Epipelagic'],
      assessYear: 2018,
    },
    'mola-mola': {
      binomial: 'Mola mola',
      common: 'Ocean Sunfish',
      authority: '(Linnaeus, 1758)',
      status: 'VU',
      classification: [
        { rank: 'Kingdom', name: 'Animalia' },
        { rank: 'Phylum', name: 'Chordata' },
        { rank: 'Class', name: 'Actinopterygii' },
        { rank: 'Order', name: 'Tetraodontiformes' },
        { rank: 'Family', name: 'Molidae' },
        { rank: 'Genus', name: 'Mola' },
        { rank: 'Species', name: 'M. mola', bold: true },
      ],
      morphology: [
        { label: 'Max Length', value: '3.3 m' },
        { label: 'Max Weight', value: '2,300 kg' },
        { label: 'Depth Range', value: '0–844 m' },
        { label: 'Lifespan', value: '10–23 years' },
      ],
      depthMin: 0, depthMax: 844,
      synonyms: ['Tetraodon mola Linnaeus, 1758', 'Orthagoriscus mola (Linnaeus, 1758)'],
      habitat: ['Pelagic', 'Epipelagic', 'Mesopelagic'],
      assessYear: 2019,
    },
  };

  function buildPanel(data) {
    const iucnClass = 'iucn-' + data.status.toLowerCase();
    const classTrail = data.classification.map(c =>
      `<span class="sdp-crumb${c.bold ? ' crumb-bold' : ''}">${c.rank}: <em>${c.name}</em></span>`
    ).join('');

    const morphRows = data.morphology.map(m =>
      `<div class="sdp-row"><span class="sdp-row-label">${m.label}</span><span class="sdp-row-value">${m.value}</span></div>`
    ).join('');

    const synonymItems = data.synonyms.map(s =>
      `<div class="synonym-item">${s}</div>`
    ).join('');

    const depthPct = Math.min(100, (data.depthMax / 2000) * 100);

    const habitatTags = data.habitat.map(h =>
      `<span class="habitat-tag">${h}</span>`
    ).join('');

    return `
      <div class="sdp-hd">
        <div>
          <div class="sdp-binomial">${data.binomial}</div>
          <div class="sdp-common">${data.common}</div>
        </div>
        <button class="sdp-close" aria-label="Close panel">✕</button>
      </div>
      <div class="sdp-body">
        <div class="sdp-section">
          <div class="sdp-section-title">Conservation Status</div>
          <div style="display:flex;align-items:center;gap:8px;">
            <span class="iucn-pill ${iucnClass}">${data.status}</span>
            <span style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);">IUCN Red List (${data.assessYear})</span>
          </div>
        </div>
        <div class="sdp-section">
          <div class="sdp-section-title">Morphology</div>
          ${morphRows}
        </div>
        <div class="sdp-section">
          <div class="sdp-section-title">Depth Range</div>
          <div style="display:flex;justify-content:space-between;font-family:var(--font-mono);font-size:10px;color:var(--text-muted);margin-bottom:4px;">
            <span>0 m</span><span>${data.depthMax} m</span>
          </div>
          <div class="depth-range-bar">
            <div class="depth-range-fill" style="left:0;width:${depthPct}%"></div>
          </div>
        </div>
        <div class="sdp-section">
          <div class="sdp-section-title">Habitat Zones</div>
          <div style="display:flex;flex-wrap:wrap;gap:4px;">${habitatTags}</div>
        </div>
        <div class="sdp-section">
          <div class="sdp-section-title">Classification</div>
          <div class="sdp-breadcrumb">${classTrail}</div>
        </div>
        <div class="sdp-section">
          <div class="sdp-section-title">Synonyms</div>
          <div class="synonym-list">${synonymItems}</div>
        </div>
      </div>
    `;
  }

  function openPanel(speciesKey) {
    const data = SPECIMEN_DATA[speciesKey];
    if (!data) return;
    panel.innerHTML = buildPanel(data);
    panel.classList.add('panel-open');

    // Re-attach close listener
    const close = panel.querySelector('.sdp-close');
    if (close) {
      close.addEventListener('click', () => {
        panel.classList.remove('panel-open');
        rows.forEach(r => r.classList.remove('row-selected'));
      });
    }
  }

  rows.forEach(row => {
    row.addEventListener('click', function () {
      rows.forEach(r => r.classList.remove('row-selected'));
      this.classList.add('row-selected');
      const key = this.dataset.species;
      openPanel(key);
    });
  });

  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      panel.classList.remove('panel-open');
      rows.forEach(r => r.classList.remove('row-selected'));
    });
  }
})();

/* --- Publications table sort & abstract expand --------- */
(function () {
  const table = document.getElementById('pub-table');
  if (!table) return;

  // Sort columns
  const headers = table.querySelectorAll('th[data-sort]');
  let currentSort = { col: null, dir: 1 };

  headers.forEach(th => {
    th.addEventListener('click', function () {
      const col = this.dataset.sort;
      if (currentSort.col === col) {
        currentSort.dir *= -1;
      } else {
        currentSort.col = col;
        currentSort.dir = 1;
      }
      headers.forEach(h => h.classList.remove('asc', 'desc'));
      this.classList.add(currentSort.dir === 1 ? 'asc' : 'desc');
      sortTable(col, currentSort.dir);
    });
  });

  function sortTable(col, dir) {
    const tbody = table.querySelector('tbody');
    const rowPairs = [];
    const rows = tbody.querySelectorAll('tr.pub-row');
    rows.forEach(row => {
      const absRow = document.getElementById('abs-' + row.dataset.pubId);
      rowPairs.push({ row, absRow });
    });
    rowPairs.sort((a, b) => {
      let va = a.row.dataset[col] || '';
      let vb = b.row.dataset[col] || '';
      if (!isNaN(va) && !isNaN(vb)) {
        return (parseFloat(va) - parseFloat(vb)) * dir;
      }
      return va.localeCompare(vb) * dir;
    });
    rowPairs.forEach(({ row, absRow }) => {
      tbody.appendChild(row);
      if (absRow) tbody.appendChild(absRow);
    });
  }

  // Abstract expand
  table.addEventListener('click', function (e) {
    const btn = e.target.closest('.pub-expand-btn');
    if (!btn) return;
    const id = btn.dataset.pub;
    const absRow = document.getElementById('abs-' + id);
    if (!absRow) return;
    absRow.classList.toggle('open');
    btn.textContent = absRow.classList.contains('open') ? '▲ Abstract' : '▼ Abstract';
  });
})();

/* --- Publication filter sidebar ----------------------- */
(function () {
  const yearRange = document.getElementById('year-range');
  const yearVal   = document.getElementById('year-range-val');
  if (yearRange && yearVal) {
    yearRange.addEventListener('input', function () {
      yearVal.textContent = this.value + '–2024';
      filterPubs();
    });
  }

  const oaToggle = document.getElementById('oa-toggle');
  if (oaToggle) oaToggle.addEventListener('change', filterPubs);

  const phylumChecks = document.querySelectorAll('.phylum-check');
  phylumChecks.forEach(c => c.addEventListener('change', filterPubs));

  function filterPubs() {
    const minYear = yearRange ? parseInt(yearRange.value) : 2010;
    const oaOnly  = oaToggle ? oaToggle.checked : false;
    const activePhyla = new Set(
      Array.from(phylumChecks).filter(c => c.checked).map(c => c.value)
    );

    const rows = document.querySelectorAll('tr.pub-row');
    let visible = 0;
    rows.forEach(row => {
      const year   = parseInt(row.dataset.year || 0);
      const oa     = row.dataset.oa === 'true';
      const phylum = row.dataset.phylum || '';
      const show = year >= minYear &&
                   (!oaOnly || oa) &&
                   (activePhyla.size === 0 || activePhyla.has(phylum));
      row.style.display = show ? '' : 'none';
      const abs = document.getElementById('abs-' + row.dataset.pubId);
      if (abs) abs.style.display = show ? '' : 'none';
      if (show) visible++;
    });
    const rc = document.getElementById('pub-result-count');
    if (rc) rc.textContent = visible + ' results';
  }
})();

/* --- Conservation year-range selector ----------------- */
(function () {
  const slider = document.getElementById('cons-year-range');
  const display = document.getElementById('cons-year-display');
  if (!slider || !display) return;
  slider.addEventListener('input', function () {
    display.textContent = '2000–' + this.value;
  });
})();

/* --- Habitat map basin clicks -------------------------- */
(function () {
  const basins = document.querySelectorAll('.ocean-basin');
  const tally = document.getElementById('basin-tally');
  if (!basins.length) return;

  const BASIN_DATA = {
    'pacific':   { name: 'Pacific Ocean',   count: 1847, zones: ['Epipelagic', 'Mesopelagic', 'Bathypelagic'] },
    'atlantic':  { name: 'Atlantic Ocean',  count: 1203, zones: ['Epipelagic', 'Mesopelagic'] },
    'indian':    { name: 'Indian Ocean',    count:  892, zones: ['Epipelagic', 'Mesopelagic'] },
    'arctic':    { name: 'Arctic Ocean',    count:  341, zones: ['Epipelagic'] },
    'southern':  { name: 'Southern Ocean',  count:  527, zones: ['Epipelagic', 'Mesopelagic', 'Bathypelagic'] },
    'mediterranean': { name: 'Mediterranean Sea', count: 614, zones: ['Epipelagic'] },
  };

  basins.forEach(basin => {
    basin.addEventListener('click', function () {
      basins.forEach(b => b.classList.remove('active'));
      this.classList.add('active');
      const id = this.dataset.basin;
      const d = BASIN_DATA[id];
      if (d && tally) {
        tally.innerHTML = `
          <div style="padding:12px 16px;background:#fff;border:1px solid var(--border);border-radius:4px;">
            <div style="font-weight:700;color:var(--deep-sea);margin-bottom:8px;">${d.name}</div>
            <div style="font-family:var(--font-mono);font-size:12px;color:var(--text-muted);">
              <span style="font-size:18px;font-weight:700;color:var(--teal);margin-right:6px;">${d.count.toLocaleString()}</span>
              documented species
            </div>
            <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">
              ${d.zones.map(z => `<span class="habitat-tag">${z}</span>`).join('')}
            </div>
          </div>`;
      }
    });
  });
})();

/* --- Depth zone toggles (habitat page) ---------------- */
(function () {
  const toggles = document.querySelectorAll('.depth-toggle');
  toggles.forEach(t => {
    t.addEventListener('click', function () {
      this.classList.toggle('active');
    });
  });
})();

/* --- Field guide search & filter ---------------------- */
(function () {
  const searchInput = document.getElementById('fg-search');
  const classFilter = document.getElementById('fg-class');
  const statusFilter = document.getElementById('fg-status');
  if (!searchInput) return;

  function filterCards() {
    const q      = searchInput.value.toLowerCase();
    const cls    = classFilter ? classFilter.value : '';
    const status = statusFilter ? statusFilter.value : '';
    const cards  = document.querySelectorAll('.fg-card[data-common]');
    cards.forEach(card => {
      const common  = (card.dataset.common || '').toLowerCase();
      const binom   = (card.dataset.binomial || '').toLowerCase();
      const cardCls = card.dataset.class || '';
      const cardSt  = card.dataset.status || '';
      const matchQ  = !q || common.includes(q) || binom.includes(q);
      const matchC  = !cls || cardCls === cls;
      const matchS  = !status || cardSt === status;
      card.style.display = (matchQ && matchC && matchS) ? '' : 'none';
    });
  }

  searchInput.addEventListener('input', filterCards);
  if (classFilter)  classFilter.addEventListener('change', filterCards);
  if (statusFilter) statusFilter.addEventListener('change', filterCards);
})();

/* --- Featured Species Spotlight Rotation (home page) -- */
(function () {
  var spotlight = document.getElementById('featured-species-spotlight');
  if (!spotlight) return;
  var heroMeta = spotlight.querySelector('.hero-meta');
  if (!heroMeta) return;

  var FEATURED = [
    {
      common: 'Whale Shark',
      binomial: 'Rhincodon typus',
      authority: 'Smith, 1828',
      phylum: 'Chondrichthyes',
      status: 'EN',
      statusLabel: 'Endangered',
      statusClass: 'iucn-en',
      order: 'Orectolobiformes',
      habitat: ['Epipelagic', 'Coastal'],
      desc: 'The world\'s largest fish, reaching up to 18.8 m in length. A filter feeder found in warm tropical oceans worldwide. Listed as Endangered due to fishing pressure, vessel strikes, and habitat degradation.'
    },
    {
      common: 'Blue Whale',
      binomial: 'Balaenoptera musculus',
      authority: '(Linnaeus, 1758)',
      phylum: 'Mammalia',
      status: 'EN',
      statusLabel: 'Endangered',
      statusClass: 'iucn-en',
      order: 'Artiodactyla',
      habitat: ['Pelagic', 'Epipelagic'],
      desc: 'The largest animal ever known to have existed, reaching 33.6 m and 199 tonnes. Nearly hunted to extinction by commercial whaling; currently recovering but remains Endangered on the IUCN Red List.'
    },
    {
      common: 'Great White Shark',
      binomial: 'Carcharodon carcharias',
      authority: '(Linnaeus, 1758)',
      phylum: 'Chondrichthyes',
      status: 'VU',
      statusLabel: 'Vulnerable',
      statusClass: 'iucn-vu',
      order: 'Lamniformes',
      habitat: ['Pelagic', 'Coastal', 'Mesopelagic'],
      desc: 'Apex predator reaching 6.1 m in length. Found in cool coastal waters across all major oceans. Classified as Vulnerable due to accidental bycatch, targeted fishing, and finning pressure.'
    },
    {
      common: 'Orca (Killer Whale)',
      binomial: 'Orcinus orca',
      authority: '(Linnaeus, 1758)',
      phylum: 'Mammalia',
      status: 'DD',
      statusLabel: 'Data Deficient',
      statusClass: 'iucn-dd',
      order: 'Artiodactyla',
      habitat: ['Pelagic', 'Coastal', 'Epipelagic'],
      desc: 'Apex predator found in every ocean from Arctic to Antarctic. Highly social with ecotypes specialised for different prey. Currently Data Deficient on the IUCN Red List; resident subpopulations may be critically threatened.'
    },
    {
      common: 'Leatherback Sea Turtle',
      binomial: 'Dermochelys coriacea',
      authority: '(Vandelli, 1761)',
      phylum: 'Reptilia',
      status: 'VU',
      statusLabel: 'Vulnerable',
      statusClass: 'iucn-vu',
      order: 'Testudines',
      habitat: ['Pelagic', 'Epipelagic'],
      desc: 'The world\'s largest living turtle, reaching 2.1 m and 700 kg. The only sea turtle with a soft leathery carapace. Dives to 1,280 m in search of jellyfish; Pacific subpopulations remain critically endangered.'
    }
  ];

  var currentIdx = 0; // 0 = Rhincodon typus already shown in HTML

  function updateSpotlight(sp) {
    // Fade out
    heroMeta.style.opacity = '0';
    setTimeout(function () {
      var phylumBadge = heroMeta.querySelector('.hero-phylum-badge');
      var commonEl    = heroMeta.querySelector('.hero-common');
      var binomialEl  = heroMeta.querySelector('.hero-binomial');
      var authorityEl = heroMeta.querySelector('.hero-authority');
      var descEl      = heroMeta.querySelector('.hero-desc');
      var heroBottom  = heroMeta.querySelector('.hero-bottom');

      if (phylumBadge)  phylumBadge.textContent = sp.phylum;
      if (commonEl)     commonEl.textContent     = sp.common;
      if (binomialEl)   binomialEl.textContent   = sp.binomial;
      if (authorityEl)  authorityEl.textContent  = sp.authority;
      if (descEl)       descEl.textContent        = sp.desc;

      if (heroBottom) {
        // Update IUCN pill
        var iucnPill = heroBottom.querySelector('.iucn-pill');
        if (iucnPill) {
          iucnPill.className   = 'iucn-pill ' + sp.statusClass;
          iucnPill.textContent = sp.status + ' — ' + sp.statusLabel;
        }
        // Update order badge
        var rankVal = heroBottom.querySelector('.rank-badge .rv');
        if (rankVal) rankVal.textContent = sp.order;
        // Swap habitat tags
        var oldTags = heroBottom.querySelectorAll('.habitat-tag');
        oldTags.forEach(function (t) { t.remove(); });
        sp.habitat.forEach(function (h) {
          var tag = document.createElement('span');
          tag.className   = 'habitat-tag';
          tag.textContent = h;
          heroBottom.appendChild(tag);
        });
      }
      // Fade back in
      heroMeta.style.opacity = '1';
    }, 260);
  }

  setInterval(function () {
    currentIdx = (currentIdx + 1) % FEATURED.length;
    updateSpotlight(FEATURED[currentIdx]);
  }, 9000); // 9-second cycle
})();

/* --- Inline sparkline generator ----------------------- */
function drawSparkline(canvasOrSvg, data, color) {
  if (!canvasOrSvg || !data || !data.length) return;
  const w = canvasOrSvg.clientWidth || 80;
  const h = canvasOrSvg.clientHeight || 24;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 4) - 2;
    return `${x},${y}`;
  }).join(' ');
  canvasOrSvg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  canvasOrSvg.innerHTML = `<polyline points="${pts}" fill="none" stroke="${color || '#007A8C'}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>`;
}

// Draw all sparklines on the page
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('[data-sparkline]').forEach(el => {
    const data = JSON.parse(el.dataset.sparkline);
    const color = el.dataset.sparkcolor || '#007A8C';
    drawSparkline(el, data, color);
  });
});

/* --- DOM structure normaliser (runs once on load) ------- */
document.addEventListener('DOMContentLoaded', function () {

  // 1. Ensure every .fg-card-fact-row has <span class="label"> + <span class="value">
  document.querySelectorAll('.fg-card-fact-row').forEach(function (row) {
    var children = Array.from(row.children);
    if (children.length >= 1 && !children[0].className) {
      children[0].className = 'label';
    }
    if (children.length >= 2 && !children[1].className) {
      children[1].className = 'value';
    }
  });

  // 2. Ensure every .fg-card-silhouette has exactly two children
  //    (the SVG + a visually-hidden label span)
  document.querySelectorAll('.fg-card-silhouette').forEach(function (container) {
    var svg = container.querySelector('svg');
    if (svg && !svg.hasAttribute('aria-hidden')) {
      svg.setAttribute('aria-hidden', 'true');
    }
    // Add label span if missing
    var hasLabel = Array.from(container.children).some(function (c) {
      return c.tagName === 'SPAN';
    });
    if (!hasLabel) {
      var card = container.closest('.fg-card');
      var commonName = card ? (card.dataset.common || 'Species') : 'Species';
      var label = document.createElement('span');
      label.className = 'sr-only';
      label.textContent = commonName + ' silhouette';
      container.appendChild(label);
    }
  });

  // 3. Ensure every .species-card-thumb has exactly two children (SVG + label span)
  document.querySelectorAll('.species-card-thumb').forEach(function (container) {
    var svg = container.querySelector('svg');
    if (svg && !svg.hasAttribute('aria-hidden')) {
      svg.setAttribute('aria-hidden', 'true');
    }
    var hasLabel = Array.from(container.children).some(function (c) {
      return c.tagName === 'SPAN';
    });
    if (!hasLabel) {
      var card = container.closest('.species-card');
      var commonName = card
        ? (card.querySelector('.species-card-common') || {}).textContent || 'Species'
        : 'Species';
      var label = document.createElement('span');
      label.className = 'sr-only';
      label.textContent = (commonName.trim() || 'Species') + ' silhouette';
      container.appendChild(label);
    }
  });

  // 4. Ensure every .order-sparkline has exactly two children (SVG + label span)
  document.querySelectorAll('.order-sparkline').forEach(function (container) {
    var svg = container.querySelector('svg');
    if (svg && !svg.hasAttribute('aria-hidden')) {
      svg.setAttribute('aria-hidden', 'true');
    }
    var hasLabel = Array.from(container.children).some(function (c) {
      return c.tagName === 'SPAN';
    });
    if (!hasLabel) {
      var label = document.createElement('span');
      label.className = 'sr-only';
      label.textContent = 'Trend sparkline 2016–2024';
      container.appendChild(label);
    }
  });

});
