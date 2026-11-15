/* View 1: the project in two minutes. */
(function () {
  'use strict';
  var App = window.App;
  var Twin = window.Twin;
  var h = App.h;
  var scene, device, timer, active = false;
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function paintScene() {
    var inv = device.inverter;
    scene.update({
      clock: inv.clock,
      cloud: inv.cloud_pct,
      acW: inv.ac_w,
      dcW: inv.dc_w,
      gridOk: true,
      state: inv.state,
      shown: Math.round(inv.ac_w),
      stateText: App.stateShort(inv.state),
      talking: inv.ac_w > 0,
    });
    document.getElementById('tour-now').textContent =
      App.clock(inv.clock) + '  ' + App.num(Math.round(inv.ac_w)) + ' ' + App.t('W', 'Вт') + '  ' + App.stateWords(inv.state);
  }

  function frame() {
    if (!active) return;
    var inv = device.inverter;
    var night = inv.clock < Twin.SUNRISE_S - 1800 || inv.clock > Twin.SUNSET_S + 1800;
    inv.advance(night ? 400 : 75);
    paintScene();
    timer = window.requestAnimationFrame(frame);
  }

  function talk() {
    var box = App.clear(document.getElementById('tour-talk'));
    var noon = new Twin.Device(1);
    noon.inverter.advance(60);
    var address = App.layout.byName['101.W'].address;
    var request = Twin.rtu(1, Twin.readRequest(address, 1));
    var reply = noon.serveRtu(request).reply;
    var q = App.readFrame(request, { dir: 'tx' });
    var a = App.readFrame(reply, { dir: 'rx' });
    box.appendChild(
      h('div', { class: 'q' }, [
        h('div', { class: 'who' }, [
          App.both('The computer asks:', 'Компьютер спрашивает:'),
          h('span', { class: 'say' }, App.both('"How much power are you delivering right now?"', '«Сколько мощности ты сейчас отдаёшь?»')),
        ]),
        App.renderBytes(q),
      ])
    );
    box.appendChild(
      h('div', { class: 'a' }, [
        h('div', { class: 'who' }, [
          App.both('The inverter answers:', 'Инвертор отвечает:'),
          h('span', { class: 'say' }, App.both('"5000 watts."', '«5000 ватт».')),
        ]),
        App.renderBytes(a),
        h('p', { class: 'small muted' }, App.both('13 88 is the number 5000 written in hexadecimal, the way computers count.', '13 88 — это число 5000 в шестнадцатеричной записи, так считают компьютеры.')),
      ])
    );
  }

  function tile(big, en, ru) {
    return h('div', { class: 'tile' }, [h('div', { class: 'big' }, big), h('div', { class: 'what' }, App.both(en, ru))]);
  }

  function numbers() {
    var run = window.RUN_DATA;
    var box = App.clear(document.getElementById('tour-tiles'));
    var passed = 0, failed = 0, frames = 0, links = 0;
    Object.keys(run.meta).forEach(function (link) {
      links += 1;
      passed += run.meta[link].passed;
      failed += run.meta[link].failed;
      frames += run.meta[link].frames;
    });
    box.appendChild(tile(App.num(run.tests.length), 'checks, each one a plain sentence', 'проверок, каждая — понятное предложение'));
    box.appendChild(tile(String(links), 'ways to connect: in memory, serial port, network', 'способа подключения: в памяти, последовательный порт, сеть'));
    box.appendChild(tile(App.num(passed), 'passes in the last run, ' + failed + ' failures', 'успешных прохождений в последнем прогоне, падений: ' + failed));
    box.appendChild(tile(App.num(frames), 'messages exchanged with the inverter', 'сообщений, которыми обменялись с инвертором'));

    var hunt = window.MUTANT_DATA;
    var dots = App.clear(document.getElementById('tour-dots'));
    hunt.mutants.forEach(function (m) {
      dots.appendChild(h('i', { class: m.caught ? null : 'bad', title: m.id }));
    });
    var line = App.clear(document.getElementById('tour-hunt'));
    line.appendChild(
      h('strong', null, App.both(hunt.meta.caught + ' of ' + hunt.meta.total + ' planted bugs were caught.', 'Поймано ' + hunt.meta.caught + ' из ' + hunt.meta.total + ' посаженных багов.'))
    );
    line.appendChild(document.createTextNode(' '));
    line.appendChild(h('span', { class: 'muted' }, App.both('Each square is one bug.', 'Каждый квадрат — один баг.')));
  }

  App.views.tour = {
    init: function () {
      scene = App.Scene(document.getElementById('tour-scene'));
      device = new Twin.Device(1);
      device.inverter.clock = reduced ? 12 * 3600 : 10 * 3600;
      device.inverter.advance(120);
      talk();
      numbers();
      paintScene();
      App.onLang(function () {
        talk();
        numbers();
        paintScene();
      });
    },
    show: function () {
      active = true;
      if (!reduced) timer = window.requestAnimationFrame(frame);
    },
    hide: function () {
      active = false;
      if (timer) window.cancelAnimationFrame(timer);
    },
  };
})();
