// Live logs over WebSocket.
(function () {
  var pane = ETH.$("#logs-pane");
  var statusEl = ETH.$("#ws-status");
  var filterInput = ETH.$("#log-filter");
  var pauseEl = ETH.$("#log-pause");
  var clearBtn = ETH.$("#log-clear");
  if (!pane) return;

  var enabled = { ERROR: true, WARNING: true, SUCCESS: true, INFO: true, DEBUG: false };
  ETH.$$('input[data-lvl]').forEach(function (el) {
    el.addEventListener("change", function () { enabled[el.dataset.lvl] = el.checked; rerender(); });
  });

  var ring = [];
  var MAX = 2000;

  function rowHtml(rec) {
    var lv = rec.level || "INFO";
    return '<div class="log-row" data-lvl="' + ETH.escape(lv) + '">' +
      '<span class="ts">' + ETH.fmtTs(rec.ts) + '</span> ' +
      '<span class="lv ' + ETH.escape(lv) + '">' + ETH.escape(lv) + '</span> ' +
      '<span class="mod">' + ETH.escape(rec.module || '') + '</span> ' +
      '<span class="msg">' + ETH.escape(rec.msg || '') + '</span>' +
      '</div>';
  }

  function passesFilter(rec) {
    if (!enabled[rec.level || "INFO"]) return false;
    var f = (filterInput && filterInput.value || "").trim().toLowerCase();
    if (!f) return true;
    return ((rec.msg || "") + " " + (rec.module || "")).toLowerCase().includes(f);
  }

  function append(rec) {
    if (!passesFilter(rec)) return;
    var nearBottom = pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 30;
    pane.insertAdjacentHTML("beforeend", rowHtml(rec));
    while (pane.children.length > MAX) pane.removeChild(pane.firstChild);
    if (nearBottom) pane.scrollTop = pane.scrollHeight;
  }

  function rerender() {
    var html = ring.filter(passesFilter).map(rowHtml).join("");
    pane.innerHTML = html;
    pane.scrollTop = pane.scrollHeight;
  }
  if (filterInput) filterInput.addEventListener("input", rerender);
  if (clearBtn) clearBtn.addEventListener("click", function () { ring = []; pane.innerHTML = ""; });

  function setStatus(connected) {
    if (!statusEl) return;
    statusEl.classList.toggle("ws-conn", connected);
    statusEl.classList.toggle("ws-disc", !connected);
    statusEl.title = connected ? "connected" : "disconnected";
  }

  var ws = null;
  function connect() {
    var proto = location.protocol === "https:" ? "wss" : "ws";
    var url = proto + "://" + location.host + "/api/ws/logs";
    try { ws = new WebSocket(url); } catch (e) { setStatus(false); setTimeout(connect, 2000); return; }
    ws.onopen = function () { setStatus(true); };
    ws.onclose = function () { setStatus(false); ws = null; setTimeout(connect, 1500); };
    ws.onerror = function () { setStatus(false); };
    ws.onmessage = function (ev) {
      if (pauseEl && pauseEl.checked) return;
      try {
        var msg = JSON.parse(ev.data);
        if (msg.type === "snapshot" && Array.isArray(msg.records)) {
          ring = msg.records.slice(-MAX);
          rerender();
        } else if (msg.type === "log") {
          ring.push(msg.record);
          if (ring.length > MAX) ring.shift();
          append(msg.record);
        }
      } catch (e) { /* ignore */ }
    };
  }
  connect();
})();
