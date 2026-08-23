(() => {
  function anchor() {
    return document.getElementById('v8-launch-readiness-card') ||
      [...document.querySelectorAll('section,article,div')].find(el =>
        /V8 FORWARD \/ HOLDOUT OPERATIONS/i.test(el.textContent || '')
      ) ||
      document.getElementById('v8-holdout-monitor');
  }

  function render() {
    const existing = document.getElementById('v10-confirmation-card');
    const anchorElement = anchor();
    if (!anchorElement && !existing) return false;
    const card = existing || document.createElement('section');
    card.id = 'v10-confirmation-card';
    card.className = 'v4-card';
    card.style.marginTop = '18px';
    card.innerHTML = `
      <div style="padding:22px">
        <div class="label">ORIGINAL V10 RESEARCH DISPOSITION</div>
        <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:18px;flex-wrap:wrap;margin-top:6px">
          <div>
            <h2 style="margin:0 0 7px">Original Challenger — Rejected</h2>
            <p style="margin:0;opacity:.74;max-width:850px">The original V10 and Cycle 2 remain reconstructed development evidence only. They did not qualify for the November holdout and have no production or brokerage authority.</p>
          </div>
          <div style="font-size:20px;font-weight:900;color:#ff8d8d">DO NOT FREEZE</div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin-top:18px">
          <div class="metric"><span>ORIGINAL V10</span><strong>12 / 13 GATES</strong></div>
          <div class="metric"><span>V10 CYCLE 2</span><strong>12 / 13 GATES</strong></div>
          <div class="metric"><span>FAILED GATE</span><strong>POSITIVE-REGIME NONINFERIORITY</strong></div>
          <div class="metric"><span>ORIGINAL CANDIDATE FROZEN</span><strong>NO</strong></div>
          <div class="metric"><span>NOVEMBER HOLDOUT</span><strong>NOT ACTIVATED</strong></div>
          <div class="metric"><span>ORDERS</span><strong>DISABLED</strong></div>
        </div>
        <div style="margin-top:16px;padding:14px;border:1px solid rgba(239,197,107,.24);border-radius:12px;background:rgba(239,197,107,.06);font-size:13px;line-height:1.55;color:var(--muted)">
          V10 improved negative-market regimes but failed the predeclared positive-regime relative-noninferiority gate. The one-session Cycle-2 exit buffer failed the same gate. The gate was not weakened after results were observed.
        </div>
        <div style="margin-top:12px;font-size:13px;opacity:.75">
          <strong style="color:var(--green)">Frozen V8 remains the current forward model.</strong>
          The separately preregistered Cycle 3 candidate passed 13/13 development gates and is frozen for a fresh Jan 4, 2027 holdout; it has no forward results yet. Historical V10 curves remain reconstructed development evidence.
        </div>
      </div>`;
    if (!existing) anchorElement.insertAdjacentElement('afterend', card);
    return true;
  }

  let attempts = 0;
  const boot = () => {
    if (!render() && attempts++ < 30) setTimeout(boot, 400);
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, {once:true});
  } else {
    boot();
  }
})();
