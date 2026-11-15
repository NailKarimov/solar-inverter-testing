/* View 2: the live inverter. The page plays the monitoring computer: it reads the registers over Modbus,
   sends commands as real frames, and watches a handful of rules after every simulated second. */
(function () {
  'use strict';
  var App = window.App;
  var Twin = window.Twin;
  var h = App.h;
  var MAP = Twin.MAP;
  var S = Twin.S;

  var bugs = {};
  var device = new Twin.Device(1, bugs);
  var inv = device.inverter;
  var layout = App.layout;
  var scene;
  var active = false;
  var raf = 0;
  var lastTime = 0;
  var carry = 0;
  var speed = 10;
  var sincePoll = 1;
  var sinceProbe = 0;
  var probeTurn = 0;
  var talkingUntil = 0;
  var dragging = { time: false, cloud: false };
  var readings = null; // values of model 101 as last read over Modbus
  var lastPoll = null;
  var lastCommand = null;
  var scheduled = [];
  var note = null;
  var tracker = { wasOut: false, back: 0 };

  var SPEEDS = [0, 1, 10, 60, 600];
  var LIVE_BUGS = ['M21', 'M23', 'M22', 'M26', 'M30', 'M03', 'M04', 'M18'];

  var checks = [
    { id: 'island', bug: 'M21', en: 'Stops feeding in when the grid is gone', ru: 'Перестаёт отдавать энергию, когда сети нет', hintEn: 'Press "Grid outage" to try it.', hintRu: 'Нажмите «Авария в сети», чтобы проверить.' },
    { id: 'reconnect', bug: 'M22', en: 'Waits 60 seconds after the grid returns', ru: 'Ждёт 60 секунд после возвращения сети', hintEn: 'Cut the grid, then bring it back.', hintRu: 'Отключите сеть и верните её.' },
    { id: 'limit', bug: 'M23', en: 'Obeys the power limit', ru: 'Соблюдает ограничение мощности', hintEn: 'Press "Limit power" around noon.', hintRu: 'Нажмите «Ограничить мощность» около полудня.' },
    { id: 'rated', bug: null, en: 'Never delivers more than its rated 5000 W', ru: 'Никогда не отдаёт больше паспортных 5000 Вт', hintEn: 'Needs strong sun: set the time to noon.', hintRu: 'Нужно яркое солнце: поставьте время на полдень.' },
    { id: 'trip', bug: 'M26', en: 'Stops when the heat sink reaches 95 °C', ru: 'Останавливается, когда радиатор нагрелся до 95 °C', hintEn: 'Press "Heat to 95 °C".', hintRu: 'Нажмите «Нагреть до 95 °C».' },
    { id: 'soft', bug: 'M30', en: 'Power rises by no more than 1 kW per second', ru: 'Мощность растёт не быстрее 1 кВт в секунду', hintEn: 'Let a cloud pass: clouds to 100 % and back.', hintRu: 'Пропустите облако: облака на 100 % и обратно.' },
    { id: 'crc', bug: 'M03', en: 'Does not answer a damaged request', ru: 'Не отвечает на повреждённый запрос' },
    { id: 'unit', bug: 'M04', en: 'Does not answer requests meant for another device', ru: 'Не отвечает на запросы к другому устройству' },
    { id: 'refuse', bug: 'M18', en: 'A refused command changes nothing', ru: 'Отклонённая команда ничего не меняет' },
  ];
  var byId = {};
  checks.forEach(function (c) {
    c.state = 'idle';
    c.n = 0;
    c.detail = null;
    byId[c.id] = c;
  });

  function pass(id) {
    var c = byId[id];
    if (c.state !== 'fail') {
      c.state = 'pass';
      c.n += 1;
    }
  }
  function fail(id, en, ru) {
    var c = byId[id];
    if (c.state !== 'fail') {
      c.state = 'fail';
      var at = App.clock(inv.clock, true);
      c.detail = [at + '  ' + en, at + '  ' + ru];
    }
  }
  function clearChecks(onlyBug) {
    checks.forEach(function (c) {
      if (onlyBug && c.bug !== onlyBug) return;
      c.state = 'idle';
      c.n = 0;
      c.detail = null;
    });
    tracker.wasOut = false;
    tracker.back = 0;
  }

  // ---- talking to the inverter ------------------------------------------------------------------------

  function exchange(pdu) {
    var request = Twin.rtu(1, pdu);
    var result = device.serveRtu(request);
    return { tx: request, rx: result.reply };
  }
  function command(pdu) {
    lastCommand = exchange(pdu);
    talkingUntil = Date.now() + 500;
    sincePoll = 1; // read again at once so the page shows the effect
    return lastCommand;
  }
  function sim(name, value) {
    return command(Twin.writeSingle(MAP.sim.base + S[name], value & 0xffff));
  }
  function address(key) {
    return layout.byName[key].address;
  }
  function setLimit(percent, enabled) {
    // limit, random window, revert timeout, ramp time, enable flag: five registers in one request
    command(Twin.writeMultiple(address('123.WMaxLimPct'), [percent, 0, 0, 0, enabled ? 1 : 0]));
  }

  function decodeModel(id, registers) {
    var model = MAP.models.filter(function (m) {
      return m.id === id;
    })[0];
    var raw = {};
    var offset = 0;
    model.points.forEach(function (point) {
      raw[point.name] = Twin.decodePoint(point, registers.slice(offset, offset + point.size));
      offset += point.size;
    });
    var real = {};
    model.points.forEach(function (point) {
      var value = raw[point.name];
      var sf = point.sf ? raw[point.sf] : null;
      real[point.name] = typeof value === 'number' && typeof sf === 'number' ? Twin.scaled(value, sf) : value;
    });
    return real;
  }

  function poll() {
    var start = layout.modelAddress[101] + 2;
    lastPoll = exchange(Twin.readRequest(start, 50));
    if (lastPoll.rx) readings = decodeModel(101, Twin.registersOf(lastPoll.rx.slice(1, -2)));
    talkingUntil = Math.max(talkingUntil, Date.now() + 180);
  }

  // ---- the rules, looked at after every simulated second --------------------------------------------------

  function tick() {
    for (var i = scheduled.length - 1; i >= 0; i--) {
      scheduled[i].left -= 1;
      if (scheduled[i].left <= 0) {
        scheduled[i].run();
        scheduled.splice(i, 1);
      }
    }
    var before = { ac_w: inv.ac_w, sink_c: inv.sink_c };
    inv.advance(1);
    var w = Math.round(inv.ac_w);

    if (!inv.grid_ok) {
      if (inv.ac_w === 0) pass('island');
      else fail('island', 'the grid is down and the inverter still delivers ' + w + ' W', 'сети нет, а инвертор всё ещё отдаёт ' + w + ' Вт');
      tracker.wasOut = true;
      tracker.back = 0;
    } else if (tracker.wasOut) {
      tracker.back += 1;
      if (inv.ac_w > 0) {
        if (tracker.back <= Twin.RECONNECT_S) fail('reconnect', 'fed in again ' + tracker.back + ' s after the grid returned', 'снова начал отдавать энергию через ' + tracker.back + ' с после возвращения сети');
        else pass('reconnect');
        tracker.wasOut = false;
      }
    }

    var couldGive = inv.availableDc() * 0.975 - 20;
    if (inv.ac_w > Twin.RATED_W + 0.5) fail('rated', w + ' W delivered, the rating is 5000 W', 'отдано ' + w + ' Вт, по паспорту 5000 Вт');
    else if (couldGive > Twin.RATED_W && inv.ac_w > 0) pass('rated');

    if (inv.limit_ena && inv.ramp_left === 0 && inv.ac_w > 0) {
      var allowed = (Twin.RATED_W * inv.eff_pct) / 100;
      if (inv.ac_w > allowed + 0.5) fail('limit', w + ' W delivered, the limit allows ' + Math.round(allowed) + ' W', 'отдано ' + w + ' Вт, ограничение разрешает ' + Math.round(allowed) + ' Вт');
      else if (couldGive > allowed) pass('limit');
    }

    if (before.sink_c >= Twin.TRIP_C) {
      if (inv.ac_w === 0) pass('trip');
      else fail('trip', 'heat sink at ' + before.sink_c.toFixed(1) + ' °C and still running', 'радиатор ' + before.sink_c.toFixed(1).replace('.', ',') + ' °C, а инвертор работает');
    }

    var step = inv.ac_w - before.ac_w;
    if (step > Twin.RAMP_W_PER_S + 0.5) fail('soft', 'power jumped by ' + Math.round(step) + ' W in one second', 'мощность прыгнула на ' + Math.round(step) + ' Вт за секунду');
    else if (step > 1) pass('soft');
  }

  function probe() {
    var request = Twin.rtu(1, Twin.readRequest(address('101.W'), 1));
    var turn = probeTurn++ % 3;
    if (turn === 0) {
      var damaged = request.slice();
      damaged[3] ^= 0x08; // one flipped bit in the register address
      if (device.serveRtu(damaged).reply === null) pass('crc');
      else fail('crc', 'a request with a flipped bit was answered', 'на запрос с перевёрнутым битом пришёл ответ');
    } else if (turn === 1) {
      if (device.serveRtu(Twin.rtu(2, Twin.readRequest(address('101.W'), 1))).reply === null) pass('unit');
      else fail('unit', 'a request for device 2 was answered by device 1', 'на запрос к устройству 2 ответило устройство 1');
    } else {
      var was = inv.limit_pct;
      var answer = device.serveRtu(Twin.rtu(1, Twin.writeSingle(address('123.WMaxLimPct'), 150))).reply;
      var refused = answer !== null && answer[1] === 0x86;
      if (refused && inv.limit_pct === was) pass('refuse');
      else {
        fail('refuse', 'a limit of 150 % was refused, yet the register now reads ' + inv.limit_pct + ' %', 'ограничение 150 % отклонено, но в регистре теперь ' + inv.limit_pct + ' %');
        inv.limit_pct = was;
        inv._retarget();
      }
    }
  }

  // ---- planted bugs ------------------------------------------------------------------------------------

  function ensureDay() {
    if (inv.availableDc() < 5300) sim('SIM_CLOCK_MIN', 13 * 60 + 22); // solar noon
    if (inv.cloud_pct !== 0) sim('SIM_CLOUD', 0);
    if (!inv.conn) command(Twin.writeSingle(address('123.Conn'), 1));
  }
  function later(ticks, run) {
    scheduled.push({ left: ticks, run: run });
  }

  var STIMULUS = {
    M21: function () {
      ensureDay();
      later(25, function () {
        sim('SIM_GRID', 0);
      });
      return ['The page waits until the inverter runs and then cuts the grid.', 'Страница ждёт, пока инвертор заработает, и отключает сеть.'];
    },
    M22: function () {
      ensureDay();
      later(25, function () {
        sim('SIM_GRID', 0);
      });
      later(29, function () {
        sim('SIM_GRID', 1);
      });
      return ['The page cuts the grid for a few seconds and brings it back.', 'Страница отключает сеть на несколько секунд и возвращает её.'];
    },
    M23: function () {
      ensureDay();
      setLimit(50, true);
      return ['The page sends a 50 % power limit.', 'Страница отправляет ограничение мощности 50 %.'];
    },
    M26: function () {
      ensureDay();
      later(25, function () {
        sim('SIM_HEAT', 950);
      });
      return ['The page heats the heat sink to exactly 95.0 °C, the trip point.', 'Страница нагревает радиатор ровно до 95,0 °C, порога отключения.'];
    },
    M30: function () {
      ensureDay();
      later(25, function () {
        sim('SIM_CLOUD', 100);
      });
      later(31, function () {
        sim('SIM_CLOUD', 0);
      });
      return ['The page lets a thick cloud pass over the panels.', 'Страница пропускает над панелями плотное облако.'];
    },
    M03: function () {
      return ['The page sends a request with one flipped bit every few seconds.', 'Страница каждые несколько секунд отправляет запрос с одним перевёрнутым битом.'];
    },
    M04: function () {
      return ['The page sends a request addressed to device 2 every few seconds.', 'Страница каждые несколько секунд отправляет запрос, адресованный устройству 2.'];
    },
    M18: function () {
      return ['The page tries to set a limit of 150 % every few seconds.', 'Страница каждые несколько секунд пытается задать ограничение 150 %.'];
    },
  };

  function setBug(id, on) {
    bugs[id] = on;
    clearChecks(id);
    scheduled = [];
    if (on) {
      if (speed === 0) setSpeed(10);
      var text = STIMULUS[id]();
      note = ['Bug ' + id + ' is on. ' + text[0], 'Баг ' + id + ' включён. ' + text[1]];
    } else {
      if (id === 'M21' || id === 'M22') sim('SIM_GRID', 1);
      if (id === 'M26') sim('SIM_HEAT', MAP.sim.heatOff);
      note = null;
    }
    paintBugs();
    paint();
  }

  // ---- painting ------------------------------------------------------------------------------------------

  function $(id) {
    return document.getElementById(id);
  }

  function setSpeed(value) {
    speed = value;
    Array.prototype.forEach.call($('live-speed').children, function (chip) {
      chip.setAttribute('aria-pressed', String(Number(chip.getAttribute('data-speed')) === value));
    });
  }

  function paintBugs() {
    var box = App.clear($('live-bugs'));
    var all = window.MUTANT_DATA.mutants;
    LIVE_BUGS.forEach(function (id) {
      var mutant = all.filter(function (m) {
        return m.id === id;
      })[0] || { id: id, title: id };
      var input = h('input', {
        type: 'checkbox',
        id: 'bug-' + id,
        onchange: function () {
          setBug(id, input.checked);
        },
      });
      input.checked = !!bugs[id];
      box.appendChild(h('label', { class: 'bug' + (bugs[id] ? ' on' : ''), for: 'bug-' + id }, [input, h('span', null, [h('span', { class: 'id' }, id), App.mutantTitle(mutant)])]));
    });
    var line = $('live-note');
    line.hidden = !note;
    App.clear(line);
    if (note) line.appendChild(App.both(note[0], note[1]));
  }

  function paintChecks() {
    var box = App.clear($('live-checks'));
    checks.forEach(function (c) {
      var mark = c.state === 'pass' ? '✓' : c.state === 'fail' ? '✗' : '○';
      var detail;
      if (c.state === 'fail') detail = App.both(c.detail[0], c.detail[1]);
      else if (c.state === 'pass') detail = App.both(c.n === 1 ? 'checked once' : 'checked ' + App.num(c.n) + ' times', 'проверено раз: ' + App.num(c.n));
      else detail = c.hintEn ? App.both(c.hintEn, c.hintRu) : App.both('the page tries this every few seconds', 'страница пробует это каждые несколько секунд');
      box.appendChild(h('div', { class: 'check ' + c.state, 'data-check': c.id }, [h('div', { class: 'mark' }, mark), h('div', { class: 't' }, App.t(c.en, c.ru)), h('div', { class: 'd' }, detail)]));
    });
  }

  function frameLines(box, exchangeRecord, titleEn, titleRu) {
    box.appendChild(h('div', { class: 'eyebrow' }, App.both(titleEn, titleRu)));
    var q = App.readFrame(exchangeRecord.tx, { dir: 'tx' });
    box.appendChild(h('div', { class: 'ln' }, [h('span', { class: 'dir' }, '→'), h('div', null, [App.renderHex(q, 10), h('div', { class: 'say' }, App.say(q))])]));
    if (exchangeRecord.rx) {
      var a = App.readFrame(exchangeRecord.rx, { dir: 'rx' });
      box.appendChild(h('div', { class: 'ln' }, [h('span', { class: 'dir' }, '←'), h('div', null, [App.renderHex(a, 10), h('div', { class: 'say' }, App.say(a))])]));
    } else {
      box.appendChild(h('div', { class: 'ln' }, [h('span', { class: 'dir' }, '←'), h('div', { class: 'say' }, App.both('silence', 'тишина'))]));
    }
  }

  function paintWire() {
    var box = App.clear($('live-wire'));
    box.style.display = 'grid';
    box.style.gap = '8px';
    if (lastCommand) frameLines(box, lastCommand, 'Last command', 'Последняя команда');
    if (lastPoll) frameLines(box, lastPoll, 'Regular reading', 'Обычное чтение');
  }

  function paint() {
    var r = readings;
    scene.update({
      clock: inv.clock,
      cloud: inv.cloud_pct,
      acW: inv.ac_w,
      dcW: inv.dc_w,
      gridOk: inv.grid_ok,
      state: inv.state,
      shown: r ? r.W : null,
      stateText: r ? App.stateShort(r.St) : '',
      talking: Date.now() < talkingUntil,
    });
    if (!r) return;
    var st = Twin.ST;
    $('live-led').className = 'led ' + (r.St === st.FAULT ? 'fault' : r.St === st.MPPT ? 'run' : r.St === st.SLEEPING ? '' : 'hold');
    $('live-state').textContent = App.stateWords(r.St);
    $('live-st').textContent = App.stateShort(r.St);
    var events = App.clear($('live-events'));
    if (r.Evt1 & Twin.EVT_GRID_DISCONNECT) events.appendChild(h('span', { class: 'pill bad' }, App.t('no grid', 'нет сети')));
    if (r.Evt1 & Twin.EVT_OVER_TEMP) events.appendChild(h('span', { class: 'pill bad' }, App.t('too hot', 'перегрев')));
    $('live-w').textContent = App.num(r.W) + ' ' + App.t('W', 'Вт');
    var share = Math.min(1, r.W / Twin.RATED_W);
    $('live-bar').style.width = (share * 100).toFixed(1) + '%';
    $('live-bar').style.background = r.W > Twin.RATED_W ? 'var(--bad)' : '';
    var mark = $('live-mark');
    mark.style.display = inv.limit_ena ? '' : 'none';
    mark.style.left = 'calc(' + inv.limit_pct + '% - 1px)';
    $('live-v').textContent = App.num(r.PhVphA, 1) + ' ' + App.t('V', 'В');
    $('live-a').textContent = App.num(r.A, 2) + ' ' + App.t('A', 'А');
    $('live-dc').textContent = App.num(r.DCW) + ' ' + App.t('W', 'Вт');
    $('live-t').textContent = App.num(r.TmpSnk, 1) + ' °C';
    $('live-e').textContent = App.num((r.WH - Twin.START_ENERGY_WH) / 1000, 2) + ' ' + App.t('kWh', 'кВт·ч');

    if (!dragging.time) $('live-time').value = String(Math.floor(inv.clock / 60));
    $('live-time-v').textContent = App.clock(inv.clock, true);
    if (!dragging.cloud) $('live-cloud').value = String(inv.cloud_pct);
    $('live-cloud-v').textContent = inv.cloud_pct + ' %';
    $('live-limit-v').textContent = $('live-limit').value + ' %';
    $('live-limit-on').setAttribute('aria-pressed', String(inv.limit_ena));
    $('live-conn').setAttribute('aria-pressed', String(!inv.conn));
    $('live-grid').setAttribute('aria-pressed', String(!inv.grid_ok));
    $('live-heat').setAttribute('aria-pressed', String(inv.heat_override_c !== null));
    paintChecks();
    paintWire();
  }

  function loop(now) {
    if (!active) return;
    var dt = Math.min(0.25, (now - lastTime) / 1000);
    lastTime = now;
    carry += dt * speed;
    var ticks = Math.min(3000, Math.floor(carry));
    carry -= ticks;
    for (var i = 0; i < ticks; i++) tick();
    sinceProbe += dt;
    if (sinceProbe > 1.5) {
      sinceProbe = 0;
      probe();
    }
    sincePoll += dt;
    if (sincePoll >= 0.25) {
      sincePoll = 0;
      poll();
      paint();
    }
    raf = window.requestAnimationFrame(loop);
  }

  function wire() {
    var speeds = $('live-speed');
    SPEEDS.forEach(function (value) {
      speeds.appendChild(
        h(
          'button',
          {
            type: 'button',
            class: 'chip',
            'data-speed': value,
            'aria-pressed': String(value === speed),
            onclick: function () {
              setSpeed(value);
            },
          },
          value === 0 ? App.both('pause', 'пауза') : '×' + value
        )
      );
    });
    var time = $('live-time');
    time.addEventListener('pointerdown', function () {
      dragging.time = true;
    });
    time.addEventListener('input', function () {
      dragging.time = true;
      sim('SIM_CLOCK_MIN', Number(time.value));
    });
    ['change', 'pointerup', 'blur'].forEach(function (name) {
      time.addEventListener(name, function () {
        dragging.time = false;
      });
    });
    var cloud = $('live-cloud');
    cloud.addEventListener('input', function () {
      dragging.cloud = true;
      sim('SIM_CLOUD', Number(cloud.value));
    });
    cloud.addEventListener('change', function () {
      dragging.cloud = false;
    });
    var limit = $('live-limit');
    limit.addEventListener('input', function () {
      $('live-limit-v').textContent = limit.value + ' %';
      if (inv.limit_ena) setLimit(Number(limit.value), true);
    });
    $('live-limit-on').addEventListener('click', function () {
      setLimit(Number(limit.value), !inv.limit_ena);
    });
    $('live-conn').addEventListener('click', function () {
      command(Twin.writeSingle(address('123.Conn'), inv.conn ? 0 : 1));
    });
    $('live-grid').addEventListener('click', function () {
      sim('SIM_GRID', inv.grid_ok ? 0 : 1);
    });
    $('live-heat').addEventListener('click', function () {
      sim('SIM_HEAT', inv.heat_override_c === null ? 950 : MAP.sim.heatOff);
    });
    $('live-reset').addEventListener('click', function () {
      scheduled = [];
      Object.keys(bugs).forEach(function (id) {
        bugs[id] = false;
      });
      note = null;
      sim('SIM_RESET', MAP.sim.resetKey);
      inv.advance(60);
      clearChecks();
      limit.value = '50';
      setSpeed(10);
      paintBugs();
    });
  }

  App.views.live = {
    init: function () {
      scene = App.Scene($('live-scene'));
      inv.advance(60); // a running inverter at noon
      wire();
      paintBugs();
      poll();
      paint();
      App.onLang(function () {
        paintBugs();
        paint();
      });
    },
    show: function () {
      active = true;
      lastTime = window.performance.now();
      raf = window.requestAnimationFrame(loop);
    },
    hide: function () {
      active = false;
      if (raf) window.cancelAnimationFrame(raf);
    },
    /* for the page tests */
    debug: { device: device, checks: checks, setBug: setBug, tick: tick, probe: probe },
  };
})();
