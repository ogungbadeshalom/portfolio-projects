/*! analytics.js — drop-in browser SDK for the Analytics pipeline.
 *
 * Usage:
 *   <script src="https://your-host/sdk/analytics.js" async></script>
 *   <script>
 *     window.analytics.init({ endpoint: "https://your-host" });   // optional
 *     window.analytics.track({ event: "click", properties: { url: ... } });
 *   </script>
 *
 * Out of the box it fires an auto `page_view` event on load, a stable
 * (cookie-persisted) user/session id, and queues events so nothing is lost if
 * the script loads before the server is reachable. Send is fire-and-forget so
 * it never blocks the page.
 */
(function (global) {
  "use strict";

  var CONFIG = { endpoint: "", flushMs: 1000, batchSize: 20 };
  var QUEUE = [];
  var USER_ID = null;
  var SESSION_ID = null;

  function endpoint() {
    var e = CONFIG.endpoint || (global.location && global.location.origin) || "";
    return e.replace(/\/+$/, "");
  }

  function randomId() {
    return "id-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  }

  function getCookie(name) {
    var m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : null;
  }
  function setCookie(name, value, days) {
    var d = new Date();
    d.setTime(d.getTime() + (days * 86400) * 1000);
    document.cookie = name + "=" + encodeURIComponent(value) +
      "; expires=" + d.toUTCString() + "; path=/";
  }

  function ensureIdentity() {
    if (!USER_ID) {
      USER_ID = getCookie("analytics_user_id") || randomId();
      setCookie("analytics_user_id", USER_ID, 365);
    }
    if (!SESSION_ID) {
      SESSION_ID = getCookie("analytics_session_id") || randomId();
      setCookie("analytics_session_id", SESSION_ID, 1);
    }
  }

  function send() {
    if (!QUEUE.length) return;
    var batch = QUEUE.splice(0, CONFIG.batchSize);
    var body = JSON.stringify(batch);
    try {
      if (global.fetch) {
        fetch(endpoint() + "/api/track/batch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: body,
        }).catch(function () { reenqueue(batch); });
      } else if (global.XMLHttpRequest) {
        var xhr = new XMLHttpRequest();
        xhr.open("POST", endpoint() + "/api/track/batch", true);
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onerror = function () { reenqueue(batch); };
        xhr.send(body);
      }
    } catch (e) { reenqueue(batch); }
  }

  function reenqueue(batch) {
    QUEUE = batch.concat(QUEUE);
  }

  var timer = null;
  function scheduleFlush() {
    if (timer) return;
    timer = setInterval(function () { send(); timer = null; }, CONFIG.flushMs);
  }

  function api() {
    return {
      init: function (opts) {
        if (opts) {
          if (opts.endpoint != null) CONFIG.endpoint = opts.endpoint;
          if (opts.flushMs != null) CONFIG.flushMs = opts.flushMs;
          if (opts.batchSize != null) CONFIG.batchSize = opts.batchSize;
        }
        ensureIdentity();
        scheduleFlush();
        return api();
      },
      track: function (event, props) {
        ensureIdentity();
        var payload = {
          event: typeof event === "string" ? event : (event && event.event),
          user_id: USER_ID,
          session_id: SESSION_ID,
          properties: props || (event && event.properties) || {},
        };
        if (payload.event == null) { return; }
        QUEUE.push(payload);
        if (QUEUE.length >= CONFIG.batchSize) send();
        return api();
      },
      page: function () {
        return api().track("page_view", { url: global.location.href, referrer: document.referrer });
      },
    };
  }

  // Auto-init with anonymous identities and an automatic page_view.
  var ready = api();
  if (typeof define === "function" && define.amd) define(function () { return ready; });
  global.analytics = ready;
  if (global.document && document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { ready.init(); ready.page(); });
  } else {
    ready.init();
    ready.page();
  }
})(typeof window !== "undefined" ? window : globalThis);