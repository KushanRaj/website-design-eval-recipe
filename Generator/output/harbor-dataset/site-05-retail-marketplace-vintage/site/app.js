// Barnyard & Bone — interactions

(function () {
  // ----- Drop countdown -----
  function nextThursdayNoonCentral() {
    const now = new Date();
    // Target: next Thursday 12:00 (treat as local, fine for demo)
    const target = new Date(now);
    const day = now.getDay(); // 0 Sun .. 4 Thu
    let delta = (4 - day + 7) % 7;
    target.setHours(12, 0, 0, 0);
    if (delta === 0 && now.getTime() > target.getTime()) delta = 7;
    target.setDate(target.getDate() + delta);
    return target;
  }
  function tickCountdown() {
    const target = nextThursdayNoonCentral();
    document.querySelectorAll("[data-countdown]").forEach(root => {
      const diff = Math.max(0, target.getTime() - Date.now());
      const d = Math.floor(diff / 86400000);
      const h = Math.floor((diff / 3600000) % 24);
      const m = Math.floor((diff / 60000) % 60);
      const s = Math.floor((diff / 1000) % 60);
      const pad = n => String(n).padStart(2, "0");
      const set = (sel, v) => {
        const el = root.querySelector(sel);
        if (el) el.textContent = v;
      };
      set("[data-d]", pad(d));
      set("[data-h]", pad(h));
      set("[data-m]", pad(m));
      set("[data-s]", pad(s));
    });
  }
  tickCountdown();
  setInterval(tickCountdown, 1000);

  // ----- Density toggle on browse -----
  document.querySelectorAll(".density-toggle").forEach(group => {
    group.addEventListener("click", e => {
      const btn = e.target.closest("button");
      if (!btn) return;
      group.querySelectorAll("button").forEach(b => b.classList.remove("on"));
      btn.classList.add("on");
      const cols = btn.dataset.cols;
      const grid = document.querySelector("[data-masonry]");
      if (grid) {
        grid.classList.remove("cols-3", "cols-5", "cols-8");
        grid.classList.add("cols-" + cols);
      }
    });
  });

  // ----- Facet pills multi-select -----
  document.querySelectorAll(".facet-pill").forEach(pill => {
    pill.addEventListener("click", () => pill.classList.toggle("on"));
  });

  // ----- Watch (heart) buttons -----
  document.querySelectorAll(".watch-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.preventDefault();
      e.stopPropagation();
      btn.classList.toggle("on");
      btn.textContent = btn.classList.contains("on") ? "♥" : "♡";
    });
  });

  // ----- Patina report expand -----
  document.querySelectorAll(".patina-head").forEach(head => {
    head.addEventListener("click", () => {
      const body = head.nextElementSibling;
      if (!body) return;
      body.style.display = body.style.display === "none" ? "grid" : "none";
      const caret = head.querySelector(".caret-x");
      if (caret) caret.textContent = body.style.display === "none" ? "+" : "—";
    });
  });

  // ----- Freight quote -----
  const freightForm = document.querySelector("[data-freight]");
  if (freightForm) {
    freightForm.addEventListener("submit", e => {
      e.preventDefault();
      const zip = freightForm.querySelector("input").value.trim() || "94110";
      // Pseudo geocoding: hash zip to coords
      const seed = [...zip].reduce((a, c) => a + c.charCodeAt(0), 0);
      const lat = 30 + (seed % 18);
      const lng = -120 + ((seed * 7) % 50);
      const miles = Math.round(400 + (seed * 13) % 1800);
      const days = Math.round(4 + miles / 350);
      const price = Math.round(180 + miles * 0.35);
      const map = document.querySelector("[data-route-map]");
      if (map) {
        map.innerHTML = `
          <svg viewBox="0 0 400 180" preserveAspectRatio="none">
            <defs>
              <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
                <path d="M 20 0 L 0 0 0 20" fill="none" stroke="rgba(212,165,55,0.12)" stroke-width="0.5"/>
              </pattern>
            </defs>
            <rect width="400" height="180" fill="url(#grid)"/>
            <path d="M 60 140 Q 180 40, 340 60" stroke="#D4A537" stroke-width="3" fill="none" stroke-dasharray="6 4"/>
            <circle cx="60" cy="140" r="7" fill="#A8392B" stroke="#F2E8D5" stroke-width="2"/>
            <circle cx="340" cy="60" r="7" fill="#D4A537" stroke="#F2E8D5" stroke-width="2"/>
            <text x="60" y="160" fill="#F2E8D5" font-family="Helvetica Neue, Arial" font-size="10" letter-spacing="2">SELLER</text>
            <text x="300" y="50" fill="#F2E8D5" font-family="Helvetica Neue, Arial" font-size="10" letter-spacing="2">${zip.toUpperCase()}</text>
          </svg>
        `;
      }
      const out = document.querySelector("[data-freight-out]");
      if (out) {
        out.innerHTML = `
          <div><b>$${price}</b>freight</div>
          <div><b>${miles}</b>miles</div>
          <div><b>${days}d</b>est. arrival</div>
        `;
      }
    });
  }

  // ----- Cart drawer toggle -----
  const drawer = document.querySelector(".cart-drawer");
  if (drawer) {
    const head = drawer.querySelector(".drawer-head");
    head.addEventListener("click", () => drawer.classList.toggle("collapsed"));
  }

  // ----- Fulfillment toggle in cart -----
  document.querySelectorAll(".fulfill-toggle").forEach(group => {
    group.addEventListener("click", e => {
      const btn = e.target.closest("button");
      if (!btn) return;
      group.querySelectorAll("button").forEach(b => b.classList.remove("on"));
      btn.classList.add("on");
    });
  });

  // ----- Hotspots -----
  document.querySelectorAll(".hotspot").forEach(spot => {
    spot.addEventListener("click", () => {
      const title = spot.dataset.title || "Listing";
      alert("Shop the photo →  " + title);
    });
  });

  // ----- Region chips toggle -----
  document.querySelectorAll(".region-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      chip.classList.toggle("on");
    });
  });

  // ----- Save search faux -----
  const saveBtn = document.querySelector(".save-search");
  if (saveBtn) {
    saveBtn.addEventListener("click", () => {
      saveBtn.textContent = "Saved ✓";
      saveBtn.style.background = "var(--ink)";
    });
  }
})();
