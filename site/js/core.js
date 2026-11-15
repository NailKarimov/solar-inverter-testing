/* Shared helpers: language, small DOM builder, number formats and the frame reader that turns bytes
   into coloured groups and one plain sentence. */
(function () {
  'use strict';
  var Twin = window.Twin;
  var App = (window.App = { views: {}, lang: 'en' });

  // ---- language ---------------------------------------------------------------------------------

  var langListeners = [];
  App.onLang = function (fn) {
    langListeners.push(fn);
  };
  App.t = function (en, ru) {
    return App.lang === 'ru' ? ru : en;
  };
  App.setLang = function (lang, silent) {
    App.lang = lang === 'ru' ? 'ru' : 'en';
    var html = document.documentElement;
    html.setAttribute('data-lang', App.lang);
    html.setAttribute('lang', App.lang);
    document.getElementById('lang-en').setAttribute('aria-pressed', String(App.lang === 'en'));
    document.getElementById('lang-ru').setAttribute('aria-pressed', String(App.lang === 'ru'));
    try {
      localStorage.setItem('lang', App.lang);
    } catch (e) {
      /* storage is optional */
    }
    if (!silent)
      langListeners.forEach(function (fn) {
        fn();
      });
  };
  App.initialLang = function () {
    var saved = null;
    try {
      saved = localStorage.getItem('lang');
    } catch (e) {
      /* storage is optional */
    }
    if (saved === 'ru' || saved === 'en') return saved;
    return /^ru/i.test(navigator.language || '') ? 'ru' : 'en';
  };

  // ---- DOM ----------------------------------------------------------------------------------------

  /* h('div', {class: 'x', onclick: fn}, [child, 'text']) */
  App.h = function (tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs)
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined || value === false) return;
        if (key.slice(0, 2) === 'on') node.addEventListener(key.slice(2), value);
        else if (key === 'html') node.innerHTML = value;
        else node.setAttribute(key, value === true ? '' : value);
      });
    (Array.isArray(children) ? children : children === undefined ? [] : [children]).forEach(function (child) {
      if (child === null || child === undefined || child === false) return;
      node.appendChild(typeof child === 'object' ? child : document.createTextNode(String(child)));
    });
    return node;
  };
  App.clear = function (node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  };
  /* A pair of spans, one per language, for text inside generated markup that should follow the toggle. */
  App.both = function (en, ru) {
    var frag = document.createDocumentFragment();
    frag.appendChild(App.h('span', { class: 'en' }, en));
    frag.appendChild(App.h('span', { class: 'ru' }, ru));
    return frag;
  };

  // ---- formats ------------------------------------------------------------------------------------

  App.num = function (value, digits) {
    return Number(value).toLocaleString(App.lang === 'ru' ? 'ru-RU' : 'en-US', {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits || 0,
    });
  };
  App.clock = function (seconds, withSeconds) {
    var s = ((seconds % 86400) + 86400) % 86400;
    var hh = Math.floor(s / 3600);
    var mm = Math.floor((s % 3600) / 60);
    var text = (hh < 10 ? '0' : '') + hh + ':' + (mm < 10 ? '0' : '') + mm;
    if (withSeconds) text += ':' + (s % 60 < 10 ? '0' : '') + (s % 60);
    return text;
  };
  App.hex2 = function (byte) {
    return (byte < 16 ? '0' : '') + byte.toString(16).toUpperCase();
  };
  App.plural = function (n, one, few, many) {
    var mod10 = n % 10;
    var mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
    return many;
  };

  // ---- names of registers ---------------------------------------------------------------------------

  var layout = (App.layout = new Twin.Layout());
  var RU_LABEL = {
    A: 'ток на выходе',
    AphA: 'ток фазы A',
    PhVphA: 'напряжение сети',
    W: 'мощность на выходе',
    Hz: 'частота сети',
    VA: 'полная мощность',
    VAr: 'реактивная мощность',
    PF: 'коэффициент мощности',
    WH: 'энергия за всё время',
    DCA: 'ток панелей',
    DCV: 'напряжение панелей',
    DCW: 'мощность панелей',
    TmpCab: 'температура в корпусе',
    TmpSnk: 'температура радиатора',
    St: 'состояние',
    Evt1: 'события',
    Mn: 'производитель',
    Md: 'модель',
    Opt: 'опции',
    Vr: 'версия',
    SN: 'серийный номер',
    DA: 'адрес устройства',
    DERTyp: 'тип устройства',
    WRtg: 'паспортная мощность',
    VARtg: 'паспортная полная мощность',
    ARtg: 'паспортный ток',
    Conn: 'подключение к сети',
    Conn_RvrtTms: 'таймаут отключения',
    WMaxLimPct: 'ограничение мощности',
    WMaxLimPct_RvrtTms: 'таймаут ограничения',
    WMaxLimPct_RmpTms: 'время перехода',
    WMaxLim_Ena: 'ограничение включено',
  };
  var SIM_LABEL = {
    SIM_ID: ['simulator marker', 'метка симулятора'],
    SIM_CLOCK_MIN: ['simulator clock, minutes', 'часы симулятора, минуты'],
    SIM_CLOCK_SEC: ['simulator clock, seconds', 'часы симулятора, секунды'],
    SIM_ADVANCE: ['let time pass, seconds', 'пропустить время, секунды'],
    SIM_CLOUD: ['cloud cover, %', 'облачность, %'],
    SIM_AMBIENT: ['air temperature', 'температура воздуха'],
    SIM_GRID: ['grid present', 'сеть есть'],
    SIM_HEAT: ['forced heat sink temperature', 'заданная температура радиатора'],
    SIM_TIME_SCALE: ['clock speed', 'скорость часов'],
    SIM_RESET: ['reset', 'сброс'],
    SIM_FRAMES_OK: ['counter: good frames', 'счётчик: хорошие кадры'],
    SIM_CRC_ERRORS: ['counter: damaged frames', 'счётчик: повреждённые кадры'],
    SIM_FRAMING_ERRORS: ['counter: unfinished frames', 'счётчик: оборванные кадры'],
    SIM_EXCEPTIONS: ['counter: refusals', 'счётчик: отказы'],
    SIM_OTHER_UNIT: ['counter: frames for others', 'счётчик: чужие кадры'],
    SIM_BROADCASTS: ['counter: broadcasts', 'счётчик: кадры для всех'],
  };
  App.pointLabel = function (point) {
    if (App.lang === 'ru') {
      if (RU_LABEL[point.name]) return RU_LABEL[point.name];
      if (point.type === 'sunssf') return 'масштабный множитель';
    }
    var label = point.label;
    // lower-case the first letter unless the label starts with an abbreviation such as AC or DC
    return /^[A-Z][a-z]/.test(label) ? label.charAt(0).toLowerCase() + label.slice(1) : label;
  };
  /* What lives at an address, as a short label; '' if nothing does. */
  App.regLabel = function (address) {
    var map = Twin.MAP;
    if (address === map.base || address === map.base + 1) return App.t('the SunS marker', 'метка SunS');
    var entry = layout.byAddress[address];
    if (entry) return App.pointLabel(entry.point);
    for (var m = 0; m < map.models.length; m++) {
      var at = layout.modelAddress[map.models[m].id];
      if (address === at) return App.t('number of model ', 'номер модели ') + map.models[m].id;
      if (address === at + 1) return App.t('length of model ', 'длина модели ') + map.models[m].id;
    }
    if (address === layout.endAddress || address === layout.endAddress + 1) return App.t('end marker', 'конечная метка');
    var sim = address - map.sim.base;
    if (sim >= 0 && sim < map.sim.names.length) {
      var pair = SIM_LABEL[map.sim.names[sim]];
      return App.t(pair[0], pair[1]);
    }
    return '';
  };
  function regText(address) {
    var label = App.regLabel(address);
    return address + (label ? ' (' + label + ')' : '');
  }

  // ---- reading a frame -------------------------------------------------------------------------------

  var REFUSAL = {
    1: ['this function is not supported', 'такая функция не поддерживается'],
    2: ['there is no such register, or it cannot be written', 'такого регистра нет или в него нельзя писать'],
    3: ['the value or the count is not allowed', 'значение или количество недопустимо'],
    4: ['the device failed', 'сбой устройства'],
  };
  var FN_NAME = {
    3: ['read', 'чтение'],
    4: ['read', 'чтение'],
    6: ['write one register', 'запись одного регистра'],
    16: ['write several registers', 'запись нескольких регистров'],
  };

  function u16(bytes, at) {
    return (bytes[at] << 8) | bytes[at + 1];
  }
  function seg(role, bytes, en, ru) {
    return { role: role, bytes: bytes, cap: [en, ru] };
  }
  function regs(n, lang) {
    if (lang === 'ru') return n + ' ' + App.plural(n, 'регистр', 'регистра', 'регистров');
    return n + (n === 1 ? ' register' : ' registers');
  }

  /* The PDU as segments and a sentence. `dir` is 'tx' (a request) or 'rx' (an answer). */
  function readPdu(pdu, dir) {
    var segs = [];
    var say;
    var fn = pdu[0];
    var name = FN_NAME[fn];
    if (fn & 0x80) {
      var why = REFUSAL[pdu[1]] || ['unknown reason', 'неизвестная причина'];
      segs.push(seg('ex', [fn], 'refused: ' + App.hex2(fn & 0x7f) + ' + 80', 'отказ: ' + App.hex2(fn & 0x7f) + ' + 80'));
      segs.push(seg('ex', pdu.slice(1), 'reason ' + App.hex2(pdu[1] || 0), 'причина ' + App.hex2(pdu[1] || 0)));
      say = ['Refused: ' + why[0] + '.', 'Отказ: ' + why[1] + '.'];
      return { segs: segs, say: say, refused: pdu[1] };
    }
    if (!name) {
      segs.push(seg('fn', [fn], 'action ' + App.hex2(fn), 'действие ' + App.hex2(fn)));
      if (pdu.length > 1) segs.push(seg('data', pdu.slice(1), 'data', 'данные'));
      say = ['Action ' + App.hex2(fn) + ', which this inverter does not know.', 'Действие ' + App.hex2(fn) + ', которого этот инвертор не знает.'];
      return { segs: segs, say: say };
    }
    segs.push(seg('fn', [fn], 'what to do: ' + name[0], 'что сделать: ' + name[1]));
    var address, count, value, values, i;
    if ((fn === 3 || fn === 4) && dir === 'tx' && pdu.length === 5) {
      address = u16(pdu, 1);
      count = u16(pdu, 3);
      segs.push(seg('addr', pdu.slice(1, 3), 'which register: ' + address, 'какой регистр: ' + address));
      segs.push(seg('count', pdu.slice(3, 5), 'how many: ' + count, 'сколько: ' + count));
      say = ['Asks for ' + regs(count, 'en') + ' starting at ' + regText(address) + '.', 'Просит ' + regs(count, 'ru') + ' начиная с ' + regText(address) + '.'];
      return { segs: segs, say: say, address: address, count: count };
    }
    if ((fn === 3 || fn === 4) && dir === 'rx') {
      values = [];
      for (i = 2; i + 1 < pdu.length; i += 2) values.push(u16(pdu, i));
      segs.push(seg('count', pdu.slice(1, 2), (pdu[1] || 0) + ' bytes follow', 'дальше байт: ' + (pdu[1] || 0)));
      segs.push(seg('data', pdu.slice(2), values.length === 1 ? 'the value: ' + values[0] : regs(values.length, 'en'), values.length === 1 ? 'значение: ' + values[0] : regs(values.length, 'ru')));
      var shown = values.length <= 4 ? ': ' + values.join(', ') : '';
      say = ['Answers with ' + regs(values.length, 'en') + shown + '.', 'Отвечает: ' + regs(values.length, 'ru') + shown + '.'];
      return { segs: segs, say: say, values: values };
    }
    if (fn === 6 && pdu.length === 5) {
      address = u16(pdu, 1);
      value = u16(pdu, 3);
      segs.push(seg('addr', pdu.slice(1, 3), 'which register: ' + address, 'какой регистр: ' + address));
      segs.push(seg('data', pdu.slice(3, 5), 'the new value: ' + value, 'новое значение: ' + value));
      say =
        dir === 'tx'
          ? ['Command: write ' + value + ' to register ' + regText(address) + '.', 'Команда: записать ' + value + ' в регистр ' + regText(address) + '.']
          : ['Confirms: ' + value + ' is written to register ' + address + '.', 'Подтверждает: ' + value + ' записано в регистр ' + address + '.'];
      return { segs: segs, say: say, address: address, values: [value] };
    }
    if (fn === 16 && dir === 'tx' && pdu.length >= 6) {
      address = u16(pdu, 1);
      count = u16(pdu, 3);
      values = [];
      for (i = 6; i + 1 < pdu.length; i += 2) values.push(u16(pdu, i));
      segs.push(seg('addr', pdu.slice(1, 3), 'first register: ' + address, 'первый регистр: ' + address));
      segs.push(seg('count', pdu.slice(3, 6), 'how many: ' + count + ', ' + pdu[5] + ' bytes', 'сколько: ' + count + ', байт: ' + pdu[5]));
      segs.push(seg('data', pdu.slice(6), 'the new values: ' + values.join(', '), 'новые значения: ' + values.join(', ')));
      say = [
        'Command: write ' + regs(count, 'en') + ' starting at ' + regText(address) + ': ' + values.join(', ') + '.',
        'Команда: записать ' + regs(count, 'ru') + ' начиная с ' + regText(address) + ': ' + values.join(', ') + '.',
      ];
      return { segs: segs, say: say, address: address, values: values };
    }
    if (fn === 16 && pdu.length === 5) {
      address = u16(pdu, 1);
      count = u16(pdu, 3);
      segs.push(seg('addr', pdu.slice(1, 3), 'first register: ' + address, 'первый регистр: ' + address));
      segs.push(seg('count', pdu.slice(3, 5), 'how many: ' + count, 'сколько: ' + count));
      say = ['Confirms: ' + regs(count, 'en') + ' written from ' + address + '.', 'Подтверждает: записано ' + regs(count, 'ru') + ' с адреса ' + address + '.'];
      return { segs: segs, say: say };
    }
    if (pdu.length > 1) segs.push(seg('data', pdu.slice(1), 'data', 'данные'));
    say = ['A ' + name[0] + ' message of an unusual shape.', 'Сообщение «' + name[1] + '» необычной формы.'];
    return { segs: segs, say: say, odd: true };
  }

  function rawFrame(bytes, en, ru) {
    return { segs: [seg('raw', bytes, '', '')], say: [en, ru], damaged: true };
  }

  /* One frame as segments and a sentence. opts: {tcp: bool, dir: 'tx' | 'rx'} */
  App.readFrame = function (bytes, opts) {
    var out;
    if (opts.tcp) {
      if (bytes.length < 8 || u16(bytes, 2) !== 0)
        return rawFrame(bytes, 'Not a Modbus network frame.', 'Это не сетевой кадр Modbus.');
      out = readPdu(bytes.slice(7), opts.dir);
      out.segs = [
        seg('mbap', bytes.slice(0, 2), 'request number ' + u16(bytes, 0), 'номер запроса ' + u16(bytes, 0)),
        seg('mbap', bytes.slice(2, 4), 'protocol 0: Modbus', 'протокол 0: Modbus'),
        seg('mbap', bytes.slice(4, 6), u16(bytes, 4) + ' bytes follow', 'дальше байт: ' + u16(bytes, 4)),
        seg('unit', bytes.slice(6, 7), 'to device ' + bytes[6], 'устройству ' + bytes[6]),
      ].concat(out.segs);
      out.unit = bytes[6];
      return out;
    }
    if (bytes.length < 4)
      return rawFrame(bytes, 'Too short to be a message: fewer than four bytes.', 'Слишком коротко для сообщения: меньше четырёх байт.');
    if (!Twin.crcOk(bytes))
      return rawFrame(
        bytes,
        'Not a valid message: damaged, cut off or noise. The checksum does not fit.',
        'Это не правильное сообщение: повреждено, оборвано или шум. Контрольная сумма не сходится.'
      );
    out = readPdu(bytes.slice(1, -2), opts.dir);
    var unit = bytes[0];
    var who =
      unit === 0
        ? seg('unit', [unit], 'to everyone (address 0)', 'всем сразу (адрес 0)')
        : opts.dir === 'tx'
          ? seg('unit', [unit], 'to device ' + unit, 'устройству ' + unit)
          : seg('unit', [unit], 'from device ' + unit, 'от устройства ' + unit);
    out.segs = [who].concat(out.segs, [seg('crc', bytes.slice(-2), 'checksum', 'контрольная сумма')]);
    out.unit = unit;
    return out;
  };

  /* Split bytes that hold several frames in a row (pipelined requests, answers that arrived together). */
  App.splitFrames = function (bytes, opts) {
    var frames = [];
    var at = 0;
    var guard = 0;
    while (at < bytes.length && guard++ < 16) {
      var size = bytes.length - at;
      if (opts.tcp) {
        if (size >= 7 && u16(bytes, at + 2) === 0) size = Math.min(size, 6 + u16(bytes, at + 4));
      } else if (opts.dir === 'rx' && size >= 3) {
        var fn = bytes[at + 1];
        var need = fn & 0x80 ? 5 : fn === 3 || fn === 4 ? 5 + bytes[at + 2] : fn === 6 || fn === 16 ? 8 : size;
        if (need <= size && Twin.crcOk(bytes.slice(at, at + need))) size = need;
      }
      frames.push(bytes.slice(at, at + size));
      at += size;
    }
    return frames;
  };

  /* Big labelled groups of bytes. `hit` marks byte positions to highlight. */
  App.renderBytes = function (frame, hit) {
    var box = App.h('div', { class: 'bytes' });
    var position = 0;
    frame.segs.forEach(function (s) {
      var bx = App.h('div', { class: 'bx' });
      s.bytes.forEach(function (byte) {
        bx.appendChild(App.h('span', { class: hit && hit[position] ? 'hit' : null }, App.hex2(byte)));
        position += 1;
      });
      var cap = App.h('div', { class: 'cap' }, s.cap[0] || s.cap[1] ? App.both(s.cap[0], s.cap[1]) : null);
      box.appendChild(App.h('div', { class: 'seg ' + s.role }, [bx, cap]));
    });
    return box;
  };

  /* One line of coloured hex. */
  App.renderHex = function (frame, maxData) {
    var line = App.h('div', { class: 'hexline' });
    frame.segs.forEach(function (s, index) {
      if (index) line.appendChild(document.createTextNode(' '));
      var bytes = s.bytes;
      var more = '';
      if (maxData && bytes.length > maxData) {
        more = ' … +' + (bytes.length - maxData);
        bytes = bytes.slice(0, maxData);
      }
      line.appendChild(App.h('i', { class: s.role }, bytes.map(App.hex2).join(' ') + more));
    });
    return line;
  };

  App.say = function (frame) {
    return App.both(frame.say[0], frame.say[1]);
  };

  // ---- test titles in the current language ------------------------------------------------------------

  var RU = window.RU_DATA || { tests: {}, steps: [], mutants: {}, suites: {}, areas: {} };
  var stepPatterns = RU.steps.map(function (pair) {
    return [new RegExp('^' + pair[0] + '$'), pair[1]];
  });
  App.testTitle = function (test) {
    return App.lang === 'ru' && RU.tests[test.name] ? RU.tests[test.name] : test.title;
  };
  App.stepText = function (text) {
    if (App.lang !== 'ru') return text;
    for (var i = 0; i < stepPatterns.length; i++) {
      if (stepPatterns[i][0].test(text)) return text.replace(stepPatterns[i][0], stepPatterns[i][1]).replace(/(\d)\.(\d)/g, '$1,$2');
    }
    return text;
  };
  App.suiteName = function (suite) {
    var row = RU.suites[suite];
    return row ? App.t(row[0], row[1]) : suite;
  };
  App.suiteBlurb = function (suite) {
    var row = RU.suites[suite];
    return row ? App.t(row[2], row[3]) : '';
  };
  App.mutantTitle = function (mutant) {
    return App.lang === 'ru' && RU.mutants[mutant.id] ? RU.mutants[mutant.id] : mutant.title;
  };
  App.areaName = function (area) {
    var row = (RU.areas || {})[area];
    return row ? App.t(row[0], row[1]) : area;
  };
  App.RU = RU;
})();
