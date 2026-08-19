// Legacy loader retained only because app.py still injects this filename.
// It performs no V5 network/model work. It only removes stale V5 wording that
// may be inserted later by older presentation helpers.
(() => {
  const scrub = () => {
    document.querySelectorAll('.primary-stock-prompt span').forEach(el => {
      el.textContent = el.textContent.replace('V5 rank', 'V8 rank');
    });
  };
  scrub();
  const observer = new MutationObserver(scrub);
  observer.observe(document.documentElement, {childList:true, subtree:true});
  window.setTimeout(() => observer.disconnect(), 5000);
})();
