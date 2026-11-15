/* The JavaScript twin of src/inverter_lab: the same inverter, map and Modbus answers, written again
   for the browser. It repeats the arithmetic of the Python simulator in the same order, so the two
   answer byte for byte alike. site/test/twin.test.mjs replays conversations recorded from the Python
   simulator against this file and fails on the first byte that differs.

   Optional planted bugs (the `bugs` object) mirror mutants of scripts/mutants.py by their ids. */
(function (root) {
  'use strict';

  var MAP = root.SIM_MAP;

  // ---- checksum ---------------------------------------------------------------------------------

  function crc16(bytes) {
    var crc = 0xffff;
    for (var i = 0; i < bytes.length; i++) {
      crc ^= bytes[i];
      for (var k = 0; k < 8; k++) crc = crc & 1 ? (crc >>> 1) ^ 0xa001 : crc >>> 1;
    }
    return crc;
  }
  function withCrc(body) {
    var crc = crc16(body);
    return body.concat([crc & 0xff, crc >>> 8]);
  }
  function crcOk(frame) {
    return frame.length >= 4 && crc16(frame.slice(0, -2)) === (frame[frame.length - 2] | (frame[frame.length - 1] << 8));
  }

  // ---- the inverter (inverter.py) -----------------------------------------------------------------

  var DAY_S = 86400;
  var NOON_S = 12 * 3600;
  var SUNRISE_S = 4 * 3600 + 30 * 60;
  var SUNSET_S = 22 * 3600 + 15 * 60;
  var RATED_W = 5000.0;
  var ARRAY_WP = 6000.0;
  var CLOUD_LOSS = 0.75;
  var EFFICIENCY = 0.975;
  var SELF_USE_W = 20.0;
  var START_W = 60.0;
  var STOP_W = 30.0;
  var STARTUP_S = 20;
  var RECONNECT_S = 60;
  var RAMP_W_PER_S = 1000.0;
  var MPP_V = 360.0;
  var OPEN_V = 440.0;
  var NOMINAL_V = 230.0;
  var V_RISE = 4.0;
  var NOMINAL_HZ = 50.0;
  var AMBIENT_C = 25.0;
  var RISE_C = 45.0;
  var TAU_S = 300.0;
  var TRIP_C = 95.0;
  var RESET_C = 75.0;
  var START_ENERGY_WH = 1234567.0;
  var RATED_A_X10 = 217;

  var ST = { OFF: 1, SLEEPING: 2, STARTING: 3, MPPT: 4, THROTTLED: 5, SHUTTING_DOWN: 6, FAULT: 7, STANDBY: 8 };
  var EVT_GRID_DISCONNECT = 1 << 4;
  var EVT_OVER_TEMP = 1 << 7;

  function roundHalfUp(x) {
    return Math.floor(x + 0.5);
  }

  function Inverter(bugs) {
    this.bugs = bugs || {};
    this.reset();
  }

  Inverter.prototype.reset = function () {
    this.clock = NOON_S;
    this.cloud_pct = 0;
    this.ambient_c = AMBIENT_C;
    this.grid_ok = true;
    this.heat_override_c = null;
    this.state = ST.SLEEPING;
    this.events = 0;
    this.over_temp = false;
    this.startup_left = STARTUP_S;
    this.uptime_s = 0;
    this.ac_w = 0.0;
    this.dc_w = 0.0;
    this.dc_v = 0.0;
    this.dc_a = 0.0;
    this.ac_v = NOMINAL_V;
    this.ac_a = 0.0;
    this.hz = NOMINAL_HZ;
    this.sink_c = AMBIENT_C;
    this.cab_c = AMBIENT_C;
    this.energy_wh = START_ENERGY_WH;
    this.conn = true;
    this.conn_rvrt_s = 0;
    this.conn_age = 0;
    this.limit_ena = false;
    this.limit_pct = 100;
    this.limit_rvrt_s = 0;
    this.limit_rmp_s = 0;
    this.limit_age = 0;
    this.eff_pct = 100.0;
    this.ramp_from = 100.0;
    this.ramp_to = 100.0;
    this.ramp_total = 0;
    this.ramp_left = 0;
    this._measure(this.availableDc());
  };

  Inverter.prototype.availableDc = function () {
    if (!(SUNRISE_S < this.clock && this.clock < SUNSET_S)) return 0.0;
    var x = (this.clock - SUNRISE_S) / (SUNSET_S - SUNRISE_S);
    var sun = 4.0 * x * (1.0 - x);
    return ARRAY_WP * sun * sun * sun * (1.0 - (CLOUD_LOSS * this.cloud_pct) / 100.0);
  };

  Inverter.prototype.writeControls = function (changes) {
    if ('Conn_RvrtTms' in changes) this.conn_rvrt_s = changes.Conn_RvrtTms;
    if ('Conn' in changes) {
      this.conn = changes.Conn === 1;
      this.conn_age = 0;
    }
    if ('WMaxLimPct_RvrtTms' in changes) this.limit_rvrt_s = changes.WMaxLimPct_RvrtTms;
    if ('WMaxLimPct_RmpTms' in changes) this.limit_rmp_s = changes.WMaxLimPct_RmpTms;
    if ('WMaxLimPct' in changes || 'WMaxLim_Ena' in changes) {
      if ('WMaxLimPct' in changes) this.limit_pct = changes.WMaxLimPct;
      if ('WMaxLim_Ena' in changes) this.limit_ena = changes.WMaxLim_Ena === 1;
      this.limit_age = 0;
      this._retarget();
    }
  };

  Inverter.prototype._retarget = function () {
    var target = this.limit_ena ? this.limit_pct : 100.0;
    if (target === this.ramp_to) return;
    this.ramp_from = this.eff_pct;
    this.ramp_to = target;
    this.ramp_total = this.limit_rmp_s;
    this.ramp_left = this.limit_rmp_s;
    if (this.ramp_total === 0) this.eff_pct = target;
  };

  Inverter.prototype.advance = function (seconds) {
    for (var i = 0; i < seconds; i++) this._tick();
  };

  Inverter.prototype._tick = function () {
    var bugs = this.bugs;
    this.clock = (this.clock + 1) % DAY_S;
    this.uptime_s += 1;

    if (this.limit_ena && this.limit_rvrt_s > 0) {
      this.limit_age += 1;
      if (this.limit_age >= this.limit_rvrt_s) {
        this.limit_ena = false;
        this._retarget();
      }
    }
    if (!this.conn && this.conn_rvrt_s > 0) {
      this.conn_age += 1;
      if (this.conn_age >= this.conn_rvrt_s) this.conn = true;
    }

    if (this.ramp_left > 0) {
      this.ramp_left -= 1;
      this.eff_pct = this.ramp_to - ((this.ramp_to - this.ramp_from) * this.ramp_left) / this.ramp_total;
    }

    if (bugs.M26 ? this.sink_c > TRIP_C : this.sink_c >= TRIP_C) this.over_temp = true;
    else if (this.sink_c <= RESET_C) this.over_temp = false;
    var events = 0;
    if (!this.grid_ok && !bugs.M21) events |= EVT_GRID_DISCONNECT;
    if (this.over_temp) events |= EVT_OVER_TEMP;
    this.events = events;

    var available = this.availableDc();
    var running = this.state === ST.MPPT || this.state === ST.THROTTLED;
    if (events) {
      this.state = ST.FAULT;
      this.ac_w = 0.0;
      this._holdStart(this.grid_ok ? STARTUP_S : bugs.M22 ? 6 : RECONNECT_S);
    } else if (!this.conn) {
      this.state = ST.STANDBY;
      this.ac_w = 0.0;
      this._holdStart(STARTUP_S);
    } else if (running && available >= STOP_W) {
      this._produce(available);
    } else if (!running && available >= START_W) {
      if (this.startup_left > 0) {
        this.startup_left -= 1;
        this.state = ST.STARTING;
        this.ac_w = 0.0;
      } else {
        this._produce(available);
      }
    } else {
      this.state = ST.SLEEPING;
      this.ac_w = 0.0;
      this._holdStart(STARTUP_S);
    }

    this._measure(available);
    this.energy_wh += this.ac_w / 3600.0;
  };

  Inverter.prototype._holdStart = function (seconds) {
    if (this.startup_left < seconds) this.startup_left = seconds;
  };

  Inverter.prototype._produce = function (available) {
    var bugs = this.bugs;
    var unconstrained = available * EFFICIENCY - SELF_USE_W;
    if (unconstrained < 0.0) unconstrained = 0.0;
    if (unconstrained > RATED_W && !bugs.M20) unconstrained = RATED_W;
    var limit_w = (RATED_W * this.eff_pct) / 100.0;
    var target = limit_w < unconstrained ? limit_w : unconstrained;
    if (bugs.M23) target = unconstrained;
    if (target > this.ac_w + RAMP_W_PER_S && !bugs.M30) this.ac_w += RAMP_W_PER_S;
    else this.ac_w = target;
    this.state = limit_w < unconstrained ? ST.THROTTLED : ST.MPPT;
  };

  Inverter.prototype._measure = function (available) {
    this.dc_w = this.ac_w > 0.0 ? (this.ac_w + SELF_USE_W) / EFFICIENCY : 0.0;
    if (available > 0.0) {
      var used = this.dc_w / available;
      if (used > 1.0) used = 1.0;
      this.dc_v = OPEN_V - (OPEN_V - MPP_V) * used;
    } else {
      this.dc_v = 0.0;
    }
    this.dc_a = this.dc_v > 0.0 ? this.dc_w / this.dc_v : 0.0;
    if (this.grid_ok) {
      this.ac_v = NOMINAL_V + (V_RISE * this.ac_w) / RATED_W;
      this.hz = NOMINAL_HZ;
    } else {
      this.ac_v = 0.0;
      this.hz = 0.0;
    }
    this.ac_a = this.ac_v > 0.0 ? this.ac_w / this.ac_v : 0.0;
    if (this.heat_override_c !== null) this.sink_c = this.heat_override_c;
    else this.sink_c += (this.ambient_c + (RISE_C * this.ac_w) / RATED_W - this.sink_c) / TAU_S;
    this.cab_c = this.ambient_c + 0.4 * (this.sink_c - this.ambient_c);
  };

  Inverter.prototype.values = function (unit) {
    var r = roundHalfUp;
    var amps = r(this.ac_a * 100.0);
    var watts = r(this.ac_w);
    return {
      '1.Mn': 'QA Portfolio Lab',
      '1.Md': 'SIM-5000-1P',
      '1.Opt': 'RIGA-JUNE',
      '1.Vr': '1.0.0',
      '1.SN': 'SIM5K-2026-0001',
      '1.DA': unit,
      '101.A': amps,
      '101.AphA': amps,
      '101.A_SF': -2,
      '101.PhVphA': r(this.ac_v * 10.0),
      '101.V_SF': -1,
      '101.W': watts,
      '101.W_SF': 0,
      '101.Hz': r(this.hz * 100.0),
      '101.Hz_SF': -2,
      '101.VA': watts,
      '101.VA_SF': 0,
      '101.VAr': 0,
      '101.VAr_SF': 0,
      '101.PF': 10000,
      '101.PF_SF': -2,
      '101.WH': r(this.energy_wh),
      '101.WH_SF': 0,
      '101.DCA': r(this.dc_a * 100.0),
      '101.DCA_SF': -2,
      '101.DCV': r(this.dc_v * 10.0),
      '101.DCV_SF': -1,
      '101.DCW': r(this.dc_w),
      '101.DCW_SF': 0,
      '101.TmpCab': r(this.cab_c * 10.0),
      '101.TmpSnk': r(this.sink_c * 10.0),
      '101.Tmp_SF': -1,
      '101.St': this.state,
      '101.Evt1': this.events,
      '101.Evt2': 0,
      '120.DERTyp': 4,
      '120.WRtg': r(RATED_W),
      '120.WRtg_SF': 0,
      '120.VARtg': r(RATED_W),
      '120.VARtg_SF': 0,
      '120.VArRtgQ1': 0,
      '120.VArRtgQ2': 0,
      '120.VArRtgQ3': 0,
      '120.VArRtgQ4': 0,
      '120.VArRtg_SF': 0,
      '120.ARtg': RATED_A_X10,
      '120.ARtg_SF': -1,
      '120.PFRtgQ1': 100,
      '120.PFRtgQ2': 100,
      '120.PFRtgQ3': 100,
      '120.PFRtgQ4': 100,
      '120.PFRtg_SF': -2,
      '123.Conn_WinTms': 0,
      '123.Conn_RvrtTms': this.conn_rvrt_s,
      '123.Conn': this.conn ? 1 : 0,
      '123.WMaxLimPct': this.limit_pct,
      '123.WMaxLimPct_WinTms': 0,
      '123.WMaxLimPct_RvrtTms': this.limit_rvrt_s,
      '123.WMaxLimPct_RmpTms': this.limit_rmp_s,
      '123.WMaxLim_Ena': this.limit_ena ? 1 : 0,
      '123.OutPFSet': 100,
      '123.OutPFSet_Ena': 0,
      '123.VArPct_Ena': 0,
      '123.WMaxLimPct_SF': 0,
      '123.OutPFSet_SF': -2,
    };
  };

  // ---- the SunSpec map (sunspec.py) ---------------------------------------------------------------

  function Layout() {
    this.base = MAP.base;
    this.entries = [];
    this.modelAddress = {};
    this.byAddress = {};
    this.byName = {};
    var address = this.base + MAP.marker.length;
    for (var m = 0; m < MAP.models.length; m++) {
      var model = MAP.models[m];
      this.modelAddress[model.id] = address;
      address += 2;
      for (var p = 0; p < model.points.length; p++) {
        var point = model.points[p];
        var entry = { address: address, model: model, point: point };
        this.entries.push(entry);
        this.byName[model.id + '.' + point.name] = entry;
        for (var o = 0; o < point.size; o++) this.byAddress[address + o] = entry;
        address += point.size;
      }
    }
    this.endAddress = address;
    this.size = address + 2 - this.base;
  }
  Layout.prototype.contains = function (address, count) {
    return this.base <= address && address + count <= this.base + this.size;
  };
  Layout.prototype.image = function (values) {
    var registers = MAP.marker.slice();
    for (var m = 0; m < MAP.models.length; m++) {
      var model = MAP.models[m];
      registers.push(model.id, model.length);
      for (var p = 0; p < model.points.length; p++) {
        var point = model.points[p];
        var value = values[model.id + '.' + point.name];
        Array.prototype.push.apply(registers, encodePoint(point, value === undefined ? null : value));
      }
    }
    registers.push(0xffff, 0);
    return registers;
  };

  function isSigned(type) {
    return MAP.signed.indexOf(type) >= 0;
  }

  function encodePoint(point, value) {
    var out = [];
    if (point.type === 'string') {
      var text = value === null ? '' : String(value);
      for (var i = 0; i < point.size; i++) {
        var hi = 2 * i < text.length ? text.charCodeAt(2 * i) : 0;
        var lo = 2 * i + 1 < text.length ? text.charCodeAt(2 * i + 1) : 0;
        out.push((hi << 8) | lo);
      }
      return out;
    }
    var number = value === null ? MAP.notImplemented[point.type] : Math.trunc(value);
    if (value !== null && isSigned(point.type)) number &= 0xffff;
    if (point.size === 2) return [Math.floor(number / 65536) & 0xffff, number & 0xffff];
    return [number & 0xffff];
  }

  function decodePoint(point, registers) {
    if (point.type === 'string') {
      var text = '';
      for (var i = 0; i < registers.length; i++) {
        var hi = registers[i] >>> 8;
        var lo = registers[i] & 0xff;
        if (!hi) break;
        text += String.fromCharCode(hi);
        if (!lo) break;
        text += String.fromCharCode(lo);
      }
      return text;
    }
    var number = point.size === 2 ? registers[0] * 65536 + registers[1] : registers[0];
    if (number === MAP.notImplemented[point.type] && point.type !== 'acc32') return null;
    if (isSigned(point.type) && number >= 0x8000) number -= 0x10000;
    return number;
  }

  // ---- the device (device.py) ---------------------------------------------------------------------

  var SIM = MAP.sim;
  var S = {};
  SIM.names.forEach(function (name, index) {
    S[name] = index;
  });
  var FN = { READ_HOLDING: 3, READ_INPUT: 4, WRITE_SINGLE: 6, WRITE_MULTIPLE: 16 };
  var EX = { ILLEGAL_FUNCTION: 1, ILLEGAL_DATA_ADDRESS: 2, ILLEGAL_DATA_VALUE: 3, SERVER_DEVICE_FAILURE: 4 };
  var MAX_READ = 125;
  var MAX_WRITE = 123;

  function IllegalAddress() {}
  function IllegalValue() {}

  function signed16(value) {
    return value >= 0x8000 ? value - 0x10000 : value;
  }

  function Device(unit, bugs) {
    this.unit = unit === undefined ? 1 : unit;
    this.bugs = bugs || {};
    this.inverter = new Inverter(this.bugs);
    this.layout = new Layout();
    this.diag = { frames_ok: 0, crc_errors: 0, framing_errors: 0, exceptions: 0, other_unit: 0, broadcasts: 0 };
    this.time_scale = 0;
  }

  Device.prototype.inSim = function (address, count) {
    return address >= SIM.base && address + count <= SIM.base + SIM.names.length;
  };

  Device.prototype.read = function (address, count) {
    if (this.layout.contains(address, count)) {
      var image = this.layout.image(this.inverter.values(this.unit));
      var start = address - this.layout.base;
      return image.slice(start, start + count);
    }
    if (this.inSim(address, count)) {
      var from = address - SIM.base;
      return this.simImage().slice(from, from + count);
    }
    throw new IllegalAddress();
  };

  Device.prototype.write = function (address, values) {
    if (this.layout.contains(address, values.length)) this.writeControls(address, values);
    else if (this.inSim(address, values.length)) this.writeSim(address - SIM.base, values);
    else throw new IllegalAddress();
  };

  Device.prototype.writeControls = function (address, values) {
    var changes = {};
    var names = [];
    for (var offset = 0; offset < values.length; offset++) {
      var entry = this.layout.byAddress[address + offset];
      if (!entry || !entry.point.writable) throw new IllegalAddress();
      if (!(entry.point.name in changes)) names.push(entry.point.name);
      changes[entry.point.name] = values[offset];
    }
    if (this.bugs.M18) this.inverter.writeControls(changes);
    for (var i = 0; i < names.length; i++) {
      var range = MAP.ranges[names[i]];
      var value = changes[names[i]];
      if (!(range[0] <= value && value <= range[1])) throw new IllegalValue();
    }
    if (!this.bugs.M18) this.inverter.writeControls(changes);
  };

  Device.prototype.simImage = function () {
    var inv = this.inverter;
    var heat = inv.heat_override_c === null ? SIM.heatOff : roundHalfUp(inv.heat_override_c * 10.0) & 0xffff;
    var d = this.diag;
    return [
      SIM.magic,
      Math.floor(inv.clock / 60),
      inv.clock % 60,
      0,
      inv.cloud_pct,
      roundHalfUp(inv.ambient_c * 10.0) & 0xffff,
      inv.grid_ok ? 1 : 0,
      heat,
      this.time_scale,
      0,
      d.frames_ok & 0xffff,
      d.crc_errors & 0xffff,
      d.framing_errors & 0xffff,
      d.exceptions & 0xffff,
      d.other_unit & 0xffff,
      d.broadcasts & 0xffff,
    ];
  };

  Device.prototype.writeSim = function (start, values) {
    var checks = {};
    checks[S.SIM_CLOCK_MIN] = function (v) {
      return v >= 0 && v < DAY_S / 60;
    };
    checks[S.SIM_ADVANCE] = function (v) {
      return v >= 1 && v <= SIM.maxAdvance;
    };
    checks[S.SIM_CLOUD] = function (v) {
      return v >= 0 && v <= 100;
    };
    checks[S.SIM_AMBIENT] = function (v) {
      return signed16(v) >= -400 && signed16(v) <= 700;
    };
    checks[S.SIM_GRID] = function (v) {
      return v === 0 || v === 1;
    };
    checks[S.SIM_HEAT] = function (v) {
      return v === SIM.heatOff || (v >= 0 && v <= 1500);
    };
    checks[S.SIM_TIME_SCALE] = function (v) {
      return v >= 0 && v <= 3600;
    };
    checks[S.SIM_RESET] = function (v) {
      return v === SIM.resetKey;
    };
    var i;
    for (i = 0; i < values.length; i++) {
      if (!(start + i in checks)) throw new IllegalAddress();
      if (!checks[start + i](values[i])) throw new IllegalValue();
    }
    var inv = this.inverter;
    for (i = 0; i < values.length; i++) {
      var offset = start + i;
      var value = values[i];
      if (offset === S.SIM_CLOCK_MIN) inv.clock = value * 60;
      else if (offset === S.SIM_ADVANCE) inv.advance(value);
      else if (offset === S.SIM_CLOUD) inv.cloud_pct = value;
      else if (offset === S.SIM_AMBIENT) inv.ambient_c = signed16(value) / 10.0;
      else if (offset === S.SIM_GRID) inv.grid_ok = value === 1;
      else if (offset === S.SIM_HEAT) inv.heat_override_c = value === SIM.heatOff ? null : value / 10.0;
      else if (offset === S.SIM_TIME_SCALE) this.time_scale = value;
      else if (offset === S.SIM_RESET) {
        inv.reset();
        for (var key in this.diag) this.diag[key] = 0;
        this.time_scale = 0;
      }
    }
  };

  /* The response PDU for a request PDU (arrays of byte values). */
  Device.prototype.respond = function (pdu) {
    var response = this.handle(pdu);
    this.diag.frames_ok += 1;
    if (response[0] & 0x80) this.diag.exceptions += 1;
    return response;
  };

  function u16(bytes, at) {
    return (bytes[at] << 8) | bytes[at + 1];
  }
  function packRegisters(registers) {
    var out = [];
    for (var i = 0; i < registers.length; i++) out.push(registers[i] >>> 8, registers[i] & 0xff);
    return out;
  }

  Device.prototype.handle = function (pdu) {
    var fn = pdu[0];
    try {
      var address, count;
      if (fn === FN.READ_HOLDING || fn === FN.READ_INPUT) {
        if (pdu.length !== 5) throw new IllegalValue();
        address = u16(pdu, 1);
        count = u16(pdu, 3);
        if (!(count >= 1 && count <= MAX_READ)) throw new IllegalValue();
        return [fn, 2 * count].concat(packRegisters(this.read(address, count)));
      }
      if (fn === FN.WRITE_SINGLE) {
        if (pdu.length !== 5) throw new IllegalValue();
        this.write(u16(pdu, 1), [u16(pdu, 3)]);
        return pdu.slice();
      }
      if (fn === FN.WRITE_MULTIPLE) {
        if (pdu.length < 6) throw new IllegalValue();
        address = u16(pdu, 1);
        count = u16(pdu, 3);
        var size = pdu[5];
        if (!(count >= 1 && count <= MAX_WRITE) || size !== 2 * count || pdu.length !== 6 + size) throw new IllegalValue();
        var values = [];
        for (var i = 0; i < count; i++) values.push(u16(pdu, 6 + 2 * i));
        this.write(address, values);
        return pdu.slice(0, 5);
      }
      return [fn | 0x80, EX.ILLEGAL_FUNCTION];
    } catch (error) {
      if (error instanceof IllegalAddress) return [fn | 0x80, EX.ILLEGAL_DATA_ADDRESS];
      if (error instanceof IllegalValue) return [fn | 0x80, EX.ILLEGAL_DATA_VALUE];
      return [fn | 0x80, EX.SERVER_DEVICE_FAILURE];
    }
  };

  /* One complete serial frame arrives (server.py, RtuServer._on_frame).
     Returns {reply: bytes or null, why: 'ok' | 'crc' | 'other-unit' | 'broadcast'}. */
  Device.prototype.serveRtu = function (frame) {
    if (!crcOk(frame) && !this.bugs.M03) {
      this.diag.crc_errors += 1;
      return { reply: null, why: 'crc' };
    }
    var unit = frame[0];
    var pdu = frame.slice(1, -2);
    if (unit === 0) {
      this.diag.broadcasts += 1;
      if (pdu[0] === FN.WRITE_SINGLE || pdu[0] === FN.WRITE_MULTIPLE) this.respond(pdu);
      return { reply: null, why: 'broadcast' };
    }
    if (unit !== this.unit && !this.bugs.M04) {
      this.diag.other_unit += 1;
      return { reply: null, why: 'other-unit' };
    }
    return { reply: withCrc([unit].concat(this.respond(pdu))), why: 'ok' };
  };

  /* One Modbus TCP frame (MBAP header + PDU). Returns the answer frame or null. */
  Device.prototype.serveTcp = function (frame) {
    var transaction = u16(frame, 0);
    var protocol = u16(frame, 2);
    var unit = frame[6];
    if (protocol !== 0) return { reply: null, why: 'not-modbus' };
    if (unit !== this.unit) {
      this.diag.other_unit += 1;
      return { reply: null, why: 'other-unit' };
    }
    return { reply: mbap(transaction, unit, this.respond(frame.slice(7))), why: 'ok' };
  };

  // ---- a small master: build requests, read values by name -----------------------------------------

  function readRequest(address, count, fn) {
    return [fn || FN.READ_HOLDING, address >>> 8, address & 0xff, count >>> 8, count & 0xff];
  }
  function writeSingle(address, value) {
    return [FN.WRITE_SINGLE, address >>> 8, address & 0xff, (value >>> 8) & 0xff, value & 0xff];
  }
  function writeMultiple(address, values) {
    return [FN.WRITE_MULTIPLE, address >>> 8, address & 0xff, 0, values.length, 2 * values.length].concat(
      packRegisters(
        values.map(function (v) {
          return v & 0xffff;
        })
      )
    );
  }
  function rtu(unit, pdu) {
    return withCrc([unit].concat(pdu));
  }
  function mbap(transaction, unit, pdu) {
    var length = pdu.length + 1;
    return [transaction >>> 8, transaction & 0xff, 0, 0, length >>> 8, length & 0xff, unit].concat(pdu);
  }
  function registersOf(responsePdu) {
    var out = [];
    for (var i = 2; i + 1 < responsePdu.length; i += 2) out.push(u16(responsePdu, i));
    return out;
  }
  function scaled(raw, sf) {
    return sf >= 0 ? raw * Math.pow(10, sf) : raw / Math.pow(10, -sf);
  }

  function hex(bytes) {
    return bytes
      .map(function (b) {
        return (b < 16 ? '0' : '') + b.toString(16).toUpperCase();
      })
      .join(' ');
  }
  function unhex(text) {
    var clean = text.replace(/[^0-9a-fA-F]/g, '');
    var out = [];
    for (var i = 0; i + 1 < clean.length; i += 2) out.push(parseInt(clean.substr(i, 2), 16));
    return out;
  }

  root.Twin = {
    MAP: MAP,
    ST: ST,
    FN: FN,
    EX: EX,
    EVT_GRID_DISCONNECT: EVT_GRID_DISCONNECT,
    EVT_OVER_TEMP: EVT_OVER_TEMP,
    RATED_W: RATED_W,
    TRIP_C: TRIP_C,
    RESET_C: RESET_C,
    SUNRISE_S: SUNRISE_S,
    SUNSET_S: SUNSET_S,
    RECONNECT_S: RECONNECT_S,
    STARTUP_S: STARTUP_S,
    RAMP_W_PER_S: RAMP_W_PER_S,
    START_ENERGY_WH: START_ENERGY_WH,
    S: S,
    crc16: crc16,
    withCrc: withCrc,
    crcOk: crcOk,
    Inverter: Inverter,
    Layout: Layout,
    Device: Device,
    encodePoint: encodePoint,
    decodePoint: decodePoint,
    readRequest: readRequest,
    writeSingle: writeSingle,
    writeMultiple: writeMultiple,
    rtu: rtu,
    mbap: mbap,
    registersOf: registersOf,
    scaled: scaled,
    hex: hex,
    unhex: unhex,
  };
})(typeof window !== 'undefined' ? window : globalThis);
