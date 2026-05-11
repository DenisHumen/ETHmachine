// Common helpers.
window.ETH = (function () {
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  function fmtTs(ts) {
    var d = new Date((ts || 0) * 1000);
    if (isNaN(d.getTime())) return "--:--:--";
    var hh = String(d.getHours()).padStart(2, "0");
    var mm = String(d.getMinutes()).padStart(2, "0");
    var ss = String(d.getSeconds()).padStart(2, "0");
    return hh + ":" + mm + ":" + ss;
  }
  function escape(s) {
    var d = document.createElement("span");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }
  return { $, $$, fmtTs, escape };
})();
