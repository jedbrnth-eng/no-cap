// No Cap ships no web-dashboard UI: this hidden placeholder exists only because a dashboard manifest needs an
// entry. The real surface is the Desktop half (desktop/plugin.js) and the text footer on every other surface.
(function () {
  "use strict";
  var SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;
  var h = SDK.React.createElement;
  function NoCapInfo() {
    return h("p", { className: "p-4 text-sm text-muted-foreground" },
      "No Cap stamps replies in chat. Use /nocap, /cap and /capscore, or the Receipts panel in Hermes Desktop.");
  }
  window.__HERMES_PLUGINS__.register("no-cap", NoCapInfo);
})();
