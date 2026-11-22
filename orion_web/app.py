"""Painel web do ORION / HIPON.V3 (FastAPI + página estática, sem passo de build).
python main.py --web   ->  http://127.0.0.1:8765
Acesso pela rede só com ORION_WEB_TOKEN (>= 24 caracteres) no .env."""
import asyncio
import collections
import hmac
import ipaddress
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
if str(RAIZ.parent) not in sys.path:
    sys.path.insert(0, str(RAIZ.parent))

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import config  # noqa: E402
import juiz  # noqa: E402
import routing  # noqa: E402
import seguranca  # noqa: E402

ESTATICO = Path(getattr(sys, "_MEIPASS", RAIZ.parent)) / "orion_web" / "static" if getattr(sys, "frozen", False) \
    else RAIZ / "static"
PLANO = ESTATICO.parent / "plano.json"


class Ponte:
    """Liga o núcleo do ORION (threads) aos clientes WebSocket (asyncio)."""

    def __init__(self, cfg, sem_voz=False):
        self.cfg, self.sem_voz = cfg, sem_voz
        self.orion = None
        self.estado_core = "parado"
        self.erro = ""
        self.estado = "a carregar"
        self.inicio = time.time()
        self.eventos = collections.deque(maxlen=400)
        self.seq = 0
        self.clientes = set()
        self.loop = None
        self._lock = threading.Lock()

    def emitir(self, tipo, texto="", **extra):
        with self._lock:
            self.seq += 1
            meta_clean = {k: v for k, v in extra.items() if isinstance(v, (str, int, float, bool, type(None)))}
            ev = {"id": self.seq, "ts": time.time(), "tipo": tipo, "type": tipo, "texto": str(texto),
                  "text": str(texto), "extra": meta_clean, "meta": meta_clean}
            self.eventos.append(ev)
        if tipo == "estado":
            self.estado = str(texto)
        elif tipo == "iniciado":
            self.estado_core = "ligado"
        elif tipo == "erro":
            self.estado_core, self.erro, self.estado = "erro", str(texto), "erro"
        if self.loop:
            self.loop.call_soon_threadsafe(asyncio.ensure_future, self._difundir(ev))

    async def _difundir(self, ev):
        for ws in list(self.clientes):
            try:
                await ws.send_json(ev)
            except Exception:
                self.clientes.discard(ws)

    def arrancar(self):
        if self.estado_core in ("a arrancar", "ligado"):
            return
        self.estado_core, self.erro = "a arrancar", ""
        threading.Thread(target=self._arrancar, daemon=True, name="core").start()

    def _arrancar(self):
        try:
            from nucleo import Orion
            self.orion = Orion(self.cfg, self.emitir, modo_texto=self.sem_voz)
            self.orion.iniciar()
        except Exception as e:
            self.orion = None
            self.emitir("erro", f"Núcleo do ORION não arrancou: {e}")


def _loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "testclient")


def _ollama():
    try:
        import ollama
        c = ollama.Client(timeout=2)
        modelos = sorted(m.model for m in c.list().models)
        try:
            ps = [{"nome": m.model, "vram_gb": round((m.size_vram or 0) / 2**30, 2),
                   "ram_gb": round(max(0, (m.size or 0) - (m.size_vram or 0)) / 2**30, 2)} for m in c.ps().models]
        except Exception:
            ps = []
        return {"ligado": True, "modelos": modelos, "carregados": ps}
    except Exception as e:
        return {"ligado": False, "modelos": [], "carregados": [], "erro": str(e)[:160]}


