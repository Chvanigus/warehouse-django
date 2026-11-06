/** Подключает поиск в выпадающих списках через jQuery страницы или админки. */
(function initializeWarehouseChoices($) {
  if (!$ || !$.fn.select2) return;
  /** Настраивает списки с поиском после загрузки разметки формы. */
  $(function enhanceWarehouseChoices() {
    $('.warehouse-choice').select2({language: 'ru', width: '100%'});
  });
})(window.django?.jQuery || window.jQuery);
