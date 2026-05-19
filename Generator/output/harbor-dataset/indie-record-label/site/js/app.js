/* ==========================================
   XEROX PRESSING CO. — site interactions
   ========================================== */

// --- Sample tracklist (label sampler queue) ---
const SAMPLER = [
  { title: "Concrete Lullaby",        artist: "Sable Circuit",       dur: "3:42" },
  { title: "Glasshouse Picket",       artist: "Mara Vex & The Hex",  dur: "4:11" },
  { title: "Tinfoil Cathedral",       artist: "North/Loop",          dur: "5:27" },
  { title: "Pressurized Daydream",    artist: "Tape Hiss Kids",      dur: "2:58" },
  { title: "Disinfectant Aisle",      artist: "Cyanide Florist",     dur: "3:19" },
  { title: "Telegram From Glasgow",   artist: "Annex 47",            dur: "4:48" },
  { title: "Lithograph Heart",        artist: "Halftone Saints",     dur: "3:36" },
  { title: "Drown The Cassette",      artist: "Mute Carrier",        dur: "4:02" },
  { title: "Pink Static",             artist: "Riso Twins",          dur: "3:11" },
  { title: "Plate Press Lullaby",     artist: "Xerox Pressing Co.",  dur: "5:55" }
];

let currentTrack = 0;
let isPlaying = false;
let progress = 34; // percent
let queueOpen = false;

function $(sel, el=document){ return el.querySelector(sel); }
function $$(sel, el=document){ return Array.from(el.querySelectorAll(sel)); }

// --- Player render ---
function renderPlayer() {
  const t = SAMPLER[currentTrack];
  const marq = $(".player-bar .marquee");
  if (marq) {
    marq.textContent = `${t.title} — ${t.artist}   ★   Now Spinning on Xerox Pressing Co.   ★   `;
  }
  const playIcon = $(".player-bar .play .icon");
  if (playIcon) {
    playIcon.className = "icon " + (isPlaying ? "icon-pause" : "icon-play");
  }
  const fill = $(".scrubber .fill");
  const knob = $(".scrubber .knob");
  if (fill) fill.style.width = progress + "%";
  if (knob) knob.style.left = progress + "%";
  // queue popout
  const queueList = $(".queue ul");
  if (queueList) {
    queueList.innerHTML = SAMPLER.map((s,i)=>`
      <li data-i="${i}" class="${i===currentTrack?'current':''}">
        <span>${String(i+1).padStart(2,'0')}. ${s.title}</span>
        <span>${s.dur}</span>
      </li>`).join("");
    $$(".queue li").forEach(li => {
      li.addEventListener("click", () => {
        currentTrack = parseInt(li.dataset.i,10);
        isPlaying = true; progress = 0;
        renderPlayer();
      });
    });
  }
}

function togglePlay(){ isPlaying = !isPlaying; renderPlayer(); }
function next(){ currentTrack = (currentTrack+1) % SAMPLER.length; progress=0; renderPlayer(); }
function prev(){ currentTrack = (currentTrack-1+SAMPLER.length) % SAMPLER.length; progress=0; renderPlayer(); }
function loadTrack(i){ currentTrack = Math.max(0, Math.min(SAMPLER.length-1, i)); isPlaying = true; progress=0; renderPlayer(); }

function attachPlayer() {
  $(".player-bar .play")?.addEventListener("click", togglePlay);
  $(".player-bar .next")?.addEventListener("click", next);
  $(".player-bar .prev")?.addEventListener("click", prev);
  $(".queue-btn")?.addEventListener("click", () => {
    queueOpen = !queueOpen;
    $(".queue")?.classList.toggle("open", queueOpen);
  });
  const trackEl = $(".scrubber .track");
  if (trackEl) {
    trackEl.addEventListener("click", (e) => {
      const r = trackEl.getBoundingClientRect();
      progress = Math.max(0, Math.min(100, ((e.clientX - r.left)/r.width)*100));
      renderPlayer();
    });
  }
  // simulated progress
  setInterval(() => {
    if (isPlaying) {
      progress = (progress + 0.6) % 100;
      const fill = $(".scrubber .fill"); if (fill) fill.style.width = progress + "%";
      const knob = $(".scrubber .knob"); if (knob) knob.style.left = progress + "%";
    }
  }, 600);
}

