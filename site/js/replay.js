/* View 4: the last test run. Suites, tests in plain words, and the frames each test exchanged. */
(function () {
  'use strict';
  var App = window.App;
  var Twin = window.Twin;
  var h = App.h;
  var run = window.RUN_DATA;
  var LINKS = ['memory', 'socat', 'tcp'];
  var SHORT = { memory: 'mem', socat: 'ser', tcp: 'tcp' };
  var LINK_TEXT = {
    memory: ['In memory', 'В памяти', 'Modbus RTU over a pair of sockets inside one program. Fast, needs nothing installed.', 'Modbus RTU через пару сокетов внутри одной программы. Быстро и ничего не нужно устанавливать.'],
    socat: ['Virtual serial port', 'Виртуальный последовательный порт', 'Modbus RTU through two serial ports joined by a virtual cable, the way a real COM port behaves.', 'Modbus RTU через два последовательных порта, соединённых виртуальным кабелем: так ведёт себя настоящий COM-порт.'],
    tcp: ['Network', 'Сеть', 'Modbus TCP: the same questions wrapped for a network connection.', 'Modbus TCP: те же вопросы в обёртке для сетевого соединения.'],
  };
  var SKIP_RU = {
    'does not use a link: runs once, in the in-memory run': 'не использует линию: выполняется один раз, в прогоне в памяти',
    'serial-line framing: does not apply to Modbus TCP': 'кадры последовательной линии: к Modbus TCP не относится',
    'Modbus TCP only: run with LINK=tcp': 'только для Modbus TCP',
    'a third-party client needs a real port: run with LINK=socat or LINK=tcp': 'стороннему клиенту нужен настоящий порт',
    'needs the bench: run with LINK=serial://PORT': 'нужен стенд с настоящим кабелем',
    "reads the simulator's memory: not possible on the bench": 'читает память симулятора: на стенде невозможно',
  };
  var query = '';
  var open = {};

  function overall(test) {
    var result = 'skipped';
    LINKS.forEach(function (link) {
      var o = test.links[link] && test.links[link].o;
      if (o === 'f') result = 'failed';
      else if (o === 'p' && result !== 'failed') result = 'passed';
    });
    return result;
  }

  function linkCards() {
    var box = App.clear(document.getElementById('replay-links'));
    LINKS.forEach(function (link) {
      var meta = run.meta[link];
      if (!meta) return;
      var text = LINK_TEXT[link];
      box.appendChild(
        h('div', { class: 'card' }, [
          h('div', { class: 'eyebrow' }, SHORT[link]),
          h('h3', null, App.t(text[0], text[1])),
          h('div', { class: 'big' }, [App.num(meta.passed), ' ', h('span', { class: 'pill ' + (meta.failed ? 'bad' : 'ok') }, meta.failed ? App.t(meta.failed + ' failed', 'упало: ' + meta.failed) : App.t('all passed', 'все прошли'))]),
          h('div', { class: 'small muted' }, App.t(meta.skipped + ' skipped · ' + App.num(meta.frames) + ' messages exchanged', 'пропущено: ' + meta.skipped + ' · сообщений: ' + App.num(meta.frames))),
          h('p', { class: 'small muted' }, App.t(text[2], text[3])),
        ])
      );
    });
  }

  function frameRows(box, direction, hex, tcp) {
    var bytes = Twin.unhex(hex);
    App.splitFrames(bytes, { tcp: tcp, dir: direction }).forEach(function (part) {
      var frame = App.readFrame(part, { tcp: tcp, dir: direction });
      box.appendChild(h('div', { class: 'fr ' + direction }, [h('span', { class: 'dir', title: direction === 'tx' ? App.t('to the inverter', 'инвертору') : App.t('from the inverter', 'от инвертора') }, direction === 'tx' ? '→' : '←'), App.renderHex(frame, 12), h('div', { class: 'say' }, App.t(frame.say[0], frame.say[1]))]));
    });
  }

  function detail(test) {
    var box = h('div', { class: 'detail' });
    var shown = 0;
    var steps = test.steps || [];
    steps.forEach(function (step) {
      if (step.text) box.appendChild(h('div', { class: 'step' }, App.stepText(step.text)));
      step.frames.forEach(function (frame) {
        shown += 1;
        frameRows(box, frame[0], frame[1], test.via === 'tcp');
      });
    });
    if (test.via) {
      var total = test.links[test.via].n;
      if (shown === 0 && !steps.length) box.appendChild(h('p', { class: 'small muted' }, App.t('This check works on the code directly and exchanges no messages with the inverter.', 'Эта проверка работает прямо с кодом и не обменивается сообщениями с инвертором.')));
      if (total > shown && shown > 0) box.appendChild(h('p', { class: 'small muted' }, App.t('…and ' + App.num(total - shown) + ' more messages in this check.', '…и ещё сообщений в этой проверке: ' + App.num(total - shown) + '.')));
      if (shown > 0) box.appendChild(h('p', { class: 'small muted' }, App.t('Recorded on the link: ', 'Записано на линии: ') + App.t(LINK_TEXT[test.via][0], LINK_TEXT[test.via][1]).toLowerCase() + '. → ' + App.t('to the inverter', 'инвертору') + ', ← ' + App.t('from the inverter', 'от инвертора') + '.'));
    }
    LINKS.forEach(function (link) {
      var info = test.links[link];
      if (info && info.why) box.appendChild(h('p', { class: 'small', style: 'color:var(--bad)' }, SHORT[link] + ': ' + info.why));
      var reason = test.skip && test.skip[link];
      if (reason) box.appendChild(h('p', { class: 'small muted' }, SHORT[link] + ' — ' + App.t('skipped: ', 'пропущена: ') + (App.lang === 'ru' && SKIP_RU[reason] ? SKIP_RU[reason] : reason)));
    });
    box.appendChild(h('p', { class: 'small muted mono' }, 'tests/' + test.suite + '.py::' + test.name + (test.params ? '[' + test.params + ']' : '')));
    return box;
  }

  function testRow(test) {
    var result = overall(test);
    var row = h('div', { class: 'test ' + result });
    var chips = h('span', { class: 'lk' });
    LINKS.forEach(function (link) {
      var info = test.links[link];
      if (info) chips.appendChild(h('i', { class: info.o }, SHORT[link]));
    });
    var button = h(
      'button',
      {
        type: 'button',
        'aria-expanded': 'false',
        onclick: function () {
          var existing = row.querySelector('.detail');
          if (existing) {
            row.removeChild(existing);
            button.setAttribute('aria-expanded', 'false');
          } else {
            row.appendChild(detail(test));
            button.setAttribute('aria-expanded', 'true');
          }
        },
      },
      [h('span', { class: 'mk' }, result === 'passed' ? '✓' : result === 'failed' ? '✗' : '–'), h('span', null, [App.testTitle(test), test.params ? h('span', { class: 'par' }, test.params) : null]), chips]
    );
    row.appendChild(button);
    return row;
  }

  function matches(test) {
    if (!query) return true;
    var hay = (App.testTitle(test) + ' ' + test.title + ' ' + test.name + ' ' + test.params).toLowerCase();
    return hay.indexOf(query) >= 0;
  }

  function suites() {
    var box = App.clear(document.getElementById('replay-suites'));
    var order = Object.keys(App.RU.suites);
    var bySuite = {};
    run.tests.forEach(function (test) {
      (bySuite[test.suite] = bySuite[test.suite] || []).push(test);
    });
    Object.keys(bySuite).forEach(function (suite) {
      if (order.indexOf(suite) < 0) order.push(suite);
    });
    var any = false;
    order.forEach(function (suite) {
      var tests = (bySuite[suite] || []).filter(matches);
      if (!tests.length) return;
      any = true;
      var passed = tests.filter(function (t) {
        return overall(t) === 'passed';
      }).length;
      var failed = tests.filter(function (t) {
        return overall(t) === 'failed';
      }).length;
      var skipped = tests.length - passed - failed;
      var label = failed ? App.t(failed + ' failed', 'упало: ' + failed) : skipped === tests.length ? App.t(skipped + ' need the bench', 'нужен стенд: ' + skipped) : passed + ' / ' + tests.length;
      var list = h('div', { class: 'tests' });
      var filled = false;
      function fill() {
        if (filled) return;
        filled = true;
        tests.forEach(function (test) {
          list.appendChild(testRow(test));
        });
      }
      var details = h('details', { class: 'suite', 'data-suite': suite }, [
        h('summary', null, [h('span', { class: 'nm' }, App.suiteName(suite)), h('span', { class: 'bl' }, App.suiteBlurb(suite)), h('span', { class: 'ct pill ' + (failed ? 'bad' : skipped === tests.length ? '' : 'ok') }, label)]),
        list,
      ]);
      details.addEventListener('toggle', function () {
        open[suite] = details.open;
        if (details.open) fill();
      });
      if (query || open[suite]) {
        details.open = true;
        fill();
      }
      box.appendChild(details);
    });
    document.getElementById('replay-none').hidden = any;
  }

  App.views.replay = {
    init: function () {
      var search = document.getElementById('replay-search');
      function placeholder() {
        search.setAttribute('placeholder', App.t('Search: grid, limit, checksum…', 'Поиск: сеть, ограничение, контрольная сумма…'));
      }
      var timer = 0;
      search.addEventListener('input', function () {
        window.clearTimeout(timer);
        timer = window.setTimeout(function () {
          query = search.value.trim().toLowerCase();
          suites();
        }, 150);
      });
      open.test_grid_safety = true;
      placeholder();
      linkCards();
      suites();
      App.onLang(function () {
        placeholder();
        linkCards();
        suites();
      });
    },
    show: function () {},
    hide: function () {},
    /* open one suite and scroll to it (used by links from the bug hunt) */
    find: function (text) {
      var search = document.getElementById('replay-search');
      search.value = text;
      query = text.toLowerCase();
      suites();
    },
  };
})();
