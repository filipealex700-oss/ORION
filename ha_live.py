"""Casa em tempo real: ligação WebSocket permanente ao Home Assistant.
Recebe todos os estados no arranque e cada mudança ao instante (luzes, tomadas, sensores, portas...).
O ORION pode anunciar em voz mudanças das entidades em config.json > home_assistant > anunciar."""
import asyncio
import json
import threading
import time

DOMINIOS = {"light", "switch", "sensor", "binary_sensor", "climate", "cover", "lock", "media_player",
            "fan", "person", "input_boolean"}
ESTADOS_PT = {"on": "ligado", "off": "desligado", "open": "aberto", "closed": "fechado", "opening": "a abrir",
              "closing": "a fechar", "locked": "trancado", "unlocked": "destrancado", "home": "em casa",
              "not_home": "fora de casa", "playing": "a tocar", "paused": "em pausa", "idle": "parado",
              "unavailable": "indisponível", "unknown": "desconhecido"}
BINARIOS = {"door": ("aberta", "fechada"), "window": ("aberta", "fechada"), "motion": ("movimento", "sem movimento"),
            "occupancy": ("ocupado", "livre"), "moisture": ("água detetada", "seco"), "smoke": ("FUMO", "sem fumo"),
            "gas": ("GÁS", "sem gás"), "opening": ("aberto", "fechado")}


def estado_legivel(ent):
    s, a = ent.get("state", ""), ent.get("attributes", {})
    if ent["entity_id"].startswith("binary_sensor.") and a.get("device_class") in BINARIOS:
        on, off = BINARIOS[a["device_class"]]
        return on if s == "on" else off if s == "off" else ESTADOS_PT.get(s, s)
    if ent["entity_id"].startswith("light.") and s == "on" and a.get("brightness"):
        return f"ligada a {round(a['brightness'] / 255 * 100)}%"
    if a.get("unit_of_measurement"):
        return f"{s} {a['unit_of_measurement']}"
    return ESTADOS_PT.get(s, s)


