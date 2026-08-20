(() => {
  const sections = Array.from(document.querySelectorAll('section.card'));

  // The full 100-stock V8 ranking board is no longer part of the Model Research UI.
  // Match both the current V8 label and the legacy V5 label in case another script
  // upgrades the label after initial render.
  const rankingBoard = sections.find(section => {
    const label = section.querySelector('.label')?.textContent?.trim() || '';
    const heading = section.querySelector('h2,h3')?.textContent?.trim() || '';
    return /100[- ]STOCK.*(?:V8|V5).*RANKING BOARD/i.test(`${label} ${heading}`) ||
           /(?:V8|V5).*100[- ]STOCK.*RANKING BOARD/i.test(`${label} ${heading}`);
  });
  if (rankingBoard) rankingBoard.remove();

  const remainingSections = Array.from(document.querySelectorAll('section.card'));
  const recentMarketData = remainingSections.find(section =>
    section.querySelector('.label')?.textContent?.trim() === 'RECENT MARKET DATA'
  );
  const v5Leaders = remainingSections.find(section =>
    section.querySelector('.label')?.textContent?.trim() === 'V5 LEADERS'
  );

  if (recentMarketData && v5Leaders) {
    v5Leaders.parentNode.insertBefore(recentMarketData, v5Leaders);
  }
})();
