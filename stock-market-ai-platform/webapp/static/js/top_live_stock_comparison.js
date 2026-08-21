(()=>{
  // Performance shim: the former implementation issued one /api/prices request per
  // stock, and each request could trigger a Tiingo REST call. That could occupy all
  // Gunicorn workers and make the entire Live Stock Viewer appear hung.
  // The replacement chart hydrates from one local-only bulk endpoint instead.
  if(location.pathname!=='/dashboard'||new URLSearchParams(location.search).get('view')!=='live')return;
  if(document.querySelector('script[data-ds-fast-live-comparison]'))return;
  const s=document.createElement('script');
  s.src='/static/js/top_live_stock_comparison_fast.js';
  s.defer=true;
  s.dataset.dsFastLiveComparison='1';
  s.addEventListener('load',()=>{
    if(document.querySelector('script[data-ds-top-live-selection]'))return;
    const selection=document.createElement('script');
    selection.src='/static/js/top_live_stock_selection.js';
    selection.defer=true;
    selection.dataset.dsTopLiveSelection='1';
    document.head.appendChild(selection);
  });
  document.head.appendChild(s);
})();
