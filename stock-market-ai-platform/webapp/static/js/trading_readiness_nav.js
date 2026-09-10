(() => {
  const add = () => {
    const nav=document.querySelector('.ds-dashboard-tabs,.shell > nav.tabs,nav.tabs');
    if(!nav) return false;

    const existing=nav.querySelector('a[href="/trading-readiness"],a[href$="/trading-readiness"],[data-trading-readiness-tab]');
    if(existing){
      existing.dataset.tradingReadinessTab='true';
      if(window.location.pathname==='/trading-readiness') existing.classList.add('active');
      return true;
    }

    const link=document.createElement('a');
    link.href='/trading-readiness';
    link.textContent='TRADING READINESS';
    const dashboardTabs=nav.classList.contains('ds-dashboard-tabs');
    link.className=(dashboardTabs?'ds-dashboard-tab':'tab')+(window.location.pathname==='/trading-readiness'?' active':'');
    link.dataset.tradingReadinessTab='true';
    nav.appendChild(link);
    return true;
  };
  if(add()) return;
  const observer=new MutationObserver(()=>{if(add())observer.disconnect()});
  observer.observe(document.documentElement,{childList:true,subtree:true});
  window.setTimeout(()=>observer.disconnect(),10000);
})();
