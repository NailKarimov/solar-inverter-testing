/* The five views and the address bar: #tour, #live, #wire, #replay, #bugs. */
(function () {
  'use strict';
  var App = window.App;
  var NAMES = ['tour', 'live', 'wire', 'replay', 'bugs'];
  var current = null;

  function show(name) {
    if (NAMES.indexOf(name) < 0) name = 'tour';
    if (name === current) return;
    if (current) {
      App.views[current].hide();
      document.getElementById('view-' + current).classList.remove('on');
    }
    current = name;
    document.getElementById('view-' + name).classList.add('on');
    Array.prototype.forEach.call(document.querySelectorAll('.tabs a'), function (link) {
      if (link.getAttribute('data-view') === name) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    App.views[name].show();
    window.scrollTo(0, 0);
  }

  function fromHash() {
    show((window.location.hash || '#tour').slice(1));
  }

  function footer() {
    var meta = window.RUN_DATA.meta.memory || {};
    var text = meta.finished
      ? App.t('Data from the test run of ', 'Данные прогона тестов от ') + meta.finished.slice(0, 10) + (meta.commit ? ', commit ' + meta.commit : '') + (meta.run ? ', run #' + meta.run : '')
      : '';
    document.getElementById('foot-run').textContent = text;
  }

  App.setLang(App.initialLang(), true);
  NAMES.forEach(function (name) {
    App.views[name].init();
  });
  footer();
  App.onLang(footer);
  document.getElementById('lang-en').addEventListener('click', function () {
    App.setLang('en');
  });
  document.getElementById('lang-ru').addEventListener('click', function () {
    App.setLang('ru');
  });
  window.addEventListener('hashchange', fromHash);
  fromHash();
})();
