(function ($) {
  if (!$ || !$.fn.select2) return;
  $(function () {
    $('.warehouse-choice').select2({language: 'ru', width: '100%'});
  });
})(window.django?.jQuery || window.jQuery);
