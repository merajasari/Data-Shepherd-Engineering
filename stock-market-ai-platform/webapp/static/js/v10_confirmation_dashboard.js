(() => {
  const CURRENT_COMPARISON_NOTE =
    'Each model is shown as its own historical strategy curve on the same hypothetical $100,000 basis. ' +
    'Live paper-account balances are intentionally excluded. Model curves begin only when their scientifically eligible evidence begins; no history is backfilled before eligibility. ' +
    'Frozen V8 and V10 Cycle 3 curves are development-era historical reconstructions only. Genuine V8 forward evidence beginning 2026-09-01 remains separate. ' +
    'The V10 Cycle 3 accelerated paper-forward lane beginning 2026-09-08 and the independent fresh holdout beginning 2027-01-04 are separate prospective journals and are never added to this reconstructed chart.';

  function correctLegacyComparisonCopy() {
    if (!document.body) return;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const text = node.nodeValue || '';
      if (
        text.includes('formal holdout begins 2026-11-02') ||
        text.includes('V10 confirmation/future holdout evidence')
      ) {
        node.nodeValue = CURRENT_COMPARISON_NOTE;
      }
    }
  }

  function anchor() {
    return document.getElementById('v8-launch-readiness-card') ||
      [...document.querySelectorAll('section,article,div')].find(el =>
        /V8 FORWARD \/ HOLDOUT OPERATIONS/i.test(el.textContent || '')
      ) ||
      document.getElementById('v8-holdout-monitor');
  }

  function render() {
    correctLegacyComparisonCopy();
    const existing = document.getElementById('v10-confirmation-card');
    const anchorElement = anchor();
    if (!anchorElement && !existing) return false;
    const card = existing || document.createElement('section');
    card.id = 'v10-confirmation-card';
    card.className = 'v4-card';
    card.style.marginTop = '18px';
    card.innerHTML = `
      <div style="padding:22px">
        <details>
          <summary style="cursor:pointer;list-style-position:outside">
            <span class="label">HISTORICAL V10 RESEARCH DISPOSITION</span>
            <strong style="display:block;margin-top:6px;font-size:17px">Original V10 and Cycle 2 — rejected development candidates</strong>
            <span style="display:block;margin-top:5px;font-size:12px;color:var(--muted)">Expand for the preserved 12/13-gate disposition. This evidence is not part of the selected Cycle 3 prospective lanes.</span>
          </summary>
          <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:18px;flex-wrap:wrap;margin-top:18px">
            <p style="margin:0;opacity:.74;max-width:850px">The original V10 and Cycle 2 remain reconstructed development evidence only. They did not qualify for the November holdout and have no production or brokerage authority.</p>
            <div style="font-size:16px;font-weight:900;color:#ff8d8d">REJECTED · DO NOT FREEZE</div>
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
            <strong style="color:var(--green)">Frozen V8 remains the current champion.</strong>
            The separately selected Cycle 3 candidate passed 13/13 development gates. Its accelerated September–December evidence and independent January confirmation are displayed above as separate prospective lanes.
          </div>
        </details>
      </div>`;
    if (!existing) {
      const currentLane = document.getElementById('v10-cycle3-holdout-monitor') ||
        document.getElementById('v10-cycle3-accelerated-monitor');
      (currentLane || anchorElement).insertAdjacentElement('afterend', card);
    }
    return true;
  }

  let attempts = 0;
  const boot = () => {
    if (!render() && attempts++ < 30) setTimeout(boot, 400);
  };
  const start = () => {
    boot();
    [500, 1500, 3000].forEach(delay => setTimeout(correctLegacyComparisonCopy, delay));
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start, {once:true});
  } else {
    start();
  }
})();
