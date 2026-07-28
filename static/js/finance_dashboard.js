document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-finance-period-form]').forEach((form) => {
    const select = form.querySelector('[data-finance-period-select]');
    const customFields = form.querySelectorAll('[data-finance-custom-date]');
    if (!select || !customFields.length) return;

    const syncCustomFields = () => {
      const showCustom = select.value === 'custom';
      customFields.forEach((field) => {
        field.style.display = showCustom ? '' : 'none';
      });
    };

    select.addEventListener('change', syncCustomFields);
    syncCustomFields();
  });
});
