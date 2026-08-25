(() => {
  const add = () => {
    const nav=document.querySelector('.ds-dashboard-tabs,.shell > nav.tabs,nav.tabs');
    if(!nav || nav.querySelector('[data-trading-readiness-tab]')) return false;
    const link=document.createElement('a');
    link.href='/trading-readiness';
    link.textContent='TRADING READINESS';
    link.className='tab'+(window.location.pathname==='/trading-readiness'?' active':'');
    link.dataset.tradingReadinessTab='true';
    nav.appendChild(link);
    return true;
  };
  if(add()) return;
  const observer=new MutationObserver(()=>{if(add())observer.disconnect()});
  observer.observe(document.documentElement,{childList:true,subtree:true});
  window.setTimeout(()=>observer.disconnect(),10000);
})();
