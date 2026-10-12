/* Real-Time Chat — WebSocket client.
 *
 * Connects to /ws/rooms/{id}?token=... and renders the message/presence/
 * typing protocol. On a drop, it reconnects automatically and fetches any
 * missed messages (by last seen message id) via the REST history endpoint.
 */
(function () {
  "use strict";

  const roomId = document.body.dataset.roomId;
  const token = localStorage.getItem("chat_token");
  const username = localStorage.getItem("chat_username");

  const messagesEl = document.getElementById("messages");
  const onlineEl = document.getElementById("online-list");
  const typingEl = document.getElementById("typing");
  const inputEl = document.getElementById("msg-input");
  const sendBtn = document.getElementById("send");
  const backEl = document.getElementById("back-link");

  let ws = null;
  let reconnectTimer = null;
  let lastSeenId = 0;
  let typingTimeout = null;
  let joined = false;

  const statusEl = document.createElement("div");
  statusEl.className = "status";
  messagesEl.appendChild(statusEl);

  function setStatus(text) {
    statusEl.textContent = text;
  }

  function profileName(user) {
    return user === username ? "You" : user;
  }

  function appendMessage(data) {
    const row = document.createElement("div");
    row.className = "msg" + (data.user === username ? " own" : "");
    const who = document.createElement("div");
    who.className = "who";
    who.textContent = profileName(data.user || "?");
    if (data.ts) {
      const when = document.createElement("span");
      when.className = "when";
      when.textContent = new Date(data.ts * 1000).toLocaleTimeString();
      who.appendChild(when);
    }
    const body = document.createElement("div");
    body.textContent = data.text; // textContent keeps sanitized text inert
    row.appendChild(who);
    row.appendChild(body);
    messagesEl.appendChild(row);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    if (data.id && Number(data.id) > lastSeenId) {
      lastSeenId = Number(data.id);
    }
  }

  function renderOnline(list) {
    onlineEl.innerHTML = "";
    if (!list || list.length === 0) {
      const empty = document.createElement("div");
      empty.className = "online-user";
      empty.textContent = "No one else online";
      onlineEl.appendChild(empty);
      return;
    }
    list.forEach(function (user) {
      const node = document.createElement("div");
      node.className = "online-user";
      node.textContent = user;
      onlineEl.appendChild(node);
    });
  }

  function showTyping(user) {
    const label = user === username ? "You" : user;
    typingEl.textContent = label + " is typing…";
    if (typingTimeout) clearTimeout(typingTimeout);
    typingTimeout = setTimeout(function () {
      typingEl.textContent = "";
    }, 1200);
  }

  function handleServer(data) {
    if (!data) return;
    switch (data.type) {
      case "presence":
        renderOnline(data.online);
        break;
      case "join":
        setStatus(profileName(data.user) + " joined");
        break;
      case "leave":
        setStatus(profileName(data.user) + " left");
        break;
      case "message":
        appendMessage(data);
        setStatus("");
        break;
      case "typing":
        showTyping(data.user);
        break;
      case "error":
        setStatus(data.message || "Error");
        break;
      default:
        break;
    }
  }

  function send(payload) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  }

  function setupInput() {
    const text = () => inputEl.value;
    const clear = () => {
      inputEl.value = "";
      inputEl.focus();
    };

    function submit() {
      const t = text().replace(/\s+$/, "");
      if (!t) return;
      send({ type: "message", text: t });
      clear();
    }

    inputEl.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        submit();
      } else if (e.key !== "Shift") {
        send({ type: "typing" });
      }
    });
    sendBtn.addEventListener("click", submit);
  }

  async function fetchMissed() {
    try {
      const res = await fetch(
        "/api/rooms/" + roomId + "/messages?limit=50" +
        (lastSeenId ? "&before_id=" + lastSeenId : ""),
        { headers: { Authorization: "Bearer " + token } }
      );
      if (!res.ok) return;
      const msgs = await res.json();
      msgs.forEach(appendMessage);
    } catch (err) {
      /* non-fatal */
    }
  }

  function openSocket() {
    if (!token) {
      setStatus("Not authenticated. Please log in.");
      return;
    }
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = proto + "://" + location.host + "/ws/rooms/" + roomId + "?token=" +
      encodeURIComponent(token);
    setStatus("Connecting…");
    ws = new WebSocket(url);

    ws.onopen = function () {
      setStatus(lastSeenId ? "Reconnected" : "Connected");
      fetchMissed();
    };

    ws.onmessage = function (evt) {
      try {
        handleServer(JSON.parse(evt.data));
      } catch (err) {
        /* ignore malformed */
      }
    };

    ws.onclose = function () {
      setStatus("Connection lost — reconnecting…");
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(openSocket, 1000);
    };

    ws.onerror = function () {
      ws.close();
    };
  }

  // ---- boot ----
  setupInput();
  if (backEl) {
    backEl.textContent = "← Back to rooms";
    backEl.href = "/rooms";
  }
  if (!username) {
    setStatus("Not logged in.");
  } else {
    openSocket();
  }
})();