class CasaViva:
    def __init__(self, cfg):
        self.cfg = cfg
        self.estados = {}
        self.mudancas = []
        self.ouvintes = []
        self.ligado = False
        self.erro = ""
        self.ultima_mudanca = None
        self.ativo = False
        self._lock = threading.Lock()

    def _ha(self):
        return self.cfg.get("home_assistant") or {}

    def configurado(self):
        h = self._ha()
        tok = str(h.get("token", ""))
        return bool(h.get("ativo") and h.get("url") and tok and not tok.startswith("COLA_AQUI"))

    def url_ws(self):
        u = self._ha()["url"].rstrip("/")
        return ("wss://" + u[8:] if u.startswith("https://") else "ws://" + u.removeprefix("http://")) + "/api/websocket"

    # ---------------- ciclo ----------------
    def iniciar(self):
        if self.ativo:
            return
        if not self.configurado():
            self.erro = "Home Assistant desligado ou sem token (config.json > home_assistant e ORION_HA_TOKEN no .env)."
            return
        self.ativo = True
        threading.Thread(target=lambda: asyncio.run(self._loop()), daemon=True, name="casa-viva").start()

    def parar(self):
        self.ativo = False

    async def _loop(self):
        espera = 2
        while self.ativo:
            try:
                await self._sessao()
                espera = 2
            except Exception as e:
                self.erro = f"Ligação ao Home Assistant perdida: {e}"
            self.ligado = False
            await asyncio.sleep(espera)
            espera = min(60, espera * 2)

    async def _sessao(self):
        import websockets
        async with websockets.connect(self.url_ws(), open_timeout=10, ping_interval=30, max_size=2**24) as ws:
            json.loads(await ws.recv())
            await ws.send(json.dumps({"type": "auth", "access_token": self._ha()["token"]}))
            r = json.loads(await ws.recv())
            if r.get("type") != "auth_ok":
                self.ativo = False
                raise RuntimeError("token do Home Assistant recusado")
            await ws.send(json.dumps({"id": 1, "type": "get_states"}))
            await ws.send(json.dumps({"id": 2, "type": "subscribe_events", "event_type": "state_changed"}))
            self.ligado, self.erro = True, ""
            self._emitir("sistema", "Ligado ao Home Assistant em tempo real.", None)
            while self.ativo:
                msg = json.loads(await ws.recv())
                if msg.get("id") == 1 and msg.get("type") == "result":
                    with self._lock:
                        self.estados = {e["entity_id"]: e for e in msg.get("result") or [] if self._interessa(e["entity_id"])}
                elif msg.get("type") == "event":
                    self._mudou(msg["event"].get("data") or {})

    def _interessa(self, eid):
        doms = set(self._ha().get("dominios") or DOMINIOS)
        return eid.split(".")[0] in doms

    def _mudou(self, d):
        eid, novo, velho = d.get("entity_id", ""), d.get("new_state"), d.get("old_state") or {}
        if not novo or not self._interessa(eid):
            return
        with self._lock:
            self.estados[eid] = novo
        if novo.get("state") == velho.get("state"):
            return  # só mudou um atributo (ex.: potência a cada segundo)
        nome = self.nome(novo)
        m = {"ts": time.time(), "entity_id": eid, "nome": nome, "de": velho.get("state"), "para": novo.get("state"),
             "texto": f"{nome}: {estado_legivel(novo)}"}
        with self._lock:
            self.mudancas = ([m] + self.mudancas)[:100]
        self.ultima_mudanca = m["ts"]
        self._emitir("casa", m["texto"], m)

    def _emitir(self, tipo, texto, m):
        anunciar = m is not None and self.deve_anunciar(m["entity_id"], m["nome"])
        for f in list(self.ouvintes):
            try:
                f(tipo, texto, m or {}, anunciar)
            except Exception:
                pass

    def deve_anunciar(self, eid, nome):
        lista = [str(x).lower() for x in self._ha().get("anunciar") or []]
        return eid.lower() in lista or nome.lower() in lista

    # ---------------- leitura ----------------
    @staticmethod
    def nome(ent):
        return (ent.get("attributes") or {}).get("friendly_name") or ent["entity_id"]

    def lista(self):
        with self._lock:
            ents = list(self.estados.values())
        return sorted(({"entity_id": e["entity_id"], "dominio": e["entity_id"].split(".")[0], "nome": self.nome(e),
                        "estado": e.get("state"), "legivel": estado_legivel(e), "desde": e.get("last_changed")}
                       for e in ents), key=lambda x: (x["dominio"], x["nome"].lower()))

    def procurar(self, nome):
        n = nome.lower().strip()
        alias = (self._ha().get("entidades") or {}).get(n)
        with self._lock:
            if alias and alias in self.estados:
                return self.estados[alias]
            for e in self.estados.values():
                if n == e["entity_id"].lower() or n in self.nome(e).lower():
                    return e
        return None

    def resumo(self):
        if not self.ligado:
            return self.erro or "Não estou ligado ao Home Assistant."
        ents = self.lista()
        luzes = [e["nome"] for e in ents if e["dominio"] == "light" and e["estado"] == "on"]
        abertos = [f"{e['nome']} {e['legivel']}" for e in ents if e["dominio"] == "binary_sensor" and e["estado"] == "on"]
        sensores = [f"{e['nome']} {e['legivel']}" for e in ents if e["dominio"] == "sensor"
                    and e["legivel"].split(" ")[-1] in ("°C", "%", "W", "ppm")][:4]
        partes = [f"luzes ligadas: {', '.join(luzes[:6])}" if luzes else "todas as luzes desligadas"]
        if abertos:
            partes.append("atenção a " + ", ".join(abertos[:4]))
        if sensores:
            partes.append(", ".join(sensores))
        return "; ".join(partes) + "."

    def estado(self):
        return {"configurado": self.configurado(), "ligado": self.ligado, "erro": self.erro,
                "url": self._ha().get("url", ""), "entidades": self.lista(), "mudancas": self.mudancas[:40],
                "anunciar": self._ha().get("anunciar") or []}


_INSTANCIA = None


def obter(cfg):
    global _INSTANCIA
    if _INSTANCIA is None:
        _INSTANCIA = CasaViva(cfg)
    return _INSTANCIA
