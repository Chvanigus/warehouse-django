(() => {
  const form = document.querySelector('[data-line-editor]');
  if (!form) return;
  const rows = form.querySelector('[data-form-rows]');
  const template = form.querySelector('[data-empty-line]');
  const total = form.elements['form-TOTAL_FORMS'];
  const max = Number(form.elements['form-MAX_NUM_FORMS'].value);
  const add = form.querySelector('[data-add-line]');

  function setDeleted(row, deleted) {
    const flag = row.querySelector('input[name$="-DELETE"]');
    for (const control of row.querySelectorAll('input, select')) {
      if (control !== flag) control.disabled = deleted;
    }
    flag.checked = deleted;
    row.hidden = deleted;
  }

  function updateNumbers() {
    const visible = rows.querySelectorAll('[data-form-row]:not([hidden])');
    visible.forEach((row, index) => {
      row.querySelector('[data-line-number]').textContent = index + 1;
    });
    add.disabled = visible.length >= max;
  }

  add.addEventListener('click', () => {
    let row = rows.querySelector('[data-form-row][hidden]');
    if (row) {
      for (const control of row.querySelectorAll('select, input')) {
        if (control.type === 'checkbox') control.checked = false;
        else control.value = '';
      }
      row.querySelectorAll('[data-field-errors]').forEach((error) => error.remove());
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
  });

  rows.addEventListener('click', (event) => {
    const remove = event.target.closest('[data-remove-line]');
    if (!remove) return;
    const row = remove.closest('[data-form-row]');
    setDeleted(row, true);
    updateNumbers();
    add.focus();
  });

  rows.querySelectorAll('[data-form-row][hidden]').forEach((row) => setDeleted(row, true));
  updateNumbers();
})();
