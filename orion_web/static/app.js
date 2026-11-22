const $ = (id) => document.getElementById(id);
let token = sessionStorage.getItem("orion-token") || "";
let socket = null;
let promptStartTime = null;
let errorCount = 0;
let activityHistory = [];

function headers() {
  return {"Content-Type":"application/json", "X-ORION-TOKEN":token};
}

function setConnection(ok) {
  $("side-connection").textContent = ok ? "ONLINE" : "OFFLINE";
  $("side-connection").style.color = ok ? "var(--cyan)" : "var(--red)";
}

function stateText(s) {
  const names = {
    "a carregar":"INICIALIZANDO", "pronto":"ORION PRONTO", "a ouvir":"A ESCUTAR...",
    "a transcrever":"PROCESSANDO ÁUDIO", "a pensar":"ANALISANDO...", "a falar":"TRANSMITINDO...", "erro":"FALHA DE SISTEMA"
  };
  return names[s] || (s ? s.toUpperCase() : "DESCONHECIDO");
}

function setState(s) {
  document.body.setAttribute("data-state", s || "pronto");
  const txt = stateText(s);
  $("state-label").textContent = txt;
  $("side-state").textContent = txt;
  
  if (s === "a pensar") {
    promptStartTime = performance.now();
  }

  const bars = document.querySelectorAll(".bar");
  bars.forEach(bar => {
    if (s === "a ouvir" || s === "a falar") {
      bar.style.height = Math.floor(Math.random() * 85 + 15) + "%";
    } else {
      bar.style.height = "10%";
    }
  });
}

function addMessage(role, text, tps = null) {
  const wrap = document.createElement("div");
  wrap.className = "message " + role;
  const meta = document.createElement("div");
  meta.className = "message-meta";
  
  let metaHtml = role === "user" ? "<span>// OPERADOR</span>" : "<span>// ORION</span>";
  if (role === "assistant" && tps) {
    metaHtml += ` <span class="tps-tag">· ${tps} tok/s</span>`;
  }
  meta.innerHTML = metaHtml;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrap.append(meta, bubble);
  $("messages").append(wrap);
  $("messages").scrollTop = $("messages").scrollHeight;
}

function addActivity(text, type = "sistema") {
  const now = new Date().toLocaleTimeString();
  const entry = { text, type, time: now };
  activityHistory.unshift(entry);

  const item = document.createElement("div");
  item.className = "log-item";
  item.textContent = text;
  const list = $("activity");
  list.prepend(item);
  while (list.children.length > 8) list.lastElementChild.remove();

  if (type === "erro") {
    errorCount++;
    $("error-badge").textContent = errorCount;
    $("error-badge").classList.remove("hidden");
  }
  renderFullActivityLog();
}

function renderFullActivityLog(filter = "all") {
  const container = $("full-activity-log");
  if (!container) return;
  container.innerHTML = "";
  
  const filtered = activityHistory.filter(item => {
    if (filter === "all") return true;
    return item.type === filter;
  });

  filtered.forEach(item => {
    const el = document.createElement("div");
    el.className = `log-entry ${item.type}`;
    el.innerHTML = `<div class="timestamp">[${item.time}] ${item.type.toUpperCase()}</div><div>${item.text}</div>`;
    container.appendChild(el);
  });
}

function handleEvent(e) {
  const t = e.type, text = e.text || "";
  if (t === "estado") {
    setState(text);
  } else if (t === "ouvi") {
    if (!e.meta?.ignorado) {
      addMessage("user", text);
      promptStartTime = performance.now();
    }
    addActivity(e.meta?.ignorado ? "Áudio ignorado" : "Comando de voz recebido", "sistema");
  } else if (t === "disse") {
    let tpsFormatted = null;
    if (promptStartTime) {
      const durationSec = (performance.now() - promptStartTime) / 1000;
      const estimatedTokens = Math.max(1, Math.round(text.length / 4));
      const tps = (estimatedTokens / Math.max(durationSec, 0.2)).toFixed(1);
      tpsFormatted = tps;
      $("tps-label").textContent = `${tps} tok/s`;
      promptStartTime = null;
    }
    addMessage("assistant", text, tpsFormatted); 
    addActivity("Resposta gerada (" + (tpsFormatted ? tpsFormatted + " tok/s" : "concluída") + ")", "sistema");
  } else if (t === "voz") {
    $("voice-label").textContent = text || "Ativa"; 
    addActivity("Sintetizador de voz atualizado", "sistema");
  } else if (t === "erro") {
    addActivity("Erro no sistema: " + text, "erro");
    setState("erro");
  } else if (["acao","job","aprendi","sistema"].includes(t)) {
    addActivity(text || t, "sistema");
  } else if (t === "iniciado") {
    addActivity("Núcleo ORION ativo", "sistema");
  }
}

