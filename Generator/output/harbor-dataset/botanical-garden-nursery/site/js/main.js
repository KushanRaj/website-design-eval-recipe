/* Fernwood Conservatory — small interactions, vanilla JS */

(function () {
  'use strict';

  // ---------- Bloom calendar: month slider --------------------------------
  const monthInput = document.querySelector('#month-slider');
  const monthStrip = document.querySelector('.month-strip');
  const wheel = document.querySelector('#bloom-wheel');
  const currentMonth = document.querySelector('#current-month');
  const peakList = document.querySelector('#peak-list');
  const months = ['Januario','Februario','Martio','Aprile','Maio','Junio','Julio','Augusto','Septembre','Octobre','Novembre','Decembre'];
  const monthsEn = ['January','February','March','April','May','June','July','August','September','October','November','December'];

  // species peak data — index 0..11, multiple months allowed
  const bloomData = [
    { sp: 'Galanthus reginae-olgae',      common: 'Autumn Snowdrop',     months: [0,1,10,11],  zone: 'Alpine Bank',      light: 'Dappled' },
    { sp: 'Helleborus × hybridus',        common: 'Lenten Rose',          months: [1,2,3],      zone: 'Woodland Walk',    light: 'Part shade' },
    { sp: 'Magnolia campbellii',          common: 'Himalayan Magnolia',   months: [2,3],        zone: 'Camellia Glade',   light: 'Full sun' },
    { sp: 'Erythronium revolutum',        common: 'Pink Fawn Lily',       months: [3,4],        zone: 'Mossy Hollow',     light: 'Dappled' },
    { sp: 'Paphiopedilum fairrieanum',    common: "Fairrie's Slipper",    months: [4,5,6],      zone: 'Glasshouse III',   light: 'Diffused' },
    { sp: 'Meconopsis betonicifolia',     common: 'Himalayan Blue Poppy', months: [5,6],        zone: 'Stone Garden',     light: 'Cool morning' },
    { sp: 'Lilium auratum',               common: 'Goldband Lily',        months: [6,7],        zone: 'Cutting Beds',     light: 'Full sun' },
    { sp: 'Hydrangea aspera',             common: 'Rough Hydrangea',      months: [7,8],        zone: 'Woodland Walk',    light: 'Part shade' },
    { sp: 'Colchicum speciosum',          common: 'Autumn Crocus',        months: [8,9],        zone: 'Meadow Slope',     light: 'Full sun' },
    { sp: 'Camellia sasanqua',            common: 'Christmas Camellia',   months: [9,10,11],    zone: 'Camellia Glade',   light: 'Part shade' },
    { sp: 'Hamamelis × intermedia',       common: 'Witch Hazel',          months: [0,1],        zone: 'Winter Garden',    light: 'Full sun' },
    { sp: 'Rhododendron sinogrande',      common: 'Giant-Leaved Rhodo.',  months: [3,4],        zone: 'Rhododendron Dell',light: 'Dappled' }
  ];

  function renderWheel(month) {
    if (!wheel) return;
    const arcs = wheel.querySelectorAll('[data-species]');
    arcs.forEach(arc => {
      const list = arc.dataset.months.split(',').map(Number);
      if (list.indexOf(month) > -1) {
        arc.setAttribute('fill', '#d36247');
        arc.setAttribute('opacity', '0.92');
      } else {
        arc.setAttribute('fill', '#647a4f');
        arc.setAttribute('opacity', '0.32');
      }
    });
  }
  function renderPeakList(month) {
    if (!peakList) return;
    const peaking = bloomData.filter(d => d.months.indexOf(month) > -1);
    peakList.innerHTML = peaking.map(p => `
      <article class="peak-card">
        <div class="peak-when">Peak — ${monthsEn[month]}</div>
        <h3 class="binomial">${p.sp}</h3>
        <div class="caption">${p.common}</div>
        <dl>
          <dt>Zone</dt><dd>${p.zone}</dd>
          <dt>Light</dt><dd>${p.light}</dd>
          <dt>Map</dt><dd><a href="garden-map.html">View location ↗</a></dd>
        </dl>
      </article>
    `).join('');
  }
  function setMonth(m) {
    m = Math.max(0, Math.min(11, m));
    if (monthInput) monthInput.value = m;
    if (currentMonth) currentMonth.textContent = months[m];
    if (monthStrip) {
      monthStrip.querySelectorAll('span').forEach((s, i) => s.classList.toggle('is-active', i === m));
    }
    renderWheel(m);
    renderPeakList(m);
  }
  if (monthInput) {
    monthInput.addEventListener('input', e => setMonth(parseInt(e.target.value, 10)));
  }
  if (monthStrip) {
    monthStrip.querySelectorAll('span').forEach((s, i) => {
      s.addEventListener('click', () => setMonth(i));
    });
  }
  if (wheel || monthInput) {
    const now = new Date().getMonth();
    setMonth(now);
  }

  // ---------- Garden map: zone hover/click --------------------------------
  const zones = document.querySelectorAll('.map-wrap .zone');
  const zoneTitle = document.querySelector('#zone-title');
  const zoneTag = document.querySelector('#zone-tag');
  const zoneBody = document.querySelector('#zone-body');
  const zoneAccess = document.querySelector('#zone-access');
  const zoneCoord = document.querySelector('#zone-coord');
  const zoneSig = document.querySelector('#zone-signature');

  const zoneData = {
    glasshouses: { name: 'The Glasshouses', tag: 'Conservatory · 0.8 ac', body: 'Three connected Victorian-style glasshouses housing the orchid, fernery, and tropical collections. Maintained at 18–24 °C with diffused light through frosted panes.', access: 'Step-free entry · Glasshouse I has a tactile orchid bench', coord: 'N 47°36′21″ / W 122°19′10″', signature: 'Paphiopedilum, Platycerium, Vireya rhododendrons' },
    woodland:    { name: 'Woodland Walk', tag: 'Naturalistic · 3.4 ac', body: 'A canopied loop beneath second-growth Douglas-fir and bigleaf maple. Spring ephemerals dominate March through May, ferns persist year-round.', access: 'Compacted gravel · seating every 60 m', coord: 'N 47°36′28″ / W 122°19′02″', signature: 'Trillium, Erythronium, Helleborus' },
    alpine:      { name: 'Alpine Bank', tag: 'Crevice & Scree · 1.2 ac', body: 'A south-facing scree of stratified basalt and pumice supporting saxifrages, dianthus, and cushion plants from the world\'s ranges.', access: 'Steep grade · stepped path with handrail', coord: 'N 47°36′32″ / W 122°19′16″', signature: 'Saxifraga, Daphne, Androsace' },
    camellia:    { name: 'Camellia Glade', tag: 'Heritage Collection · 1.6 ac', body: 'The conservatory\'s oldest planting — 47 cultivars established between 1928 and 1962, with several originals from the founder\'s Japanese correspondence.', access: 'Paved loop · benches throughout', coord: 'N 47°36′18″ / W 122°19′22″', signature: 'Camellia japonica, C. sasanqua, C. reticulata' },
    rhodo:       { name: 'Rhododendron Dell', tag: 'Sino-Himalayan · 2.1 ac', body: 'A sheltered ravine planted with tree rhododendrons from southwestern China and northeastern India. Peak bloom mid-April to mid-May.', access: 'Sloped path · viewing platform at base', coord: 'N 47°36′34″ / W 122°19′05″', signature: 'R. sinogrande, R. macabeanum, R. arboreum' },
    meadow:      { name: 'Meadow Slope', tag: 'Pollinator Reserve · 1.9 ac', body: 'A converted hay-pasture now seeded with native and introduced perennials. Managed with autumn cut only — supports 31 species of native bees.', access: 'Mown path through tall grass', coord: 'N 47°36′24″ / W 122°19′28″', signature: 'Echinacea, Eryngium, Asclepias' },
    stone:       { name: 'Stone Garden', tag: 'Himalayan Cool · 0.7 ac', body: 'An assembly of split basalt and weathered granite framing Himalayan poppies, primulas, and choice species fortuitous to our cool, damp summers.', access: 'Crushed stone paths', coord: 'N 47°36′30″ / W 122°19′13″', signature: 'Meconopsis, Primula, Cardiocrinum' },
    cutting:     { name: 'Cutting Beds', tag: 'Working Garden · 1.0 ac', body: 'Production beds supplying the cut-flower programme that funds youth education. Designed in long colour-graded ranks.', access: 'Wide gravel paths between beds', coord: 'N 47°36′16″ / W 122°19′18″', signature: 'Dahlia, Lilium, Eustoma' },
    nursery:     { name: 'Propagation Nursery', tag: 'Public Saturdays', body: 'The working heart of the rare-plant nursery — seed frames, mist house, and grafting bench. Visitors welcome 10–2 every Saturday.', access: 'Paved · wash station at entrance', coord: 'N 47°36′14″ / W 122°19′24″', signature: 'Seed-grown rarities, divisions, grafts' },
    welcome:     { name: 'Welcome Pavilion', tag: 'Visitor Services', body: 'Admissions, members\' lounge, café Hortus, shop, and the herbarium reading room. Free Wi-Fi for member-patrons.', access: 'Step-free · accessible restrooms', coord: 'N 47°36′22″ / W 122°19′32″', signature: 'Tea, books, & garden orientation' }
  };

  function setZone(key) {
    const data = zoneData[key];
    if (!data) return;
    if (zoneTitle) zoneTitle.textContent = data.name;
    if (zoneTag) zoneTag.textContent = data.tag;
    if (zoneBody) zoneBody.textContent = data.body;
    if (zoneAccess) zoneAccess.textContent = data.access;
    if (zoneCoord) zoneCoord.textContent = data.coord;
    if (zoneSig) zoneSig.textContent = data.signature;
    zones.forEach(z => z.classList.toggle('is-active', z.dataset.zone === key));
  }
  zones.forEach(z => {
    z.addEventListener('mouseenter', () => setZone(z.dataset.zone));
    z.addEventListener('focus', () => setZone(z.dataset.zone));
    z.addEventListener('click', () => setZone(z.dataset.zone));
  });
  if (zones.length) setZone('glasshouses');

  // ---------- Encyclopedia entry: sticky tabs -----------------------------
  const entryTabs = document.querySelectorAll('.entry-tabs a');
  entryTabs.forEach(t => {
    t.addEventListener('click', e => {
      const id = t.getAttribute('href');
      if (id && id.charAt(0) === '#') {
        e.preventDefault();
        const tgt = document.querySelector(id);
        if (tgt) {
          entryTabs.forEach(x => x.classList.remove('is-active'));
          t.classList.add('is-active');
          window.scrollTo({ top: tgt.offsetTop - 60, behavior: 'smooth' });
        }
      }
    });
  });

  // observe sections to set active tab
  const tabbedSections = document.querySelectorAll('.entry-section[id]');
  if (tabbedSections.length && entryTabs.length && 'IntersectionObserver' in window) {
    const obs = new IntersectionObserver(entries => {
      entries.forEach(en => {
        if (en.isIntersecting) {
          const id = '#' + en.target.id;
          entryTabs.forEach(t => t.classList.toggle('is-active', t.getAttribute('href') === id));
        }
      });
    }, { rootMargin: '-40% 0% -40% 0%' });
    tabbedSections.forEach(s => obs.observe(s));
  }

  // ---------- Workshops: calendar/list toggle -----------------------------
  const toggleBtns = document.querySelectorAll('[data-view]');
  toggleBtns.forEach(b => {
    b.addEventListener('click', () => {
      toggleBtns.forEach(x => x.classList.toggle('is-active', x === b));
      const v = b.dataset.view;
      const cal = document.querySelector('#calendar-view');
      const list = document.querySelector('#list-view');
      if (cal) cal.style.display = v === 'calendar' ? '' : 'none';
      if (list) list.style.display = v === 'list' ? '' : 'none';
    });
  });

  // ---------- Shop: simple add-to-cart counter ----------------------------
  const cartCount = document.querySelector('#cart-count');
  let cart = 0;
  document.querySelectorAll('[data-add]').forEach(btn => {
    btn.addEventListener('click', e => {
      e.preventDefault();
      cart += 1;
      if (cartCount) cartCount.textContent = '(' + cart + ')';
      btn.textContent = 'Added ✓';
      setTimeout(() => { btn.textContent = btn.dataset.add; }, 1400);
    });
  });

  // ---------- Field notes: tag filter (visual only) -----------------------
  document.querySelectorAll('.tag-row .chip').forEach(chip => {
    chip.addEventListener('click', () => {
      chip.classList.toggle('coral');
    });
  });

  // ---------- Encyclopedia filters (visual sample) ------------------------
  const encSearch = document.querySelector('#enc-search');
  if (encSearch) {
    const cards = document.querySelectorAll('.plate-card');
    encSearch.addEventListener('input', () => {
      const q = encSearch.value.trim().toLowerCase();
      cards.forEach(c => {
        const txt = c.textContent.toLowerCase();
        c.style.display = q === '' || txt.indexOf(q) > -1 ? '' : 'none';
      });
    });
  }

})();
