/* Pine Tree Hall — small interactions */

/* ---------- Seasonal marker (24 sekki) ---------- */
/* Approximate boundaries within a Gregorian year, in MM-DD start-of-period. */
const SEKKI = [
  { kanji: "立春", romaji: "Risshun",     gloss: "Beginning of spring",   start: "02-04" },
  { kanji: "雨水", romaji: "Usui",        gloss: "Rain water",            start: "02-19" },
  { kanji: "啓蟄", romaji: "Keichitsu",   gloss: "Awakening of insects",  start: "03-06" },
  { kanji: "春分", romaji: "Shunbun",     gloss: "Spring equinox",        start: "03-21" },
  { kanji: "清明", romaji: "Seimei",      gloss: "Pure and bright",       start: "04-05" },
  { kanji: "穀雨", romaji: "Kokuu",       gloss: "Grain rain",            start: "04-20" },
  { kanji: "立夏", romaji: "Rikka",       gloss: "Beginning of summer",   start: "05-06" },
  { kanji: "小満", romaji: "Shōman",      gloss: "Lesser fullness",       start: "05-21" },
  { kanji: "芒種", romaji: "Bōshu",       gloss: "Grain in ear",          start: "06-06" },
  { kanji: "夏至", romaji: "Geshi",       gloss: "Summer solstice",       start: "06-21" },
  { kanji: "小暑", romaji: "Shōsho",      gloss: "Lesser heat",           start: "07-07" },
  { kanji: "大暑", romaji: "Taisho",      gloss: "Greater heat",          start: "07-23" },
  { kanji: "立秋", romaji: "Risshū",      gloss: "Beginning of autumn",   start: "08-08" },
  { kanji: "処暑", romaji: "Shosho",      gloss: "End of heat",           start: "08-23" },
  { kanji: "白露", romaji: "Hakuro",      gloss: "White dew",             start: "09-08" },
  { kanji: "秋分", romaji: "Shūbun",      gloss: "Autumn equinox",        start: "09-23" },
  { kanji: "寒露", romaji: "Kanro",       gloss: "Cold dew",              start: "10-08" },
  { kanji: "霜降", romaji: "Sōkō",        gloss: "Descent of frost",      start: "10-23" },
  { kanji: "立冬", romaji: "Rittō",       gloss: "Beginning of winter",   start: "11-07" },
  { kanji: "小雪", romaji: "Shōsetsu",    gloss: "Lesser snow",           start: "11-22" },
  { kanji: "大雪", romaji: "Taisetsu",    gloss: "Greater snow",          start: "12-07" },
  { kanji: "冬至", romaji: "Tōji",        gloss: "Winter solstice",       start: "12-22" },
  { kanji: "小寒", romaji: "Shōkan",      gloss: "Lesser cold",           start: "01-06" },
  { kanji: "大寒", romaji: "Daikan",      gloss: "Greater cold",          start: "01-20" }
];

function currentSekki(date) {
  const mmdd = (date.getMonth() + 1).toString().padStart(2, "0") + "-" +
               date.getDate().toString().padStart(2, "0");
  // Walk year linearly. Risshun-anchored cycle.
  let last = SEKKI[SEKKI.length - 1]; // Daikan
  for (let i = 0; i < SEKKI.length; i++) {
    const s = SEKKI[i];
    if (mmdd >= s.start) last = s;
  }
  // Handle wrap before Risshun (early Jan / late Jan)
  if (mmdd < SEKKI[0].start) {
    last = (mmdd >= SEKKI[23].start) ? SEKKI[23] : SEKKI[22];
  }
  return last;
}

function renderSekki() {
  const el = document.querySelector("[data-sekki]");
  if (!el) return;
  const now = new Date();
  const s = currentSekki(now);
  el.querySelector("[data-sekki-kanji]").textContent = s.kanji;
  el.querySelector("[data-sekki-romaji]").textContent = s.romaji + " — " + s.gloss;
  const yEl = el.querySelector("[data-sekki-year]");
  if (yEl) yEl.textContent = now.getFullYear();
}

/* ---------- Schedule row note reveal (tap to keep open on touch) ---------- */
function bindRowNotes() {
  document.querySelectorAll(".has-note").forEach(row => {
    row.addEventListener("click", () => row.classList.toggle("is-open"));
  });
}

