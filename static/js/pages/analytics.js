/** Показывает суммы выбранного месяца графика и отмечает его как активный. */
(function initializeTrendSelection() {
  const trend = document.querySelector('.analytics-trend');
  const output = trend?.querySelector('[data-chart-selection]');
  if (!output) return;

  /** Обновляет выбранный месяц после нажатия мышью, касанием или с клавиатуры. */
  function selectMonth(event) {
    const month = event.target.closest('[data-chart-value]');
    if (!month) return;
    trend.querySelector('[data-chart-value][aria-pressed="true"]')?.setAttribute('aria-pressed', 'false');
    month.setAttribute('aria-pressed', 'true');
    output.textContent = month.getAttribute('aria-label');
  }

  trend.addEventListener('click', selectMonth);
})();