function connectSocket() {
  if (socket) socket.close();
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${proto}//${location.host}/ws?token=${encodeURIComponent(token)}`);
  socket.onopen = () => setConnection(true);
  socket.onmessage = (ev) => { try { handleEvent(JSON.parse(ev.data)); } catch {} };
  socket.onclose = () => { setConnection(false); setTimeout(connectSocket, 2500); };
  socket.onerror = () => socket.close();
}

async function enter() {
  const r = await fetch("/api/status", {headers:headers()});
  if (!r.ok) throw new Error("Acesso negado.");
  const s = await r.json();
  $("login").classList.add("hidden");
  $("app").classList.remove("hidden");
  setState(s.state);
  $("voice-label").textContent = s.voice || "—";
  connectSocket();
}

$("tab-chat-btn").addEventListener("click", () => {
  $("tab-chat-btn").classList.add("active");
  $("tab-activity-btn").classList.remove("active");
  $("tab-chat").classList.remove("hidden");
  $("tab-activity").classList.add("hidden");
});

$("tab-activity-btn").addEventListener("click", () => {
  $("tab-activity-btn").classList.add("active");
  $("tab-chat-btn").classList.remove("active");
  $("tab-activity").classList.remove("hidden");
  $("tab-chat").classList.add("hidden");
});

document.querySelectorAll(".filter-btn").forEach(btn => {
  btn.addEventListener("click", (e) => {
    document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
    e.target.classList.add("active");
    renderFullActivityLog(e.target.dataset.filter);
  });
});

$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  token = $("token").value.trim();
  sessionStorage.setItem("orion-token", token);
  try { await enter(); $("login-error").textContent = ""; }
  catch (e) { $("login-error").textContent = e.message; }
});

$("chat-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const field = $("message"), text = field.value.trim();
  if (!text) return;
  field.value = "";
  $("send").disabled = true;
  promptStartTime = performance.now();
  try {
    const r = await fetch("/api/chat", {method:"POST", headers:headers(), body:JSON.stringify({text})});
    if (!r.ok) throw new Error((await r.json()).detail || "Erro de envio");
    addActivity("Instrução enviada via formulário", "sistema");
  } catch(e) { addActivity("Erro de envio: " + e.message, "erro"); }
  finally { $("send").disabled = false; field.focus(); }
});

let isMuted = false;
$("mute-btn").addEventListener("click", async () => {
  try {
    const r = await fetch("/api/mute", {method:"POST", headers:headers()});
    if (r.ok) {
      const data = await r.json();
      isMuted = data.muted;
      $("mute-btn").textContent = isMuted ? "🔇" : "🎤";
      $("mute-btn").style.borderColor = isMuted ? "var(--red)" : "var(--cyan)";
      addActivity(isMuted ? "Microfone desativado" : "Microfone ativo", "sistema");
    }
  } catch(e) { addActivity("Falha no controlo do microfone", "erro"); }
});

// Modal de dispositivos de áudio
$("audio-device-btn").addEventListener("click", async () => {
  $("audio-device-modal").classList.remove("hidden");
  try {
    const r = await fetch("/api/audio/devices", {headers:headers()});
    if (r.ok) {
      const data = await r.json();
      const select = $("audio-device-select");
      select.innerHTML = "";
      if (data.devices && data.devices.length > 0) {
        data.devices.forEach(dev => {
          const opt = document.createElement("option");
          opt.value = dev.id;
          opt.textContent = dev.name + (dev.default ? " (Padrão)" : "");
          if (dev.default) opt.selected = true;
          select.appendChild(opt);
        });
      } else {
        const opt = document.createElement("option");
        opt.textContent = data.error || "Nenhum dispositivo encontrado";
        select.appendChild(opt);
      }
    }
  } catch(e) {
    addActivity("Erro ao carregar dispositivos: " + e.message, "erro");
  }
});

$("close-audio-modal").addEventListener("click", () => {
  $("audio-device-modal").classList.add("hidden");
});

$("save-audio-device").addEventListener("click", async () => {
  const deviceId = $("audio-device-select").value;
  if (!deviceId) {
    addActivity("Seleciona um dispositivo primeiro", "erro");
    return;
  }
  try {
    const r = await fetch("/api/audio/device", {
      method:"POST",
      headers:headers(),
      body:JSON.stringify({device_id: deviceId})
    });
    if (r.ok) {
      const data = await r.json();
      addActivity("Dispositivo de áudio definido: " + deviceId, "sistema");
      addActivity("Reinicia o ORION para aplicar mudanças", "sistema");
      $("audio-device-modal").classList.add("hidden");
    }
  } catch(e) {
    addActivity("Erro ao guardar dispositivo: " + e.message, "erro");
  }
});

setInterval(() => {
  const state = document.body.getAttribute("data-state");
  if (state === "a ouvir" || state === "a falar") {
    document.querySelectorAll(".bar").forEach(bar => {
      bar.style.height = Math.floor(Math.random() * 80 + 20) + "%";
    });
  }
}, 150);

(async () => {
  $("token").value = token;
  try { await enter(); } catch {}
})();