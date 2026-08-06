(() => {
  const initFinanceDashboard = (root = document) => {
    root.querySelectorAll?.('[data-finance-period-form]').forEach((form) => {
      if (form.dataset.financePeriodBound === 'true') return;
      form.dataset.financePeriodBound = 'true';
      const select = form.querySelector('[data-finance-period-select]');
      const customRange = form.querySelector('[data-finance-custom-range]');
      const customFields = form.querySelectorAll('[data-finance-custom-date]');
      if (!select || (!customRange && !customFields.length)) return;

      const syncCustomFields = () => {
        const showCustom = select.value === 'custom';
        if (customRange) customRange.style.display = showCustom ? 'grid' : 'none';
        customFields.forEach((field) => {
          field.style.display = showCustom ? '' : 'none';
        });
      };

      select.addEventListener('change', syncCustomFields);
      syncCustomFields();
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => initFinanceDashboard(), { once: true });
  } else {
    initFinanceDashboard();
  }
  document.addEventListener('sweetcrumbs:admin-page-loaded', (event) => {
    initFinanceDashboard(event.detail?.root || document);
  });
})();
