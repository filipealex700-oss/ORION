"""Segurança local do ORION (camada 1 do Master Plan HIPON.V3).
- Auditoria: cada ferramenta executada fica registada (com segredos mascarados).
- Guarda de caminhos: o LLM não pode ler ficheiros sensíveis (.env, chaves, palavras-passe do navegador...).
- Watchdog anti-ransomware: vigia as pastas protegidas (HIPON.V3, Obsidian, projetos) e alerta em
  alterações em massa, extensões de ransomware, notas de resgate ou ficheiros de texto que ficaram cifrados.
- Sandbox: código gerado corre em Docker sem rede (se existir) ou num Python isolado sem segredos.
- Backups: cópia .zip versionada das pastas protegidas."""
import datetime
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

from config import BASE
from dbutil import DBSeguro

SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
EXT_RANSOM = {".locked", ".encrypted", ".crypt", ".crypted", ".enc", ".wncry", ".wnry", ".ryk",
              ".lockbit", ".cerber", ".locky", ".zepto", ".crab", ".conti", ".akira", ".pay2key"}
NOTAS_RESGATE = re.compile(r"(readme.*(decrypt|restore|recover)|how.?to.?(decrypt|restore|recover)|"
                           r"_readme|decrypt.?files|restore.?files|!!!)", re.I)
EXT_TEXTO = {".md", ".txt", ".py", ".json", ".js", ".ts", ".html", ".css", ".csv", ".ino", ".c",
             ".cpp", ".h", ".yaml", ".yml", ".ini", ".bat"}
IGNORAR_DIRS = {".git", "__pycache__", "node_modules", "venv", "venv310", ".venv", ".obsidian",
                "modelos", "DataSET", "backups", "dist", "build"}
SENSIVEIS_NOMES = {".env", "id_rsa", "id_ed25519", "known_hosts", "login data", "cookies",
                   "web data", "key4.db", "logins.json", "credentials", "credentials.json",
                   "secrets.json", "sam", "system", "security", "ntuser.dat"}
SENSIVEIS_EXT = {".pem", ".key", ".pfx", ".p12", ".kdbx", ".ppk", ".ovpn", ".wallet"}
SENSIVEIS_DIRS = {".ssh", ".aws", ".gnupg", ".azure", ".kube", "microsoft\\credentials",
                  "microsoft\\protect", "system32\\config"}
CHAVES_SECRETAS = re.compile(r"(token|key|senha|password|secret|api)", re.I)


def caminho_bloqueado(caminho):
    """True se o ficheiro for sensível e o ORION não o deve ler nem enviar ao modelo."""
    alvo = Path(caminho).expanduser().resolve()
    p = str(alvo).lower().replace("/", "\\")
    nome = alvo.name.lower()
    if nome in SENSIVEIS_NOMES or nome.startswith(".env") or Path(nome).suffix in SENSIVEIS_EXT:
        return True
    return any(f"\\{d}\\" in p + "\\" for d in SENSIVEIS_DIRS)


def mascarar(args):
    if not isinstance(args, dict):
        return args
    return {k: ("***" if CHAVES_SECRETAS.search(str(k)) else (str(v)[:300] if v is not None else v))
            for k, v in args.items()}


def entropia(dados):
    if not dados:
        return 0.0
    cont = [0] * 256
    for b in dados:
        cont[b] += 1
    n = len(dados)
    return -sum(c / n * math.log2(c / n) for c in cont if c)


