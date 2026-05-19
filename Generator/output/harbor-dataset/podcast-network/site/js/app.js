/* Frequency Room — small interactions */
(function () {
  // Persisted "now playing" header text
  const NOW_PLAYING = {
    show: 'The Late Signal',
    episode: 'S2 · E07 — The Quiet Hour',
    runtime: '01:14:22'
  };

  // Init mini-player title
  const mpTitle = document.querySelector('.mini-player .mp-title');
  if (mpTitle) {
    mpTitle.innerHTML = `<strong>NOW PLAYING</strong> · ${NOW_PLAYING.show} — ${NOW_PLAYING.episode}`;
  }

  // Play/pause toggle (purely visual)
  const playBtn = document.querySelector('.mp-btn.play');
  if (playBtn) {
    let playing = true;
    playBtn.addEventListener('click', () => {
      playing = !playing;
      playBtn.textContent = playing ? '❚❚' : '►';
      document.querySelectorAll('.mp-wave span').forEach(s => {
        s.style.animationPlayState = playing ? 'running' : 'paused';
      });
      document.querySelectorAll('.mp-art, .ip-art').forEach(s => {
        s.style.animationPlayState = playing ? 'running' : 'paused';
      });
    });
  }

  // Filter chip toggle
  document.querySelectorAll('.filter-bar').forEach(bar => {
    bar.querySelectorAll('.filter-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        // group toggle: only one active per bar segment
        const group = chip.dataset.group;
        if (group) {
          bar.querySelectorAll(`.filter-chip[data-group="${group}"]`).forEach(c => c.classList.remove('active'));
        }
        chip.classList.toggle('active');
      });
    });
  });

  // Season tabs
  document.querySelectorAll('.season-tabs').forEach(group => {
    group.querySelectorAll('.season-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        group.querySelectorAll('.season-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
      });
    });
  });

  // Tier select on partner form
  document.querySelectorAll('.tier-select label').forEach(lbl => {
    lbl.addEventListener('click', () => {
      const group = lbl.parentElement;
      group.querySelectorAll('label').forEach(l => l.classList.remove('active'));
      lbl.classList.add('active');
    });
  });

  // Random episode lucky-dip
  const luckyBtn = document.getElementById('lucky-btn');
  if (luckyBtn) {
    const picks = [
      'The Late Signal · S2E03 — "Ambient Highways"',
      'Off-Air Annex · S4E11 — "The Last Switchboard Operator"',
      'Crate of Forgers · S1E07 — "Mailing List for Mysteries"',
      'Static Hum · S3E14 — "Two Drummers in a Pickup"',
      'Skeleton Hours · S2E02 — "When the Dial Stops Listening"'
    ];
    const out = document.getElementById('lucky-result');
    luckyBtn.addEventListener('click', () => {
      const pick = picks[Math.floor(Math.random() * picks.length)];
      if (out) out.textContent = pick;
    });
  }

  // Calendar pin hover detail
  document.querySelectorAll('.cal-cell .pin').forEach(pin => {
    pin.addEventListener('mouseenter', () => {
      const detail = pin.getAttribute('data-detail');
      const cell = pin.parentElement;
      let tip = cell.querySelector('.tip');
      if (!detail) return;
      if (!tip) {
        tip = document.createElement('div');
        tip.className = 'tip';
        tip.textContent = detail;
        Object.assign(tip.style, {
          position: 'absolute', left: '14px', top: '-8px',
          background: '#0a0510', border: '1px solid var(--magenta)',
          color: 'var(--magenta)', padding: '6px 10px',
          fontFamily: 'var(--font-mono)', fontSize: '10px',
          letterSpacing: '0.18em', textTransform: 'uppercase',
          borderRadius: '4px', zIndex: '5',
          transform: 'translateY(-100%)'
        });
        cell.appendChild(tip);
      }
    });
    pin.addEventListener('mouseleave', () => {
      const tip = pin.parentElement.querySelector('.tip');
      if (tip) tip.remove();
    });
  });

  // Animate counters when in view
  const counters = document.querySelectorAll('.counter .num[data-target]');
  if (counters.length) {
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (!e.isIntersecting) return;
        const el = e.target;
        const target = parseFloat(el.dataset.target);
        const suffix = el.dataset.suffix || '';
        const decimals = parseInt(el.dataset.decimals || '0', 10);
        const dur = 1400;
        const start = performance.now();
        function tick(now) {
          const t = Math.min(1, (now - start) / dur);
          const ease = 1 - Math.pow(1 - t, 3);
          const val = target * ease;
          el.textContent = val.toFixed(decimals).replace(/\B(?=(\d{3})+(?!\d))/g, ',') + suffix;
          if (t < 1) requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
        io.unobserve(el);
      });
    }, { threshold: 0.4 });
    counters.forEach(c => io.observe(c));
  }

  // Archive search live filter (front-end only)
  const searchInput = document.getElementById('archive-search');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      const q = searchInput.value.toLowerCase();
      document.querySelectorAll('.search-row').forEach(row => {
        const txt = row.textContent.toLowerCase();
        row.style.display = txt.includes(q) ? '' : 'none';
      });
    });
  }

  // Typed-effect mission statement (optional)
  const typed = document.querySelector('.mission .typed');
  if (typed && typed.dataset.text) {
    const text = typed.dataset.text;
    typed.textContent = '';
    let i = 0;
    function step() {
      if (i <= text.length) {
        typed.textContent = text.slice(0, i);
        i++;
        setTimeout(step, 18);
      }
    }
    step();
  }
})();