def criar_app(cfg=None, sem_voz=False, arrancar_core=True):
    cfg = cfg or config.carregar()
    ponte = Ponte(cfg, sem_voz)
    seg = seguranca.obter(cfg)
    import tools
    tools.CTX["seguranca"] = seg
    token = os.environ.get("ORION_WEB_TOKEN", "")
    app = FastAPI(title="ORION Painel", docs_url=None, redoc_url=None)
    app.state.ponte = ponte

    def autorizado(req_token):
        if not token:
            return True
        return bool(req_token) and hmac.compare_digest(str(req_token).encode(), token.encode())

    @app.middleware("http")
    async def guarda(request: Request, call_next):
        caminho, raiz = request.url.path, request.scope.get("root_path", "")
        if raiz and caminho.startswith(raiz):
            caminho = caminho[len(raiz):]
        if caminho.startswith("/api/") and caminho != "/api/auth":
            if not autorizado(request.headers.get("x-orion-token")):
                return JSONResponse({"detail": "Token inválido ou em falta."}, status_code=401)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        return resp

    @app.on_event("startup")
    async def _inicio():
        ponte.loop = asyncio.get_running_loop()
        seg.iniciar()
        if arrancar_core:
            ponte.arrancar()

    @app.on_event("shutdown")
    async def _fim():
        if ponte.orion:
            ponte.orion.parar()
        seg.parar()

    # ---------------- página ----------------
    @app.get("/")
    async def index():
        return FileResponse(ESTATICO / "index.html")

    app.mount("/static", StaticFiles(directory=str(ESTATICO)), name="static")

    # ---------------- autenticação ----------------
    @app.get("/api/auth")
    async def auth(request: Request):
        return {"token_necessario": bool(token), "autorizado": autorizado(request.headers.get("x-orion-token"))}

    # ---------------- configuração e compatibilidade frontend ----------------
    @app.get("/api/config")
    async def api_config():
        return {"tema": cfg.get("web", {}).get("tema", {})}

    @app.get("/api/status")
    async def api_status():
        o = ponte.orion
        voz = getattr(o, "voz", None) if o else None
        voz_nome = (getattr(voz, "_voz_atual", "") if voz else "") or "Ativa"
        mic_on = bool(getattr(voz, "mic_on", False))
        return {
            "state": ponte.estado,
            "estado": ponte.estado,
            "voice": voz_nome,
            "voz": voz_nome,
            "muted": not mic_on,
            "core": ponte.estado_core,
        }

    @app.post("/api/chat")
    async def api_chat(dados: dict = Body(...)):
        texto = str(dados.get("text") or dados.get("texto", "")).strip()[:2000]
        if not texto:
            raise HTTPException(400, "Texto vazio.")
        if not ponte.orion or ponte.estado_core != "ligado":
            raise HTTPException(503, ponte.erro or "O núcleo do ORION ainda não está ligado.")
        ponte.orion.enviar_texto(texto)
        return {"ok": True}

    @app.post("/api/mute")
    async def api_mute():
        o = ponte.orion
        voz = getattr(o, "voz", None) if o else None
        if not voz:
            return {"muted": False, "note": "Voz não inicializada"}
        voz.mic_on = not voz.mic_on
        return {"muted": not voz.mic_on}

    @app.get("/api/audio/devices")
    async def audio_devices():
        """Lista dispositivos de áudio disponíveis."""
        try:
            import sounddevice as sd
            devices = []
            for i, dev in enumerate(sd.query_devices()):
                if dev['max_input_channels'] > 0:
                    devices.append({
                        "id": i,
                        "name": dev['name'],
                        "channels": dev['max_input_channels'],
                        "default": i == sd.default.device[0]
                    })
            return {"devices": devices, "default": sd.default.device[0]}
        except ImportError:
            return {"devices": [], "error": "sounddevice não instalado"}
        except Exception as e:
            return {"devices": [], "error": str(e)[:200]}

    @app.post("/api/audio/device")
    async def set_audio_device(dados: dict = Body(...)):
        """Define o dispositivo de áudio para o microfone."""
        device_id = dados.get("device_id")
        if device_id is None:
            raise HTTPException(400, "device_id é obrigatório")
        # Guardar na config
        try:
            device_id = int(device_id)
        except (TypeError, ValueError):
            raise HTTPException(400, "device_id deve ser um número")
        cfg["audio_device"] = device_id
        # Notificar que precisa de reiniciar
        return {"ok": True, "device_id": device_id, "note": "Reinicia o ORION para aplicar mudanças"}

    # ---------------- estado / consola ----------------
    def _defs():
        if ponte.orion and hasattr(ponte.orion, "defs"):
            return ponte.orion.defs
        from definicoes import Definicoes
        return Definicoes(cfg)

    @app.get("/api/estado")
    async def estado():
        o = ponte.orion
        voz = getattr(o, "voz", None) if o else None
        d = dict(_defs())
        return {"nome": cfg.get("nome", "ORION"), "core": ponte.estado_core, "erro": ponte.erro,
                "estado": ponte.estado, "uptime": time.time() - ponte.inicio,
                "ollama": await run_in_threadpool(_ollama),
                "modo_texto": bool(getattr(o, "modo_texto", True)) if o else True,
                "mic": bool(getattr(voz, "mic_on", False)), "nivel": float(getattr(voz, "nivel", 0) or 0),
                "defs": {"genero": d.get("genero"), "velocidade": d.get("velocidade"),
                         "silencio": bool(d.get("silencio"))},
                "modelos": {"principal": cfg.get("modelo_llm"), "rapido": cfg.get("modelo_rapido"),
                            "codigo": cfg.get("modelo_codigo"), "whisper": cfg.get("whisper_modelo")},
                "vram_gb": cfg.get("vram_gb", 6)}

    @app.get("/api/eventos")
    async def eventos(desde: int = 0):
        return [e for e in list(ponte.eventos) if e["id"] > desde]

    @app.post("/api/enviar")
    async def enviar(dados: dict = Body(...)):
        texto = str(dados.get("texto") or dados.get("text", "")).strip()[:2000]
        if not texto:
            raise HTTPException(400, "Texto vazio.")
        if not ponte.orion or ponte.estado_core != "ligado":
            raise HTTPException(503, ponte.erro or "O núcleo do ORION ainda não está ligado.")
        ponte.orion.enviar_texto(texto)
        return {"ok": True}

    @app.post("/api/core/arrancar")
    async def core_arrancar():
        ponte.arrancar()
        return {"core": ponte.estado_core}

    @app.post("/api/definicoes")
    async def definicoes(dados: dict = Body(...)):
        d = _defs()
        if dados.get("genero") in ("feminino", "masculino"):
            d.set("genero", dados["genero"])
        if "velocidade" in dados:
            try:
                d.set("velocidade", max(110, min(240, int(dados["velocidade"]))))
            except (TypeError, ValueError):
                raise HTTPException(400, "Velocidade inválida.")
        if "silencio" in dados:
            d.set("silencio", bool(dados["silencio"]))
        voz = getattr(ponte.orion, "voz", None) if ponte.orion else None
        if "mic" in dados and voz:
            voz.mic_on = bool(dados["mic"])
        return {"ok": True, "defs": {k: d.get(k) for k in ("genero", "velocidade", "silencio")}}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        q_token = sock.query_params.get("token", "")
        if token:
            if not autorizado(q_token):
                try:
                    primeira = await asyncio.wait_for(sock.receive_text(), timeout=10)
                except Exception:
                    await sock.close(code=4401)
                    return
                if not autorizado(primeira):
                    await sock.close(code=4401)
                    return
        ponte.clientes.add(sock)
        try:
            for ev in list(ponte.eventos)[-80:]:
                await sock.send_json(ev)
            while True:
                await sock.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            ponte.clientes.discard(sock)

    # ---------------- router ----------------
    @app.get("/api/router")
    async def router():
        metr = {}
        o = ponte.orion
        if o and hasattr(o, "memoria"):
            metr = routing.metricas_rotas(o.memoria.db)
        else:
            try:
                from dbutil import DBSeguro
                metr = routing.metricas_rotas(DBSeguro(os.path.join(config.BASE, "orion_memoria.db")))
            except Exception:
                metr = {}
        rotas = []
        for rid, r in routing.rotas_config(cfg).items():
            m = metr.get(rid, {})
            rotas.append({"id": rid, "nome": r["nome"], "descricao": r["descricao"], "modelo": r["modelo"],
                          "ferramentas": r["ferramentas"], "pedidos": m.get("pedidos", 0),
                          "latencia": m.get("latencia"), "avaliacao": m.get("avaliacao")})
        carregados = await run_in_threadpool(routing.modelos_carregados)
        return {"rotas": rotas, "vram": {"orcamento_gb": cfg.get("vram_gb", 6), "carregados": carregados or [],
                                        "usado_gb": round(sum(x["vram_gb"] for x in carregados or []), 2),
                                        "saver_ativo": float(cfg.get("vram_gb", 6)) <= 8}}

    @app.post("/api/router/testar")
    async def router_testar(dados: dict = Body(...)):
        texto = str(dados.get("texto", "")).strip()
        if not texto:
            raise HTTPException(400, "Escreve uma frase para testar.")
        r = routing.classificar(cfg, texto, None, bool(cfg.get("modelo_rapido")))
        return {k: r[k] for k in ("rota", "nome", "modelo", "ferramentas", "motivo")}

    # ---------------- IA Juiz ----------------
    def _projetos():
        import codigo
        return codigo.PROJETOS

    @app.get("/api/juiz")
    async def juiz_hist():
        return {"revisoes": juiz.historico(), "config": cfg.get("juiz", {}),
                "modelo_gerador": cfg.get("modelo_codigo"),
                "modelo_critico": cfg.get("juiz", {}).get("modelo_critico") or cfg.get("modelo_llm")}

    @app.get("/api/juiz/ficheiros")
    async def juiz_ficheiros():
        import codigo
        p = _projetos()
        return sorted(str(f.relative_to(p)).replace("\\", "/") for f in p.rglob("*")
                      if f.is_file() and f.suffix.lower() in codigo.EXT_OK)[:300]

    @app.post("/api/juiz/rever")
    async def juiz_rever(dados: dict = Body(...)):
        import codigo
        try:
            p = codigo._caminho(str(dados.get("ficheiro", "")))
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not p.exists():
            raise HTTPException(404, "Esse ficheiro não existe.")
        _, reg = await run_in_threadpool(juiz.rever, cfg, str(dados["ficheiro"]), "revisão pedida no painel",
                                         p.read_text(encoding="utf-8", errors="replace"), p.suffix)
        seg.registar_acao("rever_codigo", {"ficheiro": dados["ficheiro"]}, reg["veredicto"], "painel")
        return reg

    # ---------------- segurança ----------------
    @app.get("/api/seguranca")
    async def seg_estado():
        e = seg.estado()
        e["segredos"] = config.estado_segredos(cfg) + [
            {"nome": "ORION_WEB_TOKEN", "secao": "web", "presente": bool(token), "origem": ".env" if token else "-"}]
        pend = []
        import tools
        if tools.PENDENTES.exists():
            for f in sorted(tools.PENDENTES.glob("*.py")):
                cod = f.read_text(encoding="utf-8", errors="replace")
                pend.append({"nome": f.stem, "codigo": cod[:20000],
                             "avisos": [x["descricao"] for x in juiz.verificacoes_estaticas(cod, ".py")]})
        e["pendentes"] = pend
        e["docker"] = shutil.which("docker") is not None
        return e

    @app.post("/api/seguranca/verificar")
    async def seg_verificar():
        return await run_in_threadpool(seg.verificar)

    @app.post("/api/seguranca/backup")
    async def seg_backup():
        return {"mensagem": await run_in_threadpool(seg.backup)}

    @app.post("/api/seguranca/alertas/vistos")
    async def seg_vistos():
        seg.marcar_vistos()
        return {"ok": True}

    @app.post("/api/ferramentas/{nome}/{acao}")
    async def ferramenta_decidir(nome: str, acao: str):
        import tools
        f = tools.PENDENTES / f"{nome}.py"
        if not re.fullmatch(r"[a-z0-9_]+", nome) or not f.exists():
            raise HTTPException(404, "Ferramenta pendente não encontrada.")
        if acao == "aprovar":
            tools.PLUGINS.mkdir(exist_ok=True)
            shutil.move(str(f), str(tools.PLUGINS / f.name))
            if ponte.orion:
                tools.carregar_plugins()
            seg.registar_acao("aprovar_ferramenta", {"nome": nome}, "aprovada", "painel")
            return {"ok": True, "mensagem": f"'{nome}' aprovada" + ("" if ponte.orion else "; reinicia o ORION para a carregar.")}
        if acao == "rejeitar":
            f.unlink()
            seg.registar_acao("rejeitar_ferramenta", {"nome": nome}, "rejeitada", "painel")
            return {"ok": True, "mensagem": f"'{nome}' rejeitada e apagada."}
        raise HTTPException(400, "Ação inválida.")

    # ---------------- plano ----------------
    @app.get("/api/plano")
    async def plano():
        if PLANO.exists():
            try:
                return json.loads(PLANO.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"etapas": [], "descricao": "Sem plano configurado."}

    return app


def executar(cfg=None, sem_voz=None, host=None, porta=None, cfg_path=None):
    import uvicorn
    if cfg_path and os.path.exists(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"[web] Erro ao ler config de {cfg_path}: {e}")
    cfg = cfg or config.carregar()
    web = cfg.get("web", {})
    host = host or web.get("host", "127.0.0.1")
    porta = int(porta or web.get("porta", 8765))
    token = os.environ.get("ORION_WEB_TOKEN", "")
    if not _loopback(host) and len(token) < 24:
        raise SystemExit("Para abrir o painel na rede define ORION_WEB_TOKEN no .env com pelo menos 24 caracteres.")
    sem_voz = web.get("sem_voz", False) if sem_voz is None else sem_voz
    print(f"Painel do ORION em http://{host}:{porta}")
    uvicorn.run(criar_app(cfg, sem_voz=sem_voz), host=host, port=porta, log_level="warning")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="caminho do ficheiro config.json")
    ap.add_argument("--host", help="endereço do host")
    ap.add_argument("--port", "--porta", type=int, help="porta do servidor")
    ap.add_argument("--sem-voz", action="store_true")
    a = ap.parse_args()
    executar(cfg_path=a.config, host=a.host, porta=a.port, sem_voz=a.sem_voz or None)