/* ---------- Lineage biography ---------- */
function bindLineage() {
  const bio = document.querySelector("[data-bio]");
  if (!bio) return;
  document.querySelectorAll(".node").forEach(node => {
    node.addEventListener("click", () => {
      const data = {
        dharma:  node.dataset.dharma,
        given:   node.dataset.given,
        years:   node.dataset.years,
        role:    node.dataset.role,
        lineage: node.dataset.lineage,
        body:    node.dataset.body
      };
      bio.querySelector("[data-bio-dharma]").textContent = data.dharma || "";
      bio.querySelector("[data-bio-given]").textContent  = data.given  || "";
      bio.querySelector("[data-bio-years]").textContent  = data.years  || "";
      bio.querySelector("[data-bio-role]").textContent   = data.role   || "";
      bio.querySelector("[data-bio-lineage]").textContent= data.lineage|| "";
      bio.querySelector("[data-bio-body]").textContent   = data.body   || "";
      bio.classList.add("is-open");
    });
  });
  bio.querySelector(".bio__close").addEventListener("click", () => bio.classList.remove("is-open"));
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") bio.classList.remove("is-open");
  });
}

/* ---------- Schedule / retreat filters ---------- */
function bindFilters() {
  document.querySelectorAll("[data-filterbar]").forEach(bar => {
    const target = bar.dataset.filterbar; // selector for items
    bar.querySelectorAll(".chip").forEach(chip => {
      chip.addEventListener("click", () => {
        bar.querySelectorAll(".chip").forEach(c => c.classList.remove("is-on"));
        chip.classList.add("is-on");
        const f = chip.dataset.filter;
        document.querySelectorAll(target).forEach(item => {
          if (f === "all" || (item.dataset.tags || "").split(/\s+/).includes(f)) {
            item.hidden = false;
          } else {
            item.hidden = true;
          }
        });
      });
    });
  });
}

/* ---------- Audio archive ---------- */
function bindArchive() {
  const list = document.querySelector("[data-talks]");
  if (!list) return;

  const filters = { teacher: "all", theme: "all", year: "all" };

  document.querySelectorAll("[data-rail]").forEach(ul => {
    const key = ul.dataset.rail;
    ul.querySelectorAll("li").forEach(li => {
      li.addEventListener("click", () => {
        ul.querySelectorAll("li").forEach(x => x.classList.remove("is-on"));
        li.classList.add("is-on");
        filters[key] = li.dataset.val;
        applyArchive();
      });
    });
  });

  function applyArchive() {
    list.querySelectorAll(".talk").forEach(t => {
      const matches =
        (filters.teacher === "all" || t.dataset.teacher === filters.teacher) &&
        (filters.theme   === "all" || t.dataset.theme   === filters.theme)   &&
        (filters.year    === "all" || t.dataset.year    === filters.year);
      t.hidden = !matches;
    });
  }

  list.querySelectorAll(".talk").forEach(t => {
    t.addEventListener("click", () => selectTalk(t));
  });

  function selectTalk(t) {
    list.querySelectorAll(".talk").forEach(x => x.classList.remove("is-selected"));
    t.classList.add("is-selected");
    const np = document.querySelector("[data-now]");
    if (np) {
      np.querySelector("[data-now-title]").textContent = t.dataset.title;
      np.querySelector("[data-now-meta]").textContent  =
        t.dataset.teacher_name + " — " + t.dataset.date + " — " + t.dataset.dur;
      np.querySelector("[data-now-desc]").textContent = t.dataset.desc;
    }
    const pl = document.querySelector("[data-player]");
    if (pl) {
      pl.querySelector("[data-player-title]").textContent = t.dataset.title;
      pl.querySelector("[data-player-by]").textContent    = t.dataset.teacher_name;
      pl.querySelector("[data-player-time]").textContent  = "00:00 / " + t.dataset.dur;
    }
  }
}

/* ---------- Dana band selection + free input clear ---------- */
function bindBands() {
  document.querySelectorAll("[data-bands]").forEach(group => {
    const input = group.parentElement.querySelector(".free-input input");
    group.querySelectorAll(".band").forEach(b => {
      b.addEventListener("click", () => {
        group.querySelectorAll(".band").forEach(x => x.classList.remove("is-on"));
        b.classList.add("is-on");
        if (input) input.value = b.dataset.amount;
      });
    });
    if (input) {
      input.addEventListener("input", () => {
        group.querySelectorAll(".band").forEach(x => x.classList.remove("is-on"));
      });
    }
  });
}

/* ---------- Multi-step retreat form ---------- */
function bindSteps() {
  const form = document.querySelector("[data-steps]");
  if (!form) return;
  const steps = Array.from(form.querySelectorAll(".step"));
  let i = 0;
  show(0);

  function show(n) {
    steps.forEach((s, k) => s.classList.toggle("is-on", k === n));
    i = n;
  }

  form.addEventListener("click", e => {
    if (e.target.matches("[data-next]")) {
      e.preventDefault();
      if (i < steps.length - 1) show(i + 1);
    }
    if (e.target.matches("[data-prev]")) {
      e.preventDefault();
      if (i > 0) show(i - 1);
    }
  });
}

/* ---------- Init ---------- */
document.addEventListener("DOMContentLoaded", () => {
  renderSekki();
  bindRowNotes();
  bindLineage();
  bindFilters();
  bindArchive();
  bindBands();
  bindSteps();
});
