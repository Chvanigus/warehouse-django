/** Связывает строки накладной или ведомости с управляющими полями набора форм Django. */
(function initializeLineEditor() {
  const form = document.querySelector('[data-line-editor]');
  if (!form) return;
  const rows = form.querySelector('[data-form-rows]');
  const template = form.querySelector('[data-empty-line]');
  const total = form.elements['form-TOTAL_FORMS'];
  const max = Number(form.elements['form-MAX_NUM_FORMS'].value);
  const add = form.querySelector('[data-add-line]');

  /** Помечает строку как удалённую и исключает остальные поля строки из отправки. */
  function setDeleted(row, deleted) {
    const flag = row.querySelector('input[name$="-DELETE"]');
    for (const control of row.querySelectorAll('input, select')) {
      if (control !== flag) control.disabled = deleted;
    }
    flag.checked = deleted;
    row.hidden = deleted;
  }

  /** Перенумеровывает видимые строки и ограничивает добавление по лимиту сервера. */
  function updateNumbers() {
    const visible = rows.querySelectorAll('[data-form-row]:not([hidden])');
    for (const [index, row] of visible.entries()) {
      row.querySelector('[data-line-number]').textContent = index + 1;
    }
    add.disabled = visible.length >= max;
  }

  /** Переиспользует удалённую строку или добавляет новую с очередным индексом. */
  function addLine() {
    let row = rows.querySelector('[data-form-row][hidden]');
    if (row) {
      for (const control of row.querySelectorAll('select, input')) {
        if (control.type === 'checkbox') control.checked = false;
        else control.value = '';
      }
      for (const error of row.querySelectorAll('[data-field-errors]')) error.remove();
      setDeleted(row, false);
    } else if (Number(total.value) < max) {
      const fragment = document.createElement('template');
      fragment.innerHTML = template.innerHTML.replaceAll('__prefix__', total.value);
      row = fragment.content.firstElementChild;
      rows.append(fragment.content);
      total.value = Number(total.value) + 1;
    }
    updateNumbers();
    row?.querySelector('select')?.focus();
  }

  /** Обрабатывает удаление строки общей подпиской для текущих и новых кнопок. */
  function removeLine(event) {
    const remove = event.target.closest('[data-remove-line]');
    if (!remove) return;
    const row = remove.closest('[data-form-row]');
    setDeleted(row, true);
    updateNumbers();
    add.focus();
  }

  add.addEventListener('click', addLine);
  rows.addEventListener('click', removeLine);
  for (const row of rows.querySelectorAll('[data-form-row][hidden]')) setDeleted(row, true);
  updateNumbers();
})();