class Seguranca:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sc = cfg.get("seguranca", {})
        self.db = DBSeguro(os.path.join(BASE, "orion_seguranca.db"))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS auditoria(
                id INTEGER PRIMARY KEY, ts REAL, ferramenta TEXT, args TEXT, resultado TEXT, origem TEXT);
            CREATE TABLE IF NOT EXISTS alertas(
                id INTEGER PRIMARY KEY, ts REAL, gravidade TEXT, tipo TEXT, mensagem TEXT, visto INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS snapshot(
                caminho TEXT PRIMARY KEY, tamanho INTEGER, mtime REAL);
        """)
        self.db.commit()
        self.ouvintes = []
        self.ativo = False
        self._parar = threading.Event()
        self.ultima_verificacao = None
        self.ultimo_resumo = ""
        self._lock = threading.Lock()

    # ---------------- pastas protegidas ----------------
    def pastas(self):
        lista = list(self.sc.get("pastas_protegidas") or [])
        obs = (self.cfg.get("obsidian") or {}).get("vault_path")
        if obs:
            lista.append(obs)
        lista.append(os.path.join(BASE, "projetos"))
        vistos, out = set(), []
        for p in lista:
            k = os.path.normcase(os.path.abspath(p))
            if k not in vistos:
                vistos.add(k)
                out.append(p)
        return out

    # ---------------- auditoria ----------------
    def registar_acao(self, ferramenta, args, resultado, origem="assistente"):
        try:
            self.db.execute("INSERT INTO auditoria(ts, ferramenta, args, resultado, origem) VALUES(?,?,?,?,?)",
                            (time.time(), ferramenta, json.dumps(mascarar(args or {}), ensure_ascii=False),
                             str(resultado)[:500], origem))
            self.db.commit()
        except Exception as e:
            print(f"[segurança] auditoria falhou: {e}")

    def alerta(self, gravidade, tipo, mensagem):
        self.db.execute("INSERT INTO alertas(ts, gravidade, tipo, mensagem) VALUES(?,?,?,?)",
                        (time.time(), gravidade, tipo, mensagem))
        self.db.commit()
        for f in list(self.ouvintes):
            try:
                f(gravidade, mensagem)
            except Exception:
                pass

    def ao_alerta(self, cb):
        self.ouvintes.append(cb)

    # ---------------- watchdog ----------------
    def iniciar(self):
        if self.ativo or not self.sc.get("watchdog", True):
            return
        self.ativo = True
        self._parar.clear()
        threading.Thread(target=self._loop, daemon=True, name="watchdog").start()

    def parar(self):
        self.ativo = False
        self._parar.set()

    def _loop(self):
        intervalo = max(15, int(self.sc.get("intervalo_seg", 60)))
        while not self._parar.wait(intervalo):
            try:
                self.verificar()
            except Exception as e:
                print(f"[watchdog] erro: {e}")

    def _listar(self, pasta, limite=20000):
        out = {}
        for raiz, dirs, fs in os.walk(pasta):
            dirs[:] = [d for d in dirs if d not in IGNORAR_DIRS]
            for nome in fs:
                c = os.path.join(raiz, nome)
                try:
                    st = os.stat(c)
                except OSError:
                    continue
                out[c] = (st.st_size, st.st_mtime)
                if len(out) >= limite:
                    return out
        return out

    def verificar(self):
        """Compara o estado atual das pastas protegidas com o último e gera alertas."""
        with self._lock:
            antigo = {c: (t, m) for c, t, m in self.db.execute("SELECT caminho, tamanho, mtime FROM snapshot").fetchall()}
            atual = {}
            for p in self.pastas():
                if os.path.isdir(p):
                    atual.update(self._listar(p))
            primeira = not antigo
            mudados = [c for c, v in atual.items() if c in antigo and antigo[c] != v]
            novos = [c for c in atual if c not in antigo]
            apagados = [c for c in antigo if c not in atual]
            alertas = 0
            if not primeira:
                for c in novos + mudados:
                    nome = os.path.basename(c)
                    if Path(nome).suffix.lower() in EXT_RANSOM:
                        self.alerta("alta", "extensao_ransomware", f"Ficheiro com extensão de ransomware: {c}")
                        alertas += 1
                    elif NOTAS_RESGATE.search(nome) and Path(nome).suffix.lower() in {".txt", ".html", ".hta", ".md"}:
                        self.alerta("alta", "nota_resgate", f"Possível nota de resgate: {c}")
                        alertas += 1
                cifrados = [c for c in mudados if Path(c).suffix.lower() in EXT_TEXTO and self._parece_cifrado(c)]
                if cifrados:
                    self.alerta("alta", "ficheiro_cifrado",
                                f"{len(cifrados)} ficheiro(s) de texto parecem cifrados (ex.: {cifrados[0]})")
                    alertas += 1
                limiar = int(self.sc.get("limiar_alteracoes", 40))
                tocados = len(mudados) + len(apagados)
                if tocados >= limiar and tocados >= 0.3 * max(1, len(antigo)):
                    self.alerta("alta", "alteracao_massa",
                                f"{len(mudados)} alterados e {len(apagados)} apagados desde a última verificação")
                    alertas += 1
                elif tocados >= limiar:
                    self.alerta("media", "alteracao_massa", f"{tocados} ficheiros alterados/apagados de uma vez")
                    alertas += 1
            self.db.execute("DELETE FROM snapshot")
            self.db.executemany("INSERT INTO snapshot(caminho, tamanho, mtime) VALUES(?,?,?)",
                                [(c, t, m) for c, (t, m) in atual.items()])
            self.db.commit()
            self.ultima_verificacao = time.time()
            self.ultimo_resumo = (f"{len(atual)} ficheiros vigiados" + ("" if primeira else
                                  f", {len(novos)} novos, {len(mudados)} alterados, {len(apagados)} apagados"))
            return {"ficheiros": len(atual), "novos": len(novos), "alterados": len(mudados),
                    "apagados": len(apagados), "alertas": alertas, "primeira": primeira}

    @staticmethod
    def _parece_cifrado(caminho):
        try:
            with open(caminho, "rb") as f:
                dados = f.read(65536)
        except OSError:
            return False
        return len(dados) >= 512 and entropia(dados) > 7.5

    # ---------------- backups ----------------
    def backup(self):
        destino = Path(self.sc.get("pasta_backups") or os.path.join(BASE, "backups"))
        destino.mkdir(parents=True, exist_ok=True)
        zipf = destino / f"orion-backup-{datetime.datetime.now():%Y%m%d-%H%M%S}.zip"
        n = 0
        with zipfile.ZipFile(zipf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in self.pastas():
                if not os.path.isdir(p):
                    continue
                raiz = Path(p)
                for c in self._listar(p):
                    cp = Path(c)
                    if destino in cp.parents or cp.stat().st_size > 50 * 2**20:
                        continue
                    z.write(cp, f"{raiz.name}/{cp.relative_to(raiz)}")
                    n += 1
        manter = int(self.sc.get("backups_manter", 10))
        for velho in sorted(destino.glob("orion-backup-*.zip"))[:-manter]:
            velho.unlink()
        return f"Backup criado: {zipf.name} ({n} ficheiros)."

    # ---------------- sandbox ----------------
    def modo_sandbox(self):
        pedido = self.sc.get("sandbox", "auto")
        docker = shutil.which("docker") is not None
        if pedido == "docker" or (pedido == "auto" and docker):
            return "docker" if docker else "isolado"
        return "isolado"

    def correr_isolado(self, ficheiro, pasta, python, timeout=30):
        """Executa um .py sem rede (Docker) ou num Python isolado sem as tuas variáveis secretas."""
        modo = self.modo_sandbox()
        if modo == "docker":
            vol = str(Path(pasta).resolve())
            cmd = ["docker", "run", "--rm", "--network", "none", "--memory", "512m", "--cpus", "1",
                   "--pids-limit", "128", "--read-only", "--tmpfs", "/tmp", "-v", f"{vol}:/w:ro", "-w", "/w",
                   self.sc.get("imagem_docker", "python:3.11-slim"), "python", Path(ficheiro).name]
        else:
            if not python:
                return "isolado", "Não encontrei o Python instalado no Windows para executar o código."
            cmd = [python, "-I", str(ficheiro)]
        env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "WINDIR", "HOME", "USERPROFILE")
               if k in os.environ}
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            r = subprocess.run(cmd, cwd=str(pasta), capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout, env=env, creationflags=SEM_JANELA)
        except subprocess.TimeoutExpired:
            return modo, f"Interrompido: excedeu {timeout} segundos."
        saida = ((r.stdout or "") + (r.stderr or "")).strip()
        return modo, f"Código de saída {r.returncode}. " + (saida[-600:] or "Sem saída.")

    # ---------------- painel ----------------
    def estado(self):
        alertas = [{"id": i, "ts": ts, "gravidade": g, "tipo": t, "mensagem": m, "visto": bool(v)}
                   for i, ts, g, t, m, v in self.db.execute(
                       "SELECT id, ts, gravidade, tipo, mensagem, visto FROM alertas ORDER BY id DESC LIMIT 50").fetchall()]
        audit = [{"ts": ts, "ferramenta": f, "args": a, "resultado": r, "origem": o}
                 for ts, f, a, r, o in self.db.execute(
                     "SELECT ts, ferramenta, args, resultado, origem FROM auditoria ORDER BY id DESC LIMIT 60").fetchall()]
        return {
            "watchdog": {"ativo": self.ativo, "ultima_verificacao": self.ultima_verificacao,
                         "resumo": self.ultimo_resumo,
                         "pastas": [{"caminho": p, "existe": os.path.isdir(p)} for p in self.pastas()]},
            "alertas": alertas,
            "alertas_por_ver": sum(1 for a in alertas if not a["visto"]),
            "auditoria": audit,
            "sandbox": {"modo": self.modo_sandbox(), "pedido": self.sc.get("sandbox", "auto"),
                        "docker_disponivel": shutil.which("docker") is not None},
        }

    def marcar_vistos(self):
        self.db.execute("UPDATE alertas SET visto=1")
        self.db.commit()


_INSTANCIA = None


def obter(cfg=None):
    global _INSTANCIA
    if _INSTANCIA is None:
        from config import carregar
        _INSTANCIA = Seguranca(cfg or carregar())
    return _INSTANCIA


def python_exec():
    if getattr(sys, "frozen", False):
        return shutil.which("python") or shutil.which("py")
    return sys.executable
