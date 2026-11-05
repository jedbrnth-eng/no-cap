// No Cap · Cap Board dashboard tab. Plain IIFE against window.__HERMES_PLUGIN_SDK__ (no build step, React from the SDK).
// Data: GET /api/plugins/no-cap/board (dashboard/plugin_api.py → nocap/board.py), polled every few seconds while the
// tab is visible; an unchanged board answers {unchanged: true}, so a poll costs a few stat() calls on the server.
(function () {
  "use strict";
  var SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;
  var React = SDK.React;
  var h = React.createElement;
  var useState = SDK.hooks.useState, useEffect = SDK.hooks.useEffect, useRef = SDK.hooks.useRef;
  var C = SDK.components || {};
  var Card = C.Card, CardContent = C.CardContent, Badge = C.Badge, Label = C.Label;
  var Select = C.Select, SelectOption = C.SelectOption;
  var cn = (SDK.utils && SDK.utils.cn) || function () { return Array.prototype.filter.call(arguments, Boolean).join(" "); };
  var API = "/api/plugins/no-cap/board";
  var POLL_MS = 4000;
  var HIDDEN_POLL_MS = 30000;  // a hidden tab keeps polling, slowly
  var ALL = "";

  // Same dual-signature wiring the Kanban tab uses for the SDK Select (plugins/kanban/dashboard/dist/index.js:315).
  function selectChange(setter) {
    return {
      onValueChange: function (v) { setter(v == null ? "" : v); },
      onChange: function (e) { var v = e && e.target ? e.target.value : e; setter(v == null ? "" : v); },
    };
  }

  function pct(x) { return x == null ? "—" : Math.round(x * 100) + "%"; }

  function ago(ts) {
    if (!ts) return "";
    try { if (SDK.utils && SDK.utils.timeAgo) return SDK.utils.timeAgo(ts * 1000); } catch (_e) { /* fall through */ }
    var s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return Math.round(s) + "s ago";
    if (s < 3600) return Math.round(s / 60) + "m ago";
    if (s < 86400) return Math.round(s / 3600) + "h ago";
    return Math.round(s / 86400) + "d ago";
  }

  function qs(f, v) {
    var p = [];
    ["agent", "model", "skill"].forEach(function (k) { if (f[k]) p.push(k + "=" + encodeURIComponent(f[k])); });
    if (v) p.push("v=" + encodeURIComponent(v));
    return p.length ? "?" + p.join("&") : "";
  }

  // ---- small pieces -----------------------------------------------------------------------------------------------
  function Stat(props) {
    return h("div", { className: cn("nocap-stat", props.tone && "nocap-tone-" + props.tone) },
      h("div", { className: "nocap-stat-label" }, props.label),
      h("div", { className: "nocap-stat-value" }, props.value),
      props.sub ? h("div", { className: "nocap-stat-sub" }, props.sub) : null);
  }

  function RateBar(props) {
    var r = props.row, n = props.min;
    if (r.cap_rate == null) {
      return h("span", { className: "nocap-low", title: "Rates show from " + n + " claims: a rate on fewer is noise." },
        "n=" + r.claims, h("span", { className: "nocap-low-need" }, " · needs " + n));
    }
    return h("div", { className: "nocap-rate", title: r.cap + " of " + r.claims + " claims contradicted by the turn's own tool output" },
      h("div", { className: "nocap-rate-track" },
        h("div", { className: "nocap-rate-fill", style: { width: Math.max(2, Math.round(r.cap_rate * 100)) + "%" } })),
      h("span", { className: "nocap-rate-num" }, pct(r.cap_rate)),
      h("span", { className: "nocap-rate-n" }, r.cap + "/" + r.claims));
  }

  function Trend(props) {
    var t = props.trend || {};
    if (t.dir == null) {
      return h("span", { className: "nocap-trend nocap-trend-none",
        title: "Needs ≥" + props.min + " claims in each 7-day window (this week " + (t.n_cur || 0) + ", the week before " + (t.n_prev || 0) + ")" }, "·");
    }
    var pts = Math.round((t.delta || 0) * 100);
    var arrow = t.dir === "up" ? "▲" : t.dir === "down" ? "▼" : "▬";
    var label = t.dir === "flat" ? "flat" : (pts > 0 ? "+" : "") + pts + " pts";
    return h("span", { className: "nocap-trend nocap-trend-" + t.dir,
      title: "Cap rate last 7 days " + pct(t.cur) + " vs " + pct(t.prev) + " the 7 before" }, arrow + " " + label);
  }

  function Medal(props) {
    var r = props.rank;
    if (r == null) return h("span", { className: "nocap-rank nocap-rank-none" }, "–");
    var icon = r === 1 ? "🧢" : null;
    return h("span", { className: cn("nocap-rank", r <= 3 && "nocap-rank-top", r === 1 && "nocap-rank-1") },
      icon ? h("span", { className: "nocap-rank-cap", "aria-hidden": true }, icon) : null, "#" + r);
  }

  function LeaderTable(props) {
    var rows = props.rows || [], dim = props.dim, min = props.min, flash = props.flash || {};
    if (!rows.length) {
      return h("div", { className: "nocap-empty" }, "No checked replies match these filters yet.");
    }
    var nameHead = dim === "agents" ? "Agent" : dim === "models" ? "Model" : "Skill";
    return h("div", { className: "nocap-table-wrap" },
      h("table", { className: "nocap-table" },
        h("thead", null, h("tr", null,
          h("th", { className: "nocap-col-rank" }, "Rank"),
          h("th", null, nameHead),
          dim === "agents" ? h("th", null, "Model") : null,
          h("th", { className: "nocap-col-rate" }, "Cap rate"),
          h("th", null, "🧾 Receipts"),
          h("th", null, "🔥 Streak"),
          h("th", null, "7d trend"),
          h("th", null, "Top cap"),
          h("th", { className: "nocap-col-num" }, "Replies"))),
        h("tbody", null, rows.map(function (r) {
          return h("tr", { key: r.name, className: cn(r.low_sample && "nocap-row-low", flash[dim + ":" + r.name] && "nocap-row-flash") },
            h("td", null, h(Medal, { rank: r.rank })),
            h("td", { className: "nocap-name" }, r.name),
            dim === "agents" ? h("td", { className: "nocap-model" }, r.model || "—",
              r.models > 1 ? h("span", { className: "nocap-dim" }, " +" + (r.models - 1)) : null) : null,
            h("td", null, h(RateBar, { row: r, min: min })),
            h("td", { className: "nocap-receipts" }, r.receipt_rate == null ? h("span", { className: "nocap-dim" }, r.proven + " 🧾")
              : h("span", null, pct(r.receipt_rate), h("span", { className: "nocap-dim" }, " " + r.proven + "/" + r.claims))),
            h("td", null, r.streak ? h("span", { className: "nocap-streak" }, "🔥 " + r.streak) : h("span", { className: "nocap-dim" }, "0")),
            h("td", null, h(Trend, { trend: r.trend, min: min })),
            h("td", null, r.top_cap ? h("span", { className: "nocap-kind" }, r.top_cap) : h("span", { className: "nocap-dim" }, "—")),
            h("td", { className: "nocap-col-num" }, r.replies));
        }))));
  }

  function Hall(props) {
    var items = props.items || [];
    return h("div", { className: "nocap-hall" },
      h("div", { className: "nocap-section-title" }, "🧢 Hall of Cap",
        h("span", { className: "nocap-section-sub" }, "latest claims the turn's own tool output contradicted")),
      items.length ? h("ol", { className: "nocap-hall-list" }, items.map(function (it, i) {
        return h("li", { key: i + ":" + it.ts, className: "nocap-hall-item" },
          h("div", { className: "nocap-hall-claim" }, "“" + it.claim + "”"),
          h("div", { className: "nocap-hall-evidence" },
            h("span", { className: "nocap-hall-arrow" }, "→ "),
            it.cmd ? h("code", { className: "nocap-code" }, it.cmd) : null,
            it.cmd ? " " : null,
            h("span", null, it.evidence || "contradicted by this turn's tool output")),
          h("div", { className: "nocap-hall-meta" },
            h("span", { className: "nocap-hall-agent" }, it.agent),
            h("span", null, it.model),
            it.skills && it.skills.length ? h("span", null, "skill: " + it.skills.join(", ")) : null,
            h("span", { className: "nocap-kind" }, it.kind),
            h("span", { className: "nocap-dim" }, ago(it.ts))));
      })) : h("div", { className: "nocap-empty" }, "No 🧢 yet. Every claim so far had a receipt or no contradiction."));
  }

  function Filter(props) {
    var opts = props.options || [];
    if (!Select || !SelectOption) {  // older hosts: a native select, styled with the dashboard tokens
      return h("label", { className: "nocap-filter" }, h("span", null, props.label),
        h("select", { className: "nocap-native-select", value: props.value, onChange: function (e) { props.onChange(e.target.value); } },
          h("option", { value: ALL }, "All"), opts.map(function (o) { return h("option", { key: o, value: o }, o); })));
    }
    return h("div", { className: "nocap-filter" },
      Label ? h(Label, { className: "text-xs text-muted-foreground" }, props.label) : h("span", null, props.label),
      h(Select, Object.assign({ value: props.value, className: "h-8" }, selectChange(props.onChange)),
        h(SelectOption, { value: ALL }, "All " + props.plural),
        opts.map(function (o) { return h(SelectOption, { key: o, value: o }, o); })));
  }

  // ---- page ---------------------------------------------------------------------------------------------------
  function CapBoard() {
    var _d = useState(null), data = _d[0], setData = _d[1];
    var _e = useState(""), err = _e[0], setErr = _e[1];
    var _f = useState({ agent: "", model: "", skill: "" }), filters = _f[0], setFilters = _f[1];
    var _m = useState("agents"), dim = _m[0], setDim = _m[1];
    var _t = useState(0), tick = _t[0], setTick = _t[1];
    var _fl = useState({}), flash = _fl[0], setFlash = _fl[1];
    var version = useRef(""), prev = useRef(null), polledAt = useRef(0);

    useEffect(function () {
      var alive = true, timer = null, first = true, inflight = false;
      version.current = "";
      function poll() {
        if (!alive) return;
        // A hidden tab polls every 30 s instead of every 4 (little work while nobody looks), and the first load always
        // runs: a tab opened in the background must not sit on "Loading" until it is focused.
        if (document.hidden && !first && Date.now() - polledAt.current < HIDDEN_POLL_MS) {
          timer = setTimeout(poll, POLL_MS);
          return;
        }
        first = false;
        inflight = true;
        SDK.fetchJSON(API + qs(filters, version.current)).then(function (b) {
          if (!alive) return;
          polledAt.current = Date.now();
          setErr("");
          setTick(function (x) { return x + 1; });
          if (b && b.unchanged) return;
          version.current = b.version || "";
          var changed = {};
          if (prev.current) {
            ["agents", "models", "skills"].forEach(function (k) {
              var old = {};
              (prev.current[k] || []).forEach(function (r) { old[r.name] = r.replies; });
              (b[k] || []).forEach(function (r) { if (old[r.name] !== r.replies) changed[k + ":" + r.name] = true; });
            });
          }
          prev.current = b;
          setData(b);
          if (Object.keys(changed).length) {
            setFlash(changed);
            setTimeout(function () { if (alive) setFlash({}); }, 1600);
          }
        }).catch(function (e) {
          if (alive) setErr(String((e && e.message) || e));
        }).then(function () {
          inflight = false;
          if (alive) timer = setTimeout(poll, POLL_MS);
        });
      }
      function onVisible() { if (!document.hidden && alive && !inflight) { if (timer) clearTimeout(timer); poll(); } }
      document.addEventListener("visibilitychange", onVisible);
      poll();
      return function () {
        alive = false;
        if (timer) clearTimeout(timer);
        document.removeEventListener("visibilitychange", onVisible);
      };
    }, [filters.agent, filters.model, filters.skill]);

    function setF(k) { return function (v) { setFilters(Object.assign({}, filters, (function () { var o = {}; o[k] = v; return o; })())); }; }

    if (!data) {
      return h("div", { className: "nocap-board" },
        h("div", { className: "nocap-empty" }, err ? "Cap Board couldn't load: " + err : "Loading the Cap Board…"));
    }
    var t = data.totals || {}, o = data.options || {}, n = data.min_claims;
    var rows = data[dim] || [];
    var leader = (data.agents || []).filter(function (r) { return r.rank === 1; })[0];
    var bad = (data.sources || []).reduce(function (a, s) { return a + (s.bad_lines || 0); }, 0);
    var live = polledAt.current && Date.now() - polledAt.current < POLL_MS * 3;

    return h("div", { className: "nocap-board" },
      h("div", { className: "nocap-head" },
        h("div", null,
          h("div", { className: "nocap-title" }, h("span", { className: "nocap-title-cap" }, "🧢"), "Cap Board"),
          h("div", { className: "nocap-subtitle" },
            "Who makes the most false claims. Every 🧢 is a claim the turn's own tool output contradicted.")),
        h("div", { className: "nocap-live", title: "Polls every " + POLL_MS / 1000 + " s while this tab is visible" },
          h("span", { className: cn("nocap-live-dot", live && "nocap-live-on", err && "nocap-live-err") }),
          err ? "offline" : "live", h("span", { className: "nocap-dim", key: tick }, " · " + ago(data.generated_at)))),

      h("div", { className: "nocap-stats" },
        h(Stat, { label: "Replies checked", value: t.replies || 0, sub: (t.agents || 0) + " agent(s) · " + (data.models || []).length + " model(s)" }),
        h(Stat, { label: "Claims", value: t.claims || 0, sub: "every claim judged, stamped or not" }),
        h(Stat, { label: "🧢 Caps", value: t.cap || 0, tone: "cap", sub: "cap rate " + pct(t.cap_rate) }),
        h(Stat, { label: "🧾 Receipts", value: t.proven || 0, tone: "receipt", sub: "receipt rate " + pct(t.receipt_rate) }),
        h(Stat, { label: "🤔 No receipt", value: t.unsure || 0, tone: "unsure", sub: "unproven, not contradicted" }),
        leader ? h(Stat, { label: "Top capper", value: leader.name, tone: "cap", sub: pct(leader.cap_rate) + " of " + leader.claims + " claims" }) : null),

      h("div", { className: "nocap-toolbar" },
        h("div", { className: "nocap-seg", role: "tablist" }, [["agents", "Agents"], ["models", "Models"], ["skills", "Skills"]].map(function (x) {
          return h("button", { key: x[0], type: "button", role: "tab", "aria-selected": dim === x[0],
            className: cn("nocap-seg-btn", dim === x[0] && "nocap-seg-on"), onClick: function () { setDim(x[0]); } },
            x[1], h("span", { className: "nocap-seg-n" }, (data[x[0]] || []).length));
        })),
        h("div", { className: "nocap-filters" },
          h(Filter, { label: "Agent", plural: "agents", value: filters.agent, options: o.agents, onChange: setF("agent") }),
          h(Filter, { label: "Model", plural: "models", value: filters.model, options: o.models, onChange: setF("model") }),
          h(Filter, { label: "Skill", plural: "skills", value: filters.skill, options: o.skills, onChange: setF("skill") }))),

      h(Card, { className: "nocap-card" }, h(CardContent, { className: "nocap-card-body" },
        h(LeaderTable, { rows: rows, dim: dim, min: n, flash: flash }))),

      h(Card, { className: "nocap-card" }, h(CardContent, { className: "nocap-card-body" },
        h(Hall, { items: data.hall }))),

      h("div", { className: "nocap-foot" },
        h("span", null, "Cap rate = 🧢 ÷ claims · receipt rate = 🧾 ÷ claims · rates and ranks need ≥" + n + " claims (greyed rows show n) · trend: last 7 days vs the 7 before"),
        h("span", { className: "nocap-scope" }, scopeText(data.scope)),
        h("span", null, "Stores (read-only): " + (data.sources || []).map(function (s) { return s.label + " " + s.records; }).join(" · ") +
          (bad ? " · " + bad + " unreadable line(s) skipped" : ""))));
  }

  // Plain text from the server's scope (React escapes it): the board shows this profile only unless the
  // board.team_profiles setting opts in to the multi-profile team view.
  function scopeText(sc) {
    if (!sc) return "";
    if (sc.mode === "team") return "Team view (board.team_profiles): " + (sc.profiles || []).join(", ");
    return "This profile only (" + (sc.profile || "default") + ") · set board.team_profiles for a team view";
  }

  window.__HERMES_PLUGINS__.register("no-cap", CapBoard);
})();
