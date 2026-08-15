(() => {
  const makeButton = (className) => {
    const link = document.createElement('a');
    link.href = '/signup';
    link.textContent = 'SIGN UP';
    link.className = className;
    link.style.textDecoration = 'none';
    return link;
  };

  const landingActions = document.querySelector('.landing-header-actions');
  if (landingActions && !landingActions.querySelector('a[href="/signup"]')) {
    const button = makeButton('landing-login-button');
    button.style.borderColor = '#36d8ff';
    button.style.color = '#36d8ff';
    button.style.background = 'rgba(54,216,255,.08)';
    landingActions.insertBefore(button, landingActions.firstChild);
  }

  const dashboardActions = document.querySelector('.actions');
  if (dashboardActions && !dashboardActions.querySelector('a[href="/signup"]')) {
    const button = makeButton('pill');
    button.style.color = '#36d8ff';
    button.style.borderColor = 'rgba(54,216,255,.45)';
    button.style.background = 'rgba(54,216,255,.08)';
    dashboardActions.insertBefore(button, dashboardActions.firstChild);
  }

  const shell = document.querySelector('.shell');
  const header = shell && shell.querySelector('header');
  const existingTabs = shell && shell.querySelector('.tabs');
  if (shell && header && !existingTabs && ['/dashboard', '/crypto'].includes(window.location.pathname)) {
    const style = document.createElement('style');
    style.textContent = `
      .ds-dashboard-tabs{display:flex;gap:10px;margin-bottom:22px;flex-wrap:wrap}
      .ds-dashboard-tab{padding:12px 18px;border:1px solid #244261;border-radius:999px;text-decoration:none;color:#91a6c2;font-weight:900;letter-spacing:.04em;background:rgba(13,28,49,.85)}
      .ds-dashboard-tab.active{color:#06151d;background:linear-gradient(90deg,#36d8ff,#39e3a1);border-color:transparent}
      .ds-dashboard-tab:hover{border-color:rgba(54,216,255,.55);color:#f2f6ff}
    `;
    document.head.appendChild(style);

    const nav = document.createElement('nav');
    nav.className = 'ds-dashboard-tabs';
    nav.setAttribute('aria-label', 'Dashboard sections');
    nav.innerHTML = `
      <a class="ds-dashboard-tab ${window.location.pathname === '/dashboard' ? 'active' : ''}" href="/dashboard">STOCKS</a>
      <a class="ds-dashboard-tab ${window.location.pathname === '/crypto' ? 'active' : ''}" href="/crypto">CRYPTO</a>
    `;
    header.insertAdjacentElement('afterend', nav);
  }
})();
