/* ===========================================================
   Three Rivers CCU — small enhancements
   Vanilla JS only. Used for visible interactions.
   =========================================================== */

(function () {
  'use strict';

  /* ---------------- COUNTDOWN ---------------- */
  function updateCountdown() {
    const root = document.querySelector('[data-countdown]');
    if (!root) return;
    const target = new Date(root.getAttribute('data-countdown'));
    const now = new Date();
    let diff = Math.max(0, target - now);
    const d = Math.floor(diff / 86400000); diff -= d * 86400000;
    const h = Math.floor(diff / 3600000);  diff -= h * 3600000;
    const m = Math.floor(diff / 60000);    diff -= m * 60000;
    const s = Math.floor(diff / 1000);
    const set = (sel, v) => {
      const el = root.querySelector(sel);
      if (el) el.textContent = String(v).padStart(2, '0');
    };
    set('[data-cd-days]', d);
    set('[data-cd-hours]', h);
    set('[data-cd-mins]', m);
    set('[data-cd-secs]', s);
  }
  if (document.querySelector('[data-countdown]')) {
    updateCountdown();
    setInterval(updateCountdown, 1000);
  }

  /* ---------------- TABS ---------------- */
  document.querySelectorAll('[data-tablist]').forEach(group => {
    const buttons = group.querySelectorAll('[data-tab]');
    buttons.forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-tab');
        buttons.forEach(b => b.classList.toggle('active', b === btn));
        document.querySelectorAll('[data-tabpanel]').forEach(p => {
          p.style.display = p.getAttribute('data-tabpanel') === id ? '' : 'none';
        });
      });
    });
  });

  /* ---------------- CALCULATOR CARDS ---------------- */
  const calcCards = document.querySelectorAll('.calc-card[data-calc]');
  calcCards.forEach(card => {
    card.addEventListener('click', () => {
      const id = card.getAttribute('data-calc');
      const panel = document.querySelector(`.calc-panel[data-panel="${id}"]`);
      if (!panel) return;
      const isOpen = panel.classList.contains('open');
      document.querySelectorAll('.calc-panel.open').forEach(p => p.classList.remove('open'));
      document.querySelectorAll('.calc-card.active').forEach(c => c.classList.remove('active'));
      if (!isOpen) {
        panel.classList.add('open');
        card.classList.add('active');
        panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    });
  });

  const fmtMoney = n => '$' + (Number(n)||0).toLocaleString('en-US', {
    minimumFractionDigits: 2, maximumFractionDigits: 2
  });

  function calcMonthlyPI(principal, annualRate, years) {
    const r = annualRate / 100 / 12;
    const n = years * 12;
    if (!principal || !n) return 0;
    if (r === 0) return principal / n;
    return principal * r * Math.pow(1 + r, n) / (Math.pow(1 + r, n) - 1);
  }

  // Mortgage
  const mortForm = document.getElementById('calc-mortgage-form');
  if (mortForm) {
    const update = () => {
      const p   = +mortForm.principal.value;
      const r   = +mortForm.rate.value;
      const y   = +mortForm.term.value;
      const tax = +mortForm.taxes.value || 0;
      const ins = +mortForm.insurance.value || 0;
      const pmi = +mortForm.pmi.value || 0;
      const pi  = calcMonthlyPI(p, r, y);
      const total = pi + tax/12 + ins/12 + pmi;
      document.getElementById('mort-out').textContent  = fmtMoney(total);
      document.getElementById('mort-pi').textContent   = fmtMoney(pi);
      document.getElementById('mort-tax').textContent  = fmtMoney(tax/12);
      document.getElementById('mort-ins').textContent  = fmtMoney(ins/12);
      document.getElementById('mort-pmi').textContent  = fmtMoney(pmi);
    };
    mortForm.addEventListener('input', update);
    update();
  }

  // Auto
  const autoForm = document.getElementById('calc-auto-form');
  if (autoForm) {
    const update = () => {
      const p = +autoForm.principal.value;
      const r = +autoForm.rate.value;
      const y = +autoForm.term.value;
      const old = +autoForm.oldRate.value;
      const pay = calcMonthlyPI(p, r, y);
      const oldPay = calcMonthlyPI(p, old, y);
      const savings = (oldPay - pay) * (y * 12);
      document.getElementById('auto-out').textContent = fmtMoney(pay);
      document.getElementById('auto-total').textContent = fmtMoney(pay * y * 12);
      document.getElementById('auto-savings').textContent = fmtMoney(Math.max(0, savings));
    };
    autoForm.addEventListener('input', update);
    update();
  }

  // Debt consolidation
  const debtForm = document.getElementById('calc-debt-form');
  if (debtForm) {
    const update = () => {
      const a = +debtForm.amount.value;
      const r = +debtForm.rate.value;
      const y = +debtForm.term.value;
      const curMonthly = +debtForm.currentMonthly.value;
      const pay = calcMonthlyPI(a, r, y);
      document.getElementById('debt-out').textContent = fmtMoney(pay);
      document.getElementById('debt-save').textContent = fmtMoney(Math.max(0, curMonthly - pay));
      document.getElementById('debt-total').textContent = fmtMoney(pay * y * 12);
    };
    debtForm.addEventListener('input', update);
    update();
  }

  // Savings projector
  const savForm = document.getElementById('calc-savings-form');
  if (savForm) {
    const update = () => {
      const goal = +savForm.goal.value;
      const have = +savForm.start.value || 0;
      const monthly = +savForm.monthly.value;
      const apy = +savForm.apy.value;
      const r = apy/100/12;
      // months to reach goal
      let months = 0;
      let bal = have;
      while (bal < goal && months < 600) {
        bal = bal * (1+r) + monthly;
        months++;
      }
      const years = (months/12).toFixed(1);
      document.getElementById('sav-out').textContent = months >= 600 ? '60+ years' : `${months} months`;
      document.getElementById('sav-years').textContent = `${years} years`;
      document.getElementById('sav-end').textContent = fmtMoney(bal);
    };
    savForm.addEventListener('input', update);
    update();
  }

  // HELOC
  const helForm = document.getElementById('calc-heloc-form');
  if (helForm) {
    const update = () => {
      const home = +helForm.value.value;
      const owed = +helForm.balance.value;
      const ltv = +helForm.ltv.value;
      const rate = +helForm.rate.value;
      const limit = Math.max(0, home * (ltv/100) - owed);
      const interestOnly = (limit * rate / 100) / 12;
      document.getElementById('hel-out').textContent = fmtMoney(limit);
      document.getElementById('hel-interest').textContent = fmtMoney(interestOnly);
    };
    helForm.addEventListener('input', update);
    update();
  }

  // Amortization (first 12 months preview)
  const amForm = document.getElementById('calc-am-form');
  if (amForm) {
    const update = () => {
      const p = +amForm.principal.value;
      const r = +amForm.rate.value / 100 / 12;
      const y = +amForm.term.value;
      const pay = calcMonthlyPI(p, +amForm.rate.value, y);
      let bal = p;
      const tbody = document.getElementById('am-rows');
      tbody.innerHTML = '';
      const months = Math.min(12, y * 12);
      let totalI = 0, totalP = 0;
      for (let i = 1; i <= months; i++) {
        const interest = bal * r;
        const principal = pay - interest;
        bal -= principal;
        totalI += interest; totalP += principal;
        tbody.insertAdjacentHTML('beforeend',
          `<tr><td>${i}</td>
               <td>${fmtMoney(pay)}</td>
               <td>${fmtMoney(principal)}</td>
               <td>${fmtMoney(interest)}</td>
               <td>${fmtMoney(Math.max(0,bal))}</td></tr>`);
      }
      document.getElementById('am-summary').textContent =
        `First year: ${fmtMoney(totalP)} principal, ${fmtMoney(totalI)} interest.`;
    };
    amForm.addEventListener('input', update);
    update();
  }

  /* ---------------- PRINT-TO-PDF ---------------- */
  document.querySelectorAll('[data-print]').forEach(btn => {
    btn.addEventListener('click', () => window.print());
  });

  /* ---------------- OUTLINE RAIL SCROLLSPY ---------------- */
  const rail = document.querySelector('.outline-rail');
  if (rail) {
    const links = rail.querySelectorAll('a[href^="#"]');
    const idMap = new Map();
    links.forEach(a => {
      const id = a.getAttribute('href').slice(1);
      const target = document.getElementById(id);
      if (target) idMap.set(target, a);
    });
    if ('IntersectionObserver' in window && idMap.size) {
      const io = new IntersectionObserver(entries => {
        entries.forEach(en => {
          if (en.isIntersecting) {
            links.forEach(a => a.classList.remove('active'));
            const link = idMap.get(en.target);
            if (link) link.classList.add('active');
          }
        });
      }, { rootMargin: '-40% 0px -55% 0px' });
      idMap.forEach((_, t) => io.observe(t));
    }
  }

  /* ---------------- FRAUD-ALERT TOGGLE ---------------- */
  document.querySelectorAll('[data-fraud-toggle]').forEach(t => {
    t.addEventListener('change', () => {
      const note = t.closest('label').querySelector('.fraud-status');
      if (note) note.textContent = t.checked ? 'Subscribed' : 'Not subscribed';
    });
  });

  /* ---------------- MARGINALIA TAP TO EXPAND (MOBILE) ---------------- */
  document.querySelectorAll('[data-margin]').forEach(span => {
    const note = span.getAttribute('data-margin');
    span.addEventListener('click', () => {
      let pop = span.nextElementSibling;
      if (pop && pop.classList.contains('marg-pop')) {
        pop.remove();
      } else {
        const div = document.createElement('div');
        div.className = 'marginalia marg-pop';
        div.textContent = note;
        span.insertAdjacentElement('afterend', div);
      }
    });
  });

  /* ---------------- ARCHIVE CAROUSEL CONTROLS ---------------- */
  document.querySelectorAll('[data-carousel]').forEach(c => {
    const prev = c.querySelector('[data-carousel-prev]');
    const next = c.querySelector('[data-carousel-next]');
    const track = c.querySelector('.archive-carousel');
    if (!track) return;
    const step = () => track.clientWidth * 0.7;
    if (prev) prev.addEventListener('click', () => track.scrollBy({ left: -step(), behavior: 'smooth' }));
    if (next) next.addEventListener('click', () => track.scrollBy({ left: step(),  behavior: 'smooth' }));
  });

  /* ---------------- FORM FRIENDLY SUBMIT ---------------- */
  document.querySelectorAll('form[data-noop]').forEach(f => {
    f.addEventListener('submit', e => {
      e.preventDefault();
      const note = f.querySelector('.form-note');
      if (note) {
        note.textContent = f.getAttribute('data-noop');
        note.style.display = 'block';
      }
    });
  });

  /* ---------------- MAP PIN TOOLTIP ---------------- */
  document.querySelectorAll('.map-pin').forEach(pin => {
    pin.addEventListener('mouseenter', () => pin.classList.add('hover'));
    pin.addEventListener('mouseleave', () => pin.classList.remove('hover'));
  });

})();