// --- Sampler tracklist on homepage ---
function attachSampler() {
  $$(".sampler-row").forEach((row, i) => {
    row.addEventListener("click", () => loadTrack(i));
  });
}

// --- Roster filter chips ---
function attachRosterFilter(){
  const chips = $$(".chip-row .chip");
  const cards = $$(".artist-card");
  chips.forEach(chip => {
    chip.addEventListener("click", () => {
      chips.forEach(c => c.classList.remove("on"));
      chip.classList.add("on");
      const tag = chip.dataset.tag;
      cards.forEach(card => {
        const tags = (card.dataset.tags || "").split(",");
        if (tag === "all" || tags.includes(tag)) {
          card.style.display = "";
        } else {
          card.style.display = "none";
        }
      });
    });
  });
  // "hear them" buttons
  $$(".artist-card .hear").forEach(btn => {
    btn.addEventListener("click", e => {
      e.preventDefault();
      const i = parseInt(btn.dataset.track || "0", 10);
      loadTrack(i);
    });
  });
}

// --- Release flip cards ---
function attachFlip(){
  $$(".flip-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      btn.closest(".release-card").classList.toggle("flipped");
    });
  });
  $$(".release-card .face.front").forEach(face => {
    face.addEventListener("click", () => {
      face.closest(".release-card").classList.toggle("flipped");
    });
  });
}

// --- Tour filter ---
function attachTourFilter(){
  const regionChips = $$("[data-region-chip]");
  const ticketToggle = $("#tix-toggle");
  const rows = $$(".tour-row.dat");
  let region = "all";
  let onlyAvail = false;
  function apply(){
    rows.forEach(r => {
      const reg = r.dataset.region;
      const soldOut = r.dataset.sold === "1";
      const okR = region==="all" || reg===region;
      const okT = !onlyAvail || !soldOut;
      r.style.display = (okR && okT) ? "" : "none";
    });
  }
  regionChips.forEach(c => c.addEventListener("click", () => {
    regionChips.forEach(x => x.classList.remove("on"));
    c.classList.add("on");
    region = c.dataset.regionChip;
    apply();
  }));
  if (ticketToggle){
    ticketToggle.addEventListener("change", () => { onlyAvail = ticketToggle.checked; apply(); });
  }
}

// --- Catalog filters (format/year/in-stock) ---
function attachCatalogFilter(){
  const fmt = $("#fmt-filter");
  const yr = $("#year-filter");
  const stockChk = $("#stock-filter");
  const cards = $$(".release-card");
  function apply(){
    cards.forEach(c => {
      const okF = !fmt || fmt.value === "all" || c.dataset.format === fmt.value;
      const okY = !yr || yr.value === "all" || c.dataset.year === yr.value;
      const okS = !stockChk || !stockChk.checked || c.dataset.stock === "1";
      c.style.display = (okF && okY && okS) ? "" : "none";
    });
  }
  [fmt, yr, stockChk].forEach(el => el && el.addEventListener("change", apply));
}

// --- Cart pill ---
function attachCart(){
  let count = parseInt(localStorage.getItem("xrx_cart") || "0", 10);
  const out = $(".cart-pill .count");
  function render(){ if (out) out.textContent = String(count); }
  render();
  $$(".add-to-cart, .product .add").forEach(btn => {
    btn.addEventListener("click", () => {
      count++;
      localStorage.setItem("xrx_cart", String(count));
      render();
      btn.classList.add("bumped");
      setTimeout(()=>btn.classList.remove("bumped"), 200);
    });
  });
}

// --- Variant selector ---
function attachVariants(){
  const variants = $$(".variant:not(.oos)");
  variants.forEach(v => v.addEventListener("click", () => {
    variants.forEach(x => x.classList.remove("on"));
    v.classList.add("on");
  }));
}

// --- Newsletter no-op ---
function attachNewsletter(){
  $$(".tear-off form, .dispatch-form").forEach(f => {
    f.addEventListener("submit", e => {
      e.preventDefault();
      const btn = f.querySelector("button");
      const original = btn.textContent;
      btn.textContent = "Stamped.";
      setTimeout(() => { btn.textContent = original; f.reset(); }, 1800);
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  renderPlayer();
  attachPlayer();
  attachSampler();
  attachRosterFilter();
  attachFlip();
  attachTourFilter();
  attachCatalogFilter();
  attachCart();
  attachVariants();
  attachNewsletter();
});
