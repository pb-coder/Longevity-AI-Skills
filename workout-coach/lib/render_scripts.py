"""Dashboard inline JavaScript asset."""
from __future__ import annotations


INLINE_JS = r"""
(function() {
  // -------- tabs --------
  function selectTab(name) {
    document.querySelectorAll('.tab').forEach(function(t) {
      t.setAttribute('aria-selected', t.dataset.tab === name ? 'true' : 'false');
    });
    document.querySelectorAll('.tab-panel').forEach(function(p) {
      p.setAttribute('data-active', p.dataset.tab === name ? 'true' : 'false');
    });
    try { history.replaceState(null, '', '#' + name); } catch(e) {}
  }
  document.querySelectorAll('.tab').forEach(function(t) {
    t.addEventListener('click', function() { selectTab(t.dataset.tab); });
  });
  var initial = (location.hash || '#today').slice(1);
  var validTabs = ['today', 'trajectory', 'workout'];
  if (validTabs.indexOf(initial) === -1) initial = 'today';
  selectTab(initial);

  // -------- tooltips for [data-tip] and .term --------
  var tt = document.createElement('div');
  tt.className = 'tooltip';
  document.body.appendChild(tt);

  function showTip(target, evt) {
    var text = target.getAttribute('data-tip');
    if (!text) {
      var dt = target.closest('[data-tip]');
      if (dt) text = dt.getAttribute('data-tip');
    }
    if (!text) return;
    tt.textContent = text;
    tt.classList.add('show');
    moveTip(evt);
  }
  function hideTip() { tt.classList.remove('show'); }
  function moveTip(evt) {
    var x = (evt.clientX || (evt.touches && evt.touches[0].clientX) || 0);
    var y = (evt.clientY || (evt.touches && evt.touches[0].clientY) || 0);
    var ttw = tt.offsetWidth, tth = tt.offsetHeight;
    var px = Math.min(window.innerWidth - ttw - 8, x + 14);
    var py = y - tth - 14;
    if (py < 6) py = y + 18;
    tt.style.left = px + 'px';
    tt.style.top = py + 'px';
  }
  function bindTip(el) {
    el.addEventListener('mouseenter', function(e) { showTip(el, e); });
    el.addEventListener('mousemove', moveTip);
    el.addEventListener('mouseleave', hideTip);
    el.addEventListener('touchstart', function(e) { showTip(el, e); }, {passive: true});
  }
  document.querySelectorAll('[data-tip], .term').forEach(bindTip);
  document.addEventListener('touchend', hideTip);
  document.addEventListener('scroll', hideTip, true);

  // -------- interactive training-load chart --------
  var chart = document.querySelector('.load-chart');
  var ltt = document.querySelector('.load-tooltip');
  if (chart && ltt) {
    var series = JSON.parse(chart.getAttribute('data-series'));
    var left = +chart.getAttribute('data-left');
    var right = +chart.getAttribute('data-right');
    var scrub = chart.querySelector('.scrubber');
    var sLine = chart.querySelector('.scrub-line');
    var sCtl  = chart.querySelector('.scrub-ctl');
    var sAtl  = chart.querySelector('.scrub-atl');

    function vbToClient(x) {
      var box = chart.getBoundingClientRect();
      var vb = chart.viewBox.baseVal;
      return box.left + (x / vb.width) * box.width;
    }
    function clientToVbX(clientX) {
      var box = chart.getBoundingClientRect();
      var vb = chart.viewBox.baseVal;
      return ((clientX - box.left) / box.width) * vb.width;
    }
    function showScrub(evt) {
      var clientX = evt.clientX || (evt.touches && evt.touches[0].clientX);
      var vbx = clientToVbX(clientX);
      if (vbx < left || vbx > right) { hideScrub(); return; }
      var t = (vbx - left) / (right - left);
      var idx = Math.round(t * (series.length - 1));
      if (idx < 0 || idx >= series.length) { hideScrub(); return; }
      var d = series[idx];
      var x = left + (idx / Math.max(series.length - 1, 1)) * (right - left);

      sLine.setAttribute('x1', x); sLine.setAttribute('x2', x);
      // place dots
      var vb = chart.viewBox.baseVal;
      var ctls = series.map(function(s){return s.ctl;});
      var atls = series.map(function(s){return s.atl;});
      var tsbs = series.map(function(s){return s.tsb;});
      var vmax = Math.max.apply(null, ctls.concat(atls)) * 1.15;
      var vmin = Math.min.apply(null, tsbs.concat([0])) * 1.15;
      var span = vmax - vmin;
      var bottom = vb.height - 28;
      function y(v){ return bottom - ((v - vmin) / span) * (bottom - 14); }
      sCtl.setAttribute('cx', x); sCtl.setAttribute('cy', y(d.ctl));
      sAtl.setAttribute('cx', x); sAtl.setAttribute('cy', y(d.atl));
      scrub.style.display = '';

      ltt.style.display = 'block';
      ltt.querySelector('.lt-date').textContent = d.date;
      ltt.querySelector('.lt-ctl').textContent  = d.ctl.toFixed(1);
      ltt.querySelector('.lt-atl').textContent  = d.atl.toFixed(1);
      ltt.querySelector('.lt-tsb').textContent  = (d.tsb >= 0 ? '+' : '') + d.tsb.toFixed(1);
      var px = Math.min(window.innerWidth - ltt.offsetWidth - 10,
                        clientX + 14);
      var py = (evt.clientY || (evt.touches && evt.touches[0].clientY) || 0) - ltt.offsetHeight - 14;
      if (py < 60) py += ltt.offsetHeight + 30;
      ltt.style.left = px + 'px';
      ltt.style.top = py + 'px';
    }
    function hideScrub() {
      scrub.style.display = 'none';
      ltt.style.display = 'none';
    }
    chart.addEventListener('mousemove', showScrub);
    chart.addEventListener('mouseleave', hideScrub);
    chart.addEventListener('touchstart', showScrub, {passive: true});
    chart.addEventListener('touchmove',  showScrub, {passive: true});
    chart.addEventListener('touchend',   hideScrub);
  }

  // -------- markdown viewer for the Workout tab --------
  // The workout markdown contains:
  //   # Workout plan — DATE       (dropped: date is in the page header)
  //   Assessment: ./...html       (dropped: we are already on that file)
  //   ## Workout N: TYPE          (becomes a card)
  //   ## Cardio N: ...            (becomes a card)
  //   Date: ___                    (placeholder line at top of card)
  //   Recovery (...): ___         (placeholder line at top of card)
  //   - Exercise: weight x reps   (bullet)
  //     - sub note  (or `  — sub note` with em-dash)
  function renderMarkdownInto(elt, md) {
    elt.innerHTML = '';
    var lines = md.split('\n');
    var i = 0;
    var card = null;
    var ul = null;        // current top-level <ul>
    var lastLi = null;    // last top-level <li> (for nesting sub-bullets)
    function newCard(title) {
      card = document.createElement('section');
      card.className = 'workout-card';
      if (title) {
        var h = document.createElement('h2');
        h.textContent = title;
        card.appendChild(h);
      }
      elt.appendChild(card);
      ul = null;
      lastLi = null;
    }
    function ensureCard() {
      if (!card) newCard(null);
    }
    function ensureUl() {
      ensureCard();
      if (!ul) {
        ul = document.createElement('ul');
        card.appendChild(ul);
      }
    }
    function addPlaceholder(line) {
      ensureCard();
      var ph = card.querySelector('.placeholders');
      if (!ph) {
        ph = document.createElement('div');
        ph.className = 'placeholders';
        // Insert at top, right after the h2 if present
        var h2 = card.querySelector('h2');
        if (h2 && h2.nextSibling) card.insertBefore(ph, h2.nextSibling);
        else card.appendChild(ph);
      }
      var row = document.createElement('div');
      row.className = 'placeholder-row';
      row.textContent = line;
      ph.appendChild(row);
    }
    while (i < lines.length) {
      var raw = lines[i]; i++;
      var line = raw.replace(/\s+$/, '');
      if (!line.trim()) { ul = null; lastLi = null; continue; }

      // Drop the top-level title line and the Assessment link line.
      if (/^#\s+/.test(line) && !/^##/.test(line)) continue;
      if (/^Assessment:/i.test(line)) continue;

      // ## Workout / Cardio section → new card
      if (/^##\s+/.test(line)) {
        newCard(line.replace(/^##\s+/, ''));
        continue;
      }

      // Date: ___  /  Recovery (...): ___  → placeholder rows
      if (/^Date:/i.test(line) || /^Recovery\s*\(/i.test(line)) {
        addPlaceholder(line);
        continue;
      }

      // Sub-bullet: 2+ leading spaces followed by `-` or `—` (em-dash)
      // or `–` (en-dash). Nests under the previous top-level <li>.
      var sub = line.match(/^\s{2,}(?:[-—–])\s*(.*)$/);
      if (sub) {
        ensureUl();
        if (!lastLi) {
          // No parent — render as italic muted item on its own
          lastLi = document.createElement('li');
          ul.appendChild(lastLi);
        }
        var subUl = lastLi.querySelector('ul');
        if (!subUl) {
          subUl = document.createElement('ul');
          subUl.className = 'sub';
          lastLi.appendChild(subUl);
        }
        var sli = document.createElement('li');
        sli.textContent = sub[1];
        subUl.appendChild(sli);
        continue;
      }

      // Top-level bullet
      var top = line.match(/^-\s+(.*)$/);
      if (top) {
        ensureUl();
        lastLi = document.createElement('li');
        lastLi.textContent = top[1];
        ul.appendChild(lastLi);
        continue;
      }

      // Bare prose under a card (e.g. cardio details)
      ensureCard();
      var p = document.createElement('div');
      p.className = 'workout-prose';
      p.textContent = line;
      card.appendChild(p);
      ul = null;
      lastLi = null;
    }
  }
  var mdScript = document.getElementById('workout-md');
  var workoutTab = document.querySelector('.tab-panel[data-tab="workout"]');
  if (mdScript && workoutTab) {
    renderMarkdownInto(workoutTab, mdScript.textContent);
  }
})();
"""
