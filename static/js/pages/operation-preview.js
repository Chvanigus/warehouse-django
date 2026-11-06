/** Показывает предварительный расчёт складской операции рядом с формой. */
(function initializeOperationPreview() {
  const form = document.querySelector('[data-operation-form]');
  if (!form || typeof BigInt !== 'function') return;

  const quantityField = form.elements.quantity;
  const priceField = form.elements.price;
  const stockField = form.elements.spares_list;
  const measureField = form.elements.measure;
  const previewQuantity = form.querySelector('[data-preview-quantity]');
  const previewPrice = form.querySelector('[data-preview-price]');
  const previewTotal = form.querySelector('[data-preview-total]');
  const previewBalance = form.querySelector('[data-preview-balance]');
  const previewAvailable = form.querySelector('[data-preview-available]');
  const editAvailability = form.querySelector('[data-preview-edit]');
  const warning = form.querySelector('[data-preview-warning]');
  const integerFormat = new Intl.NumberFormat('ru-RU');

  /** Переводит ввод с точкой или запятой в целое число сотых для точного расчёта. */
  function minorUnits(value) {
    const match = /^(-?)(\d*)(?:[.,](\d{1,2}))?$/.exec(value ?? '');
    if (!match || (!match[2] && !match[3])) return null;
    const units = BigInt(match[2] || '0') * 100n + BigInt((match[3] || '').padEnd(2, '0'));
    return match[1] ? -units : units;
  }

  /** Форматирует число сотых по русской локали и при необходимости выводит две дробные цифры. */
  function display(units, fixed = false) {
    if (units === null) return '—';
    const absolute = units < 0n ? -units : units;
    const fraction = absolute % 100n;
    const decimals = fixed || fraction ? ',' + String(fraction).padStart(2, '0') : '';
    return (units < 0n ? '−' : '') + integerFormat.format(absolute / 100n) + decimals;
  }

  /** Добавляет единицу измерения к количеству, если значение и единица заданы. */
  function displayQuantity(units, measure) {
    return units === null || !measure ? display(units) : display(units) + ' ' + measure;
  }

  /** Обновляет сумму, доступное количество и подсказку о превышении остатка. */
  function updatePreview() {
    const stock = stockField?.selectedOptions[0]?.dataset;
    let measure = stock?.measure || '';
    if (measureField?.value) measure = measureField.selectedOptions[0].textContent;
    const quantity = minorUnits(quantityField.value);
    const price = minorUnits(priceField?.value ?? stock?.price);
    const total = quantity !== null && quantity > 0n && price !== null && price >= 0n
      ? (quantity * price + 50n) / 100n
      : null;

    previewQuantity.textContent = displayQuantity(quantity, measure);
    previewPrice.textContent = display(price, true);
    previewTotal.textContent = display(total, true);

    if (stockField) {
      const balance = minorUnits(stock?.balance);
      const available = minorUnits(stock?.available);
      previewBalance.textContent = displayQuantity(balance, measure);
      previewAvailable.textContent = displayQuantity(available, measure);
      editAvailability.hidden = available === balance;
      warning.hidden = available === null || quantity === null || quantity <= 0n || quantity <= available;
    }
  }

  form.addEventListener('input', updatePreview);
  form.addEventListener('change', updatePreview);
  // При выборе значения Select2 отправляет событие через jQuery.
  if (window.jQuery) window.jQuery(form).on('change', 'select', updatePreview);
  updatePreview();
})();
