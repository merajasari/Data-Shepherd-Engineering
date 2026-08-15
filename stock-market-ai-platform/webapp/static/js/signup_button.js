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
})();
