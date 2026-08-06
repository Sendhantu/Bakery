(() => {
  const storageKey = 'sweetcrumbs:demand-insights:acknowledged';

  const readAcknowledged = () => {
    try {
      return new Set(JSON.parse(localStorage.getItem(storageKey) || '[]'));
    } catch (error) {
      return new Set();
    }
  };

  const writeAcknowledged = (ids) => {
    localStorage.setItem(storageKey, JSON.stringify(Array.from(ids)));
  };

  const updateCount = () => {
    const cards = Array.from(document.querySelectorAll('[data-demand-advisory]'))
      .filter((card) => !card.classList.contains('hidden'));
    const badge = document.querySelector('[data-demand-count]');
    const empty = document.querySelector('[data-demand-empty]');
    if (badge) badge.textContent = cards.length;
    if (empty) empty.classList.toggle('hidden', cards.length > 0);
  };

  const initDemandInsights = (root = document) => {
    const acknowledged = readAcknowledged();
    const cards = root.querySelectorAll?.('[data-demand-advisory]') || [];

    cards.forEach((card) => {
      const advisoryId = card.dataset.advisoryId;
      if (acknowledged.has(advisoryId)) {
        card.classList.add('hidden');
        return;
      }

      card.classList.add('demand-advisory-highlight');
      window.setTimeout(() => card.classList.remove('demand-advisory-highlight'), 1800);

      const button = card.querySelector('[data-demand-ack]');
      if (!button) return;
      if (button.dataset.demandAckBound === 'true') return;
      button.dataset.demandAckBound = 'true';
      button.addEventListener('click', () => {
        acknowledged.add(advisoryId);
        writeAcknowledged(acknowledged);
        card.classList.add('hidden');
        updateCount();
      });
    });

    updateCount();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => initDemandInsights(), { once: true });
  } else {
    initDemandInsights();
  }
  document.addEventListener('sweetcrumbs:admin-page-loaded', (event) => {
    initDemandInsights(event.detail?.root || document);
  });
})();
