/* The picture: sun, clouds, a house with panels, the inverter, the grid and the monitoring computer.
   Scene(container) returns an object with update(snapshot). */
(function () {
  'use strict';
  var App = window.App;
  var Twin = window.Twin;
  var NS = 'http://www.w3.org/2000/svg';
  var count = 0;

  function both(x, y, en, ru, cls, anchor) {
    var a = anchor ? ' text-anchor="' + anchor + '"' : '';
    return (
      '<text class="en ' + (cls || '') + '" x="' + x + '" y="' + y + '"' + a + '>' + en + '</text>' +
      '<text class="ru ' + (cls || '') + '" x="' + x + '" y="' + y + '"' + a + '>' + ru + '</text>'
    );
  }

  function markup(id) {
    var stars = '';
    var spots = [[90, 40], [180, 70], [260, 30], [380, 56], [470, 28], [560, 64], [650, 36], [40, 96], [610, 110]];
    spots.forEach(function (p) {
      stars += '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="1.6" fill="#fff"/>';
    });
    var panels = '';
    for (var i = 0; i < 4; i++) {
      var x0 = 252 + i * 20;
      var y0 = 143 - i * 11.6;
      panels +=
        '<polygon points="' + x0 + ',' + y0 + ' ' + (x0 + 18) + ',' + (y0 - 10.4) + ' ' + (x0 + 18) + ',' + (y0 - 24.4) + ' ' + x0 + ',' + (y0 - 14) + '" fill="#1d3a66" stroke="#0d1c33" stroke-width="1"/>';
    }
    return (
      '<svg xmlns="' + NS + '" viewBox="0 0 720 320" role="img" aria-labelledby="' + id + '-t">' +
      '<title id="' + id + '-t">Sun, solar panels on a house, the inverter, the grid and a monitoring computer</title>' +
      '<rect width="720" height="236" fill="var(--sky-night)"/>' +
      '<rect class="day" width="720" height="236" fill="var(--sky-day)"/>' +
      '<g class="stars">' + stars + '</g>' +
      '<path d="M40 232 Q 360 -150 680 232" fill="none" stroke="var(--line)" stroke-dasharray="2 6" opacity="0.7"/>' +
      '<circle class="sun" r="17" fill="var(--sun-fill)"/>' +
      '<g class="cloud" fill="#f4f6f9" stroke="#b5bfcc" stroke-width="1">' +
      '<ellipse cx="0" cy="0" rx="46" ry="17"/><ellipse cx="-26" cy="-12" rx="24" ry="15"/><ellipse cx="12" cy="-16" rx="28" ry="18"/></g>' +
      '<rect y="232" width="720" height="88" fill="var(--sunk)"/>' +
      '<line x1="0" y1="232" x2="720" y2="232" stroke="var(--line)"/>' +
      // house
      '<rect x="250" y="150" width="170" height="82" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.5"/>' +
      '<polygon points="236,150 335,92 434,150" fill="var(--roof)" stroke="var(--ink)" stroke-width="1.5"/>' +
      panels +
      '<polygon class="glow" points="252,143 330,97.8 330,83.8 252,129" fill="var(--sun-fill)"/>' +
      '<rect x="272" y="176" width="34" height="30" fill="var(--sunk)" stroke="var(--ink)"/>' +
      '<rect x="350" y="182" width="30" height="50" fill="var(--sunk)" stroke="var(--ink)"/>' +
      // cables
      '<path class="flow dc" d="M332 100 L 452 138 L 452 168"/>' +
      '<path class="flow ac" d="M476 196 L 612 196"/>' +
      '<path class="flow data" d="M150 262 L 454 262 L 454 226"/>' +
      // inverter
      '<rect x="432" y="168" width="44" height="58" rx="5" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.5"/>' +
      '<circle class="invled" cx="442" cy="178" r="4"/>' +
      '<rect x="437" y="188" width="34" height="16" rx="2" fill="var(--sunk)"/>' +
      '<text class="lcd invw" x="454" y="200" text-anchor="middle" style="font-size:10px">0</text>' +
      both(484, 222, 'inverter', 'инвертор', 'lbl') +
      // grid
      '<g class="pylon" stroke="var(--ink)" stroke-width="1.5" fill="none">' +
      '<path d="M628 232 L 636 150 L 644 232 M 620 168 H 652 M 624 186 H 648 M 636 150 V 140"/>' +
      '<path d="M652 168 Q 690 176 720 164 M 648 186 Q 690 194 720 182"/></g>' +
      both(636, 250, 'grid', 'сеть', 'lbl', 'middle') +
      '<g class="gridx" stroke="var(--bad)" stroke-width="4" stroke-linecap="round"><path d="M536 184 L 560 208 M 560 184 L 536 208"/></g>' +
      // monitoring computer
      '<rect x="62" y="212" width="88" height="54" rx="4" fill="var(--surface)" stroke="var(--ink)" stroke-width="1.5"/>' +
      '<rect x="52" y="266" width="108" height="6" rx="3" fill="var(--ink)"/>' +
      '<text class="lcd monw" x="106" y="236" text-anchor="middle" style="font-size:12px">0 W</text>' +
      '<text class="lcd monst" x="106" y="254" text-anchor="middle" style="font-size:9.5px;font-weight:500" fill="var(--muted)"></text>' +
      both(106, 290, 'monitoring computer', 'компьютер мониторинга', 'lbl', 'middle') +
      both(300, 281, 'questions and answers', 'вопросы и ответы', 'lbl', 'middle') +
      '<text class="lcd clk" x="16" y="26" style="font-size:15px" fill="#fff"></text>' +
      '</svg>'
    );
  }

  App.Scene = function (container) {
    count += 1;
    container.innerHTML = markup('scene' + count);
    var svg = container.querySelector('svg');
    function q(selector) {
      return svg.querySelector(selector);
    }
    var parts = {
      day: q('.day'),
      stars: q('.stars'),
      sun: q('.sun'),
      cloud: q('.cloud'),
      glow: q('.glow'),
      dc: q('.flow.dc'),
      ac: q('.flow.ac'),
      data: q('.flow.data'),
      led: q('.invled'),
      invw: q('.invw'),
      monw: q('.monw'),
      monst: q('.monst'),
      clk: q('.clk'),
      pylon: q('.pylon'),
      gridx: q('.gridx'),
    };

    function flow(node, fraction) {
      if (fraction > 0.002) {
        node.classList.add('on');
        node.style.setProperty('--flow-s', (2.2 - 1.8 * Math.min(1, fraction)).toFixed(2) + 's');
      } else {
        node.classList.remove('on');
      }
    }

    return {
      /* snapshot: {clock, cloud, acW, dcW, gridOk, state, stateText, talking} */
      update: function (s) {
        var span = Twin.SUNSET_S - Twin.SUNRISE_S;
        var x = (s.clock - Twin.SUNRISE_S) / span;
        var up = x > 0 && x < 1;
        var height = up ? 4 * x * (1 - x) : 0;
        var daylight = up ? Math.min(1, height * 3) : 0;
        parts.day.setAttribute('opacity', (daylight * (1 - 0.35 * (s.cloud / 100))).toFixed(3));
        parts.stars.setAttribute('opacity', (1 - daylight).toFixed(3));
        parts.clk.setAttribute('fill', daylight > 0.5 ? 'var(--ink)' : '#fff');
        if (up) {
          // a point on the dashed arc: quadratic curve from (40,232) through control (360,-150) to (680,232)
          var px = (1 - x) * (1 - x) * 40 + 2 * (1 - x) * x * 360 + x * x * 680;
          var py = (1 - x) * (1 - x) * 232 + 2 * (1 - x) * x * -150 + x * x * 232;
          parts.sun.setAttribute('cx', px.toFixed(1));
          parts.sun.setAttribute('cy', py.toFixed(1));
          parts.sun.setAttribute('opacity', '1');
          parts.cloud.setAttribute('transform', 'translate(' + (px + 6).toFixed(1) + ',' + (py + 8).toFixed(1) + ') scale(' + (0.9 + s.cloud / 160).toFixed(2) + ')');
        } else {
          parts.sun.setAttribute('opacity', '0');
          parts.cloud.setAttribute('transform', 'translate(360,60)');
        }
        parts.cloud.setAttribute('opacity', (s.cloud / 100).toFixed(2));
        parts.glow.setAttribute('opacity', (0.32 * Math.min(1, s.dcW / 5200)).toFixed(3));
        flow(parts.dc, s.dcW / 5200);
        flow(parts.ac, s.acW / Twin.RATED_W);
        if (s.talking) parts.data.classList.add('on');
        else parts.data.classList.remove('on');
        parts.data.style.setProperty('--flow-s', '0.7s');
        var st = Twin.ST;
        var led = s.state === st.FAULT ? 'var(--bad)' : s.state === st.MPPT ? 'var(--ok)' : s.state === st.SLEEPING ? 'var(--idle)' : 'var(--sun-fill)';
        parts.led.setAttribute('fill', led);
        parts.invw.textContent = String(Math.round(s.acW));
        parts.monw.textContent = s.shown === null || s.shown === undefined ? '…' : App.num(s.shown) + ' ' + App.t('W', 'Вт');
        parts.monst.textContent = s.stateText || '';
        parts.clk.textContent = App.clock(s.clock);
        parts.gridx.setAttribute('opacity', s.gridOk ? '0' : '1');
        parts.pylon.setAttribute('opacity', s.gridOk ? '1' : '0.35');
      },
    };
  };

  /* Plain words for an operating state. */
  App.stateWords = function (state) {
    var st = Twin.ST;
    if (state === st.SLEEPING) return App.t('asleep: not enough light', 'спит: мало света');
    if (state === st.STARTING) return App.t('checking the grid before it starts', 'проверяет сеть перед запуском');
    if (state === st.MPPT) return App.t('feeding in everything the sun gives', 'отдаёт всё, что даёт солнце');
    if (state === st.THROTTLED) return App.t('held back by a power limit', 'сдерживается ограничением мощности');
    if (state === st.FAULT) return App.t('stopped: fault', 'остановлен: авария');
    if (state === st.STANDBY) return App.t('disconnected on command', 'отключён по команде');
    return '';
  };
  App.stateShort = function (state) {
    return Twin.MAP.states[String(state)] || '';
  };
})();
