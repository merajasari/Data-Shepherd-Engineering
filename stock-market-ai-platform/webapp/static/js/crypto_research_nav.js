(() => {
  const main = document.querySelector('nav.tabs');
  if (!main || document.getElementById('crypto-section-nav')) return;
  const nav = document.createElement('nav');
  nav.id = 'crypto-section-nav';
  nav.className = 'tabs';
  nav.setAttribute('aria-label', 'Crypto sections');
  nav.innerHTML = '<a class="tab active" href="/crypto">CRYPTO OVERVIEW</a><a class="tab" href="/crypto/model-research">CRYPTO MODEL RESEARCH</a>';
  main.insertAdjacentElement('afterend', nav);
})();
