/* TAON-1 client-side glue — minimal vanilla JS.
   - Live UTC clock + packet status updates
   - Expandable log rows
   - Gear comparison cart (max 4)
   - CWA accordion
   - Calendar day side-panel
   - Gallery filter chips + lightbox + radar overlay toggle
*/

(function () {
  "use strict";

  // ---- UTC clock & packet status -------------------------------------------
  function pad(n) { return String(n).padStart(2, "0"); }
  function fmtUTC(d) {
    return (
      d.getUTCFullYear() + "-" +
      pad(d.getUTCMonth() + 1) + "-" +
      pad(d.getUTCDate()) + " " +
      pad(d.getUTCHours()) + ":" +
      pad(d.getUTCMinutes()) + ":" +
      pad(d.getUTCSeconds()) + "Z"
    );
  }
  function tickClock() {
    document.querySelectorAll("[data-utc]").forEach(function (el) {
      el.textContent = fmtUTC(new Date());
    });
  }
  tickClock();
  setInterval(tickClock, 1000);

  // Pseudo-random but stable seeded last-strike timer
  var startMs = Date.now();
  function tickStrike() {
    document.querySelectorAll("[data-lastStrike]").forEach(function (el) {
      var s = Math.floor((Date.now() - startMs) / 1000) % 600;
      el.textContent = "T-" + pad(Math.floor(s / 60)) + ":" + pad(s % 60);
    });
    document.querySelectorAll("[data-chasers]").forEach(function (el) {
      var base = 47;
      var jitter = Math.floor((Date.now() / 7000) % 8);
      el.textContent = (base + jitter);
    });
  }
  tickStrike();
  setInterval(tickStrike, 1000);

  // ---- Expandable log rows --------------------------------------------------
  document.querySelectorAll("table.grid .expander").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var tr = btn.closest("tr");
      var next = tr.nextElementSibling;
      if (next && next.classList.contains("expand-row")) {
        var hidden = next.style.display === "none" || next.style.display === "";
        next.style.display = hidden ? "table-row" : "none";
        btn.textContent = hidden ? "−" : "+";
      }
    });
  });

  // ---- Gear comparison cart (max 4) ----------------------------------------
  var cartKey = "taon-gear-cart";
  function readCart() {
    try { return JSON.parse(localStorage.getItem(cartKey) || "[]"); }
    catch (e) { return []; }
  }
  function writeCart(arr) {
    localStorage.setItem(cartKey, JSON.stringify(arr));
    renderCart();
  }
  function renderCart() {
    var holder = document.getElementById("cart-slots");
    if (!holder) return;
    var items = readCart();
    var slots = holder.querySelectorAll(".slot");
    slots.forEach(function (slot, i) {
      var name = items[i];
      if (name) {
        slot.classList.add("filled");
        slot.innerHTML = "<span>" + name + "</span><span class='x' data-idx='" + i + "'>[X]</span>";
      } else {
        slot.classList.remove("filled");
        slot.innerHTML = "<span>SLOT " + (i + 1) + " — empty</span>";
      }
    });
    holder.querySelectorAll(".x").forEach(function (x) {
      x.addEventListener("click", function () {
        var idx = parseInt(x.getAttribute("data-idx"), 10);
        var arr = readCart();
        arr.splice(idx, 1);
        writeCart(arr);
      });
    });
    var btn = document.getElementById("cart-compare-btn");
    if (btn) {
      btn.disabled = items.length < 2;
      btn.textContent = items.length < 2
        ? "ADD 2+ ITEMS TO DIFF"
        : "DIFF " + items.length + " ITEMS →";
    }
  }
  document.querySelectorAll(".gear-card .add-cart").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var name = btn.getAttribute("data-name");
      var arr = readCart();
      if (arr.indexOf(name) >= 0) return;
      if (arr.length >= 4) return;
      arr.push(name);
      writeCart(arr);
    });
  });
  var clearBtn = document.getElementById("cart-clear");
  if (clearBtn) clearBtn.addEventListener("click", function () { writeCart([]); });
  renderCart();

  // ---- CWA accordion --------------------------------------------------------
  document.querySelectorAll(".accordion .cwa .head").forEach(function (h) {
    h.addEventListener("click", function () {
      h.parentElement.classList.toggle("open");
    });
  });

  // ---- Calendar day click ---------------------------------------------------
  var dayDetail = document.getElementById("day-detail");
  if (dayDetail) {
    document.querySelectorAll(".calendar .day[data-detail]").forEach(function (d) {
      d.addEventListener("click", function () {
        document.querySelectorAll(".calendar .day.active").forEach(function (x) {
          x.classList.remove("active");
        });
        d.classList.add("active");
        try {
          var data = JSON.parse(d.getAttribute("data-detail"));
          renderDayDetail(data, d.getAttribute("data-date"));
        } catch (e) {}
      });
    });
  }
  function renderDayDetail(data, dateStr) {
    if (!dayDetail) return;
    var rsvps = (data.rsvps || []).map(function (r) {
      return "<li><span class='cs amber'>" + r + "</span></li>";
    }).join("");
    var hazards = (data.hazards || []).map(function (h) {
      return "<tr><td>" + h.k + "</td><td class='num'>" + h.p + "%</td><td>" + (h.note || "") + "</td></tr>";
    }).join("");
    dayDetail.innerHTML = "" +
      "<h3>" + dateStr + " — " + (data.cat || "—") + "</h3>" +
      "<div class='dim'>" + (data.summary || "") + "</div>" +
      "<hr class='ascii'/>" +
      "<table class='grid'><thead><tr><th>HAZARD</th><th>PROB</th><th>NOTES</th></tr></thead><tbody>" +
      hazards + "</tbody></table>" +
      "<hr class='ascii'/>" +
      "<div class='dim'>PARTICIPATING CHASERS</div>" +
      "<ul style='margin:4px 0; padding-left:18px;'>" + rsvps + "</ul>" +
      "<hr class='ascii'/>" +
      "<div class='dim'>RENDEZVOUS</div>" +
      "<div>" + (data.rdv || "TBD") + "</div>";
  }

  // ---- Gallery filter chips -------------------------------------------------
  var chipBar = document.querySelector(".chips[data-filter]");
  if (chipBar) {
    chipBar.querySelectorAll(".chip").forEach(function (c) {
      c.addEventListener("click", function () {
        chipBar.querySelectorAll(".chip").forEach(function (x) { x.classList.remove("active"); });
        c.classList.add("active");
        var k = c.getAttribute("data-key");
        document.querySelectorAll(".masonry .tile").forEach(function (t) {
          var tags = (t.getAttribute("data-tags") || "").split(",");
          var show = k === "all" || tags.indexOf(k) >= 0;
          t.style.display = show ? "" : "none";
        });
      });
    });
  }

  // ---- Lightbox -------------------------------------------------------------
  var lb = document.getElementById("lightbox");
  if (lb) {
    document.querySelectorAll(".masonry .tile").forEach(function (t) {
      t.addEventListener("click", function () {
        var data = {
          cs: t.getAttribute("data-cs") || "—",
          loc: t.getAttribute("data-loc") || "—",
          time: t.getAttribute("data-time") || "—",
          lens: t.getAttribute("data-lens") || "—",
          notes: t.getAttribute("data-notes") || "",
          tags: t.getAttribute("data-tags") || ""
        };
        var inner = t.querySelector(".img").outerHTML;
        var canvas = lb.querySelector(".photo .canvas");
        canvas.innerHTML = inner + "<div class='radar-overlay'></div>";
        lb.querySelector(".side").innerHTML = "" +
          "<div class='dim'>PHOTOGRAPHER</div>" +
          "<div class='amber'><strong>" + data.cs + "</strong></div>" +
          "<hr class='ascii'/>" +
          "<div class='kv'>" +
            "<div class='k'>LOCATION</div><div>" + data.loc + "</div>" +
            "<div class='k'>TIME</div><div>" + data.time + "</div>" +
            "<div class='k'>LENS</div><div>" + data.lens + "</div>" +
            "<div class='k'>TAGS</div><div>" + data.tags + "</div>" +
          "</div>" +
          "<hr class='ascii'/>" +
          "<div>" + data.notes + "</div>" +
          "<hr class='ascii'/>" +
          "<button class='btn amber' id='radar-toggle'>OVERLAY: RADAR @ SHOT TIME</button>";
        lb.classList.add("open");
        lb.classList.remove("show-radar");
        var rt = document.getElementById("radar-toggle");
        if (rt) rt.addEventListener("click", function () {
          lb.classList.toggle("show-radar");
        });
      });
    });
    lb.querySelector(".close").addEventListener("click", function () {
      lb.classList.remove("open");
    });
    lb.addEventListener("click", function (e) {
      if (e.target === lb) lb.classList.remove("open");
    });
  }

  // ---- SPC tabs -------------------------------------------------------------
  document.querySelectorAll(".spc").forEach(function (spc) {
    var btns = spc.querySelectorAll(".tabs button");
    btns.forEach(function (b) {
      b.addEventListener("click", function () {
        btns.forEach(function (x) { x.classList.remove("active"); });
        b.classList.add("active");
        var k = b.getAttribute("data-tab");
        spc.querySelectorAll("[data-day]").forEach(function (g) {
          g.style.display = g.getAttribute("data-day") === k ? "" : "none";
        });
      });
    });
  });

  // ---- Callsign hover-card --------------------------------------------------
  var hc = document.createElement("div");
  hc.id = "cs-hover";
  hc.style.cssText = "position:fixed;z-index:200;display:none;background:#02080a;border:1px solid #ffae28;color:#ffae28;padding:8px;font-size:11px;font-family:var(--mono);min-width:200px;";
  document.body.appendChild(hc);
  document.querySelectorAll("[data-cs-card]").forEach(function (el) {
    el.addEventListener("mouseenter", function (e) {
      hc.innerHTML = el.getAttribute("data-cs-card");
      hc.style.display = "block";
    });
    el.addEventListener("mousemove", function (e) {
      hc.style.left = (e.clientX + 12) + "px";
      hc.style.top = (e.clientY + 12) + "px";
    });
    el.addEventListener("mouseleave", function () {
      hc.style.display = "none";
    });
  });

  // ---- Roster search --------------------------------------------------------
  var rs = document.getElementById("roster-search");
  if (rs) {
    rs.addEventListener("input", function () {
      var q = rs.value.trim().toUpperCase();
      document.querySelectorAll("#roster-table tbody tr").forEach(function (tr) {
        tr.style.display = tr.textContent.toUpperCase().indexOf(q) >= 0 ? "" : "none";
      });
    });
  }

  // ---- Log filters (visual only) -------------------------------------------
  document.querySelectorAll(".rail input[type=checkbox]").forEach(function (c) {
    c.addEventListener("change", function () {
      // Visual side-effect — pulse the table briefly
      var t = document.querySelector("table.grid");
      if (!t) return;
      t.style.transition = "opacity 0.2s";
      t.style.opacity = "0.55";
      setTimeout(function () { t.style.opacity = "1"; }, 220);
    });
  });
})();
