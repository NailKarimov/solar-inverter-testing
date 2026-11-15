/* View 3: one question and one answer taken apart, noise and the checksum, and the SunSpec map. */
(function () {
  'use strict';
  var App = window.App;
  var Twin = window.Twin;
  var h = App.h;
  var MAP = Twin.MAP;
  var layout = App.layout;

  var device = new Twin.Device(1);
  var tcp = false;
  var transaction = 0;
  var current = 'W';
  var noise = null; // index of the flipped bit, or null
  var block = '101';

  var QUESTIONS = [
    { id: 'W', en: 'How much power right now?', ru: 'Какая сейчас мощность?', key: '101.W' },
    { id: 'V', en: 'What is the grid voltage?', ru: 'Какое напряжение в сети?', key: '101.PhVphA' },
    { id: 'T', en: 'How hot is the heat sink?', ru: 'Насколько нагрет радиатор?', key: '101.TmpSnk' },
    { id: 'E', en: 'How much energy since installation?', ru: 'Сколько энергии с момента установки?', key: '101.WH' },
    { id: 'S', en: 'What are you doing?', ru: 'Что ты сейчас делаешь?', key: '101.St' },
    { id: 'N', en: 'Who made you?', ru: 'Кто тебя сделал?', key: '1.Mn' },
    { id: 'X', en: 'What is in register 39999?', ru: 'Что в регистре 39999?', raw: 39999 },
    { id: 'L', en: 'Limit your power to 50 %', ru: 'Ограничь мощность до 50 %', limit: 50 },
    { id: 'F', en: 'Remove the limit', ru: 'Сними ограничение', limit: 100, off: true },
    { id: 'B', en: 'Limit your power to 150 %', ru: 'Ограничь мощность до 150 %', limit: 150 },
  ];

  function question() {
    return QUESTIONS.filter(function (q) {
      return q.id === current;
    })[0];
  }

  function pduFor(q) {
    if (q.key) {
      var entry = layout.byName[q.key];
      return Twin.readRequest(entry.address, entry.point.size);
    }
    if (q.raw) return Twin.readRequest(q.raw, 1);
    return Twin.writeMultiple(layout.byName['123.WMaxLimPct'].address, [q.limit, 0, 0, 0, q.off ? 0 : 1]);
  }

  function units(u) {
    var ru = { W: 'Вт', V: 'В', A: 'А', Hz: 'Гц', Wh: 'Вт·ч', C: '°C', VA: 'ВА', var: 'вар', '%': '%', s: 'с' };
    if (u === 'C') return '°C';
    return App.lang === 'ru' && ru[u] ? ru[u] : u;
  }

  /* The value of a point in real units, as text; null if the inverter does not have it. */
  function pointValue(entry) {
    var point = entry.point;
    var raw = Twin.decodePoint(point, device.read(entry.address, point.size));
    if (raw === null) return null;
    if (point.type === 'string') return { text: raw, raw: raw };
    var text;
    if (point.sf) {
      var sfEntry = layout.byName[entry.model.id + '.' + point.sf];
      var sf = Twin.decodePoint(sfEntry.point, device.read(sfEntry.address, 1));
      if (sf === null) return { text: String(raw), raw: raw };
      text = App.num(Twin.scaled(raw, sf), sf < 0 ? -sf : 0) + (point.units ? ' ' + units(point.units) : '');
      return { text: text, raw: raw, sf: sf };
    }
    if (point.name === 'St') return { text: App.stateShort(raw) + ': ' + App.stateWords(raw), raw: raw };
    if (point.name === 'Evt1') {
      var names = [];
      if (raw & Twin.EVT_GRID_DISCONNECT) names.push(App.t('no grid', 'нет сети'));
      if (raw & Twin.EVT_OVER_TEMP) names.push(App.t('too hot', 'перегрев'));
      return { text: names.length ? names.join(', ') : App.t('none', 'нет'), raw: raw };
    }
    return { text: App.num(raw) + (point.units ? ' ' + units(point.units) : ''), raw: raw };
  }

  function plainAnswer(q, parsed) {
    if (parsed.refused) {
      return { bad: true, en: 'The inverter refuses and says why. Nothing has changed.', ru: 'Инвертор отказывает и называет причину. Ничего не изменилось.' };
    }
    if (q.key) {
      var entry = layout.byName[q.key];
      var value = pointValue(entry);
      var label = App.pointLabel(entry.point);
      var en = 'In plain words: ' + label + ' is ' + value.text + '.';
      var ru = 'Простыми словами: ' + label + ' — ' + value.text + '.';
      if (value.sf !== undefined && value.sf !== 0) {
        en += ' The register holds ' + value.raw + '; a second register, the scale factor, says ' + value.sf + ': move the decimal point ' + -value.sf + ' place' + (value.sf === -1 ? '' : 's') + ' to the left.';
        ru += ' В регистре лежит ' + value.raw + '; второй регистр, масштабный множитель, равен ' + value.sf + ': запятую нужно сдвинуть влево на ' + -value.sf + '.';
      }
      if (entry.point.size === 2 && entry.point.type !== 'string') {
        en += ' The number is too big for one register, so it takes two.';
        ru += ' Число не помещается в один регистр, поэтому занимает два.';
      }
      if (entry.point.type === 'string') {
        en += ' Text is stored two letters per register.';
        ru += ' Текст хранится по две буквы на регистр.';
      }
      return { en: en, ru: ru };
    }
    if (q.off) return { en: 'The inverter confirms. The limit is off and the power climbs back by 1 kW per second.', ru: 'Инвертор подтверждает. Ограничение снято, мощность возвращается по 1 кВт в секунду.' };
    return { en: 'The inverter confirms by repeating the address and the count. Ask for the power again: it is now 2500 W.', ru: 'Инвертор подтверждает, повторяя адрес и количество. Спросите мощность ещё раз: теперь она 2500 Вт.' };
  }

  function paintTalk() {
    var q = question();
    var pdu = pduFor(q);
    var request, reply;
    if (tcp) {
      transaction = (transaction + 1) & 0xffff;
      request = Twin.mbap(transaction, 1, pdu);
      reply = device.serveTcp(request).reply;
    } else {
      request = Twin.rtu(1, pdu);
      reply = device.serveRtu(request).reply;
    }
    device.inverter.advance(8); // a few seconds pass before the next question
    var qf = App.readFrame(request, { tcp: tcp, dir: 'tx' });
    var af = App.readFrame(reply, { tcp: tcp, dir: 'rx' });
    var box = App.clear(document.getElementById('wire-talk'));
    box.appendChild(
      h('div', { class: 'q' }, [
        h('div', { class: 'who' }, [App.both('The computer sends ' + request.length + ' bytes:', 'Компьютер отправляет байт: ' + request.length), h('span', { class: 'say' }, App.say(qf))]),
        App.renderBytes(qf),
      ])
    );
    var plain = plainAnswer(q, af);
    box.appendChild(
      h('div', { class: 'a' }, [
        h('div', { class: 'who' }, [App.both('The inverter sends back ' + reply.length + ' bytes:', 'Инвертор присылает байт: ' + reply.length), h('span', { class: 'say' }, App.say(af))]),
        App.renderBytes(af),
        h('div', { class: 'verdict' + (plain.bad ? ' bad' : '') }, App.both(plain.en, plain.ru)),
      ])
    );
    var cable = App.clear(document.getElementById('wire-cable'));
    cable.appendChild(
      tcp
        ? App.both(
            'On a network the device address and the checksum are replaced by a 7-byte header. TCP already delivers the bytes undamaged, so Modbus adds no checksum of its own. The middle of the message is the same as on a serial cable.',
            'В сети адрес устройства и контрольную сумму заменяет заголовок из 7 байт. TCP и так доставляет байты неповреждёнными, поэтому своей контрольной суммы Modbus не добавляет. Середина сообщения та же, что и в последовательной линии.'
          )
        : App.both(
            'On a serial cable up to 247 devices share the same two wires. So every message starts with the number of the device it is meant for and ends with a checksum.',
            'В последовательной линии до 247 устройств делят одни и те же два провода. Поэтому каждое сообщение начинается с номера устройства, которому оно предназначено, и заканчивается контрольной суммой.'
          )
    );
  }

  function paintNoise() {
    var q = question();
    var clean = Twin.rtu(1, pduFor(q));
    var frame = clean.slice();
    var hit = {};
    if (noise !== null) {
      var bit = noise % (frame.length * 8);
      frame[bit >> 3] ^= 1 << (bit & 7);
      hit[bit >> 3] = true;
    }
    var parsed = App.readFrame(clean, { dir: 'tx' });
    var position = 0;
    parsed.segs.forEach(function (s) {
      s.bytes = frame.slice(position, position + s.bytes.length);
      position += s.bytes.length;
    });
    var sent = frame.slice(-2);
    var crc = Twin.crc16(frame.slice(0, -2));
    var computed = [crc & 0xff, crc >>> 8];
    var same = sent[0] === computed[0] && sent[1] === computed[1];
    var box = App.clear(document.getElementById('wire-noisebox'));
    box.appendChild(h('div', { class: 'small muted' }, noise === null ? App.both('What arrives at the inverter:', 'Что приходит к инвертору:') : App.both('What arrives at the inverter. The damaged byte is marked:', 'Что приходит к инвертору. Повреждённый байт отмечен:')));
    box.appendChild(App.renderBytes(parsed, hit));
    box.appendChild(
      h('table', null, [
        h('tr', null, [h('td', null, App.both('Checksum that arrived in the message', 'Контрольная сумма, пришедшая в сообщении')), h('td', { class: 'num' }, Twin.hex(sent))]),
        h('tr', null, [h('td', null, App.both('Checksum the inverter calculates from the bytes that arrived', 'Контрольная сумма, которую инвертор вычисляет из пришедших байт')), h('td', { class: 'num' }, Twin.hex(computed))]),
      ])
    );
    box.appendChild(
      same
        ? h('div', { class: 'verdict' }, App.both('The two are equal. The message is intact and the inverter answers.', 'Они равны. Сообщение целое, и инвертор отвечает.'))
        : h(
            'div',
            { class: 'verdict bad' },
            App.both(
              'The two differ. The inverter cannot tell which bit is wrong, so it does nothing and stays silent. The computer waits, gets no answer and asks again.',
              'Они различаются. Инвертор не может узнать, какой бит неверный, поэтому ничего не делает и молчит. Компьютер ждёт, не получает ответа и спрашивает снова.'
            )
          )
    );
  }

  function hexRegisters(registers) {
    var shown = registers.slice(0, 3).map(function (r) {
      return ('000' + r.toString(16).toUpperCase()).slice(-4);
    });
    return shown.join(' ') + (registers.length > 3 ? ' …' : '');
  }

  function blocks() {
    var list = [{ id: 'SunS', label: 'SunS', size: 2, mark: true }];
    var names = { 1: ['who am I', 'кто я'], 101: ['measurements', 'измерения'], 120: ['nameplate', 'паспорт'], 123: ['commands', 'команды'] };
    MAP.models.forEach(function (model) {
      list.push({ id: String(model.id), label: model.id + ' · ' + App.t(names[model.id][0], names[model.id][1]), size: model.length + 2, model: model });
    });
    list.push({ id: 'end', label: App.t('end', 'конец'), size: 2, mark: true });
    return list;
  }

  function paintMap() {
    var bar = App.clear(document.getElementById('wire-mapbar'));
    blocks().forEach(function (b) {
      bar.appendChild(
        h(
          'button',
          {
            type: 'button',
            class: b.mark ? 'mark' : null,
            style: 'flex:' + b.size + ' 0 ' + (b.mark ? '52px' : '0'),
            'aria-pressed': String(b.id === block),
            title: b.size + App.t(' registers', ' рег.'),
            onclick: function () {
              block = b.id;
              paintMap();
            },
          },
          b.label
        )
      );
    });

    var rows = [];
    function row(address, name, what, registers, value, writable) {
      rows.push(
        h('tr', null, [
          h('td', { class: 'num' }, String(address)),
          h('td', null, [h('code', null, name), writable ? h('span', { class: 'pill sun', style: 'margin-left:6px' }, App.t('can be written', 'можно записать')) : null]),
          h('td', null, what),
          h('td', { class: 'num' }, hexRegisters(registers)),
          h('td', null, value === null ? h('span', { class: 'na' }, App.t('not on this inverter', 'у этого инвертора нет')) : value),
        ])
      );
    }
    if (block === 'SunS') {
      row(MAP.base, 'SunS', App.t('the letters "Su"', 'буквы «Su»'), [MAP.marker[0]], 'Su');
      row(MAP.base + 1, '', App.t('the letters "nS"', 'буквы «nS»'), [MAP.marker[1]], 'nS');
    } else if (block === 'end') {
      row(layout.endAddress, 'ID', App.t('end of the chain', 'конец цепочки'), [0xffff], '65535');
      row(layout.endAddress + 1, 'L', App.t('length 0', 'длина 0'), [0], '0');
    } else {
      var model = MAP.models.filter(function (m) {
        return String(m.id) === block;
      })[0];
      var start = layout.modelAddress[model.id];
      row(start, 'ID', App.t('number of this block', 'номер этого блока'), [model.id], String(model.id));
      row(start + 1, 'L', App.t('how many registers follow', 'сколько регистров дальше'), [model.length], String(model.length));
      model.points.forEach(function (point) {
        if (point.type === 'pad') return;
        var entry = layout.byName[model.id + '.' + point.name];
        var value = pointValue(entry);
        row(entry.address, point.name, App.pointLabel(point), device.read(entry.address, point.size), value === null ? null : value.text, point.writable);
      });
    }
    var table = h('table', null, [
      h('thead', null, h('tr', null, [h('th', { class: 'num' }, App.t('Address', 'Адрес')), h('th', null, App.t('Name', 'Имя')), h('th', null, App.t('What it is', 'Что это')), h('th', { class: 'num' }, App.t('In the registers', 'В регистрах')), h('th', null, App.t('Meaning', 'Значение'))])),
      h('tbody', null, rows),
    ]);
    App.clear(document.getElementById('wire-points')).appendChild(table);
  }

  function paintAsk() {
    var box = App.clear(document.getElementById('wire-ask'));
    QUESTIONS.forEach(function (q) {
      box.appendChild(
        h(
          'button',
          {
            type: 'button',
            class: 'btn',
            'aria-pressed': String(q.id === current),
            onclick: function () {
              current = q.id;
              noise = null;
              paintAll();
            },
          },
          App.t(q.en, q.ru)
        )
      );
    });
  }

  function paintAll() {
    paintAsk();
    paintTalk();
    paintNoise();
    paintMap();
  }

  App.views.wire = {
    init: function () {
      device.inverter.advance(60);
      document.getElementById('wire-rtu').addEventListener('click', function () {
        tcp = false;
        cable();
      });
      document.getElementById('wire-tcp').addEventListener('click', function () {
        tcp = true;
        cable();
      });
      function cable() {
        document.getElementById('wire-rtu').setAttribute('aria-pressed', String(!tcp));
        document.getElementById('wire-tcp').setAttribute('aria-pressed', String(tcp));
        paintTalk();
      }
      document.getElementById('wire-noise').addEventListener('click', function () {
        noise = Math.floor(Math.random() * 100000);
        paintNoise();
      });
      document.getElementById('wire-clean').addEventListener('click', function () {
        noise = null;
        paintNoise();
      });
      paintAll();
      App.onLang(paintAll);
    },
    show: function () {},
    hide: function () {},
  };
})();
