(() => {
  const IDLE_MS = 5 * 60 * 1000;
  const WARNING_MS = 30 * 1000;
  const WARNING_AT_MS = IDLE_MS - WARNING_MS;
  const PING_MIN_MS = 1000;
  let lastActivity = Date.now();
  let lastPing = 0;
  let warningTimer = null;
  let logoutTimer = null;
  let countdownTimer = null;

  const style = document.createElement('style');
  style.id = 'ds-session-timeout-style';
  style.textContent = `
    #ds-idle-overlay{position:fixed;inset:0;z-index:100000;display:none;align-items:center;justify-content:center;padding:22px;background:rgba(2,8,18,.76);backdrop-filter:blur(7px)}
    #ds-idle-overlay.open{display:flex}
    #ds-idle-dialog{width:min(460px,100%);padding:26px;border:1px solid rgba(239,197,107,.48);border-radius:20px;background:linear-gradient(145deg,#10223b,#081424);box-shadow:0 30px 90px rgba(0,0,0,.55);color:#f2f6ff}
    #ds-idle-dialog h2{margin:6px 0 10px}
    #ds-idle-countdown{font-size:2.25rem;font-weight:950;color:#efc56b;margin:16px 0}
    #ds-stay-signed-in{width:100%;padding:13px 18px;border:0;border-radius:999px;background:linear-gradient(90deg,#36d8ff,#39e3a1);color:#06151d;font-weight:950;cursor:pointer}
  `;
  document.head.appendChild(style);

  const overlay = document.createElement('div');
  overlay.id = 'ds-idle-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-labelledby', 'ds-idle-title');
  overlay.innerHTML = `
    <div id="ds-idle-dialog">
      <div style="color:#efc56b;font-size:.72rem;font-weight:900;letter-spacing:.14em">SESSION SECURITY</div>
      <h2 id="ds-idle-title">You’re about to be signed out</h2>
      <p style="color:#91a6c2;line-height:1.55">For your security, this session closes after five minutes without activity.</p>
      <div id="ds-idle-countdown" aria-live="polite">30 seconds</div>
      <button id="ds-stay-signed-in" type="button">STAY SIGNED IN</button>
    </div>`;
  document.body.appendChild(overlay);

  const ping = async force => {
    const now = Date.now();
    if (!force && now - lastPing < PING_MIN_MS) return;
    lastPing = now;
    try {
      const response = await fetch('/api/session/activity', {
        method: 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: {'Accept':'application/json'}
      });
      if (response.status === 401) window.location.assign('/?reason=inactive');
    } catch (error) {
      console.warn('[SESSION ACTIVITY]', error);
    }
  };

  const clearTimers = () => {
    window.clearTimeout(warningTimer);
    window.clearTimeout(logoutTimer);
    window.clearInterval(countdownTimer);
  };

  const logout = () => window.location.assign('/logout?reason=inactive');

  const showWarning = () => {
    overlay.classList.add('open');
    let remaining = 30;
    const node = document.getElementById('ds-idle-countdown');
    node.textContent = `${remaining} seconds`;
    document.getElementById('ds-stay-signed-in').focus();
    countdownTimer = window.setInterval(() => {
      remaining -= 1;
      node.textContent = `${Math.max(0, remaining)} second${remaining === 1 ? '' : 's'}`;
    }, 1000);
    logoutTimer = window.setTimeout(logout, WARNING_MS);
  };

  const schedule = () => {
    clearTimers();
    overlay.classList.remove('open');
    const elapsed = Date.now() - lastActivity;
    warningTimer = window.setTimeout(showWarning, Math.max(0, WARNING_AT_MS - elapsed));
  };

  const recordActivity = () => {
    if (overlay.classList.contains('open')) return;
    lastActivity = Date.now();
    schedule();
    ping(false);
  };

  ['pointerdown','keydown','touchstart','scroll'].forEach(eventName =>
    window.addEventListener(eventName, recordActivity, {passive:true})
  );

  document.getElementById('ds-stay-signed-in').addEventListener('click', () => {
    lastActivity = Date.now();
    schedule();
    ping(true);
  });

  ping(true);
  schedule();
})();
