(() => {
  const sections = Array.from(document.querySelectorAll('section.card'));

  const recentMarketData = sections.find(section =>
    section.querySelector('.label')?.textContent?.trim() === 'RECENT MARKET DATA'
  );

  const v5Leaders = sections.find(section =>
    section.querySelector('.label')?.textContent?.trim() === 'V5 LEADERS'
  );

  if (!recentMarketData || !v5Leaders || !v5Leaders.parentNode) {
    return;
  }

  v5Leaders.parentNode.insertBefore(recentMarketData, v5Leaders);
})();
