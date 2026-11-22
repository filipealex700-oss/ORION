"""Trabalho em segundo plano: tarefas agendadas e lembretes que correm sem estares presente.
Só usam ferramentas seguras (lista PERMITIDAS) e guardam um relatório para te contar depois."""
import datetime
import os
import re
import threading
import time
import unicodedata

from config import BASE
from dbutil import DBSeguro
from tools import CTX, ferramenta

# Nunca abrem/fecham programas, nem executam código, nem mexem em dispositivos sem estares presente.
PERMITIDAS = {"resumo_do_dia", "listar_tarefas", "listar_candidaturas", "ver_carteira", "hora_data",
              "estado_sistema", "guardar_memoria", "criar_codigo", "editar_codigo", "ler_codigo",
              "listar_projetos", "organizar_pasta", "desfazer_organizacao", "adicionar_tarefa",
              "rever_codigo", "estado_seguranca", "verificar_integridade", "criar_backup"}


def _norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if c and unicodedata.category(c) != "Mn")


def _ts(hora, amanha=False):
    h, m = map(int, hora.split(":"))
    agora = datetime.datetime.now()
    alvo = agora.replace(hour=h, minute=m, second=0, microsecond=0)
    if amanha:
        alvo += datetime.timedelta(days=1)
    elif alvo <= agora:
        alvo += datetime.timedelta(days=1)
    return alvo.timestamp()


def interpretar(quando):
    """-> (tipo, hora, intervalo_min, proxima_execucao)"""
    q = _norm(quando)
    m = re.search(r"cada\s+(\d+)\s*(min|hora|h)", q)
    if m:
        mins = int(m.group(1)) * (60 if m.group(2).startswith("h") else 1)
        if mins < 5:
            raise ValueError("Intervalo mínimo: 5 minutos.")
        return "intervalo", None, mins, time.time() + mins * 60
    if "agora" in q:
        return "unica", None, None, time.time()
    m = re.search(r"(\d{1,2})\s*[:h]\s*(\d{2})?", q)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if h > 23 or mi > 59:
            raise ValueError("Hora inválida.")
        hora = f"{h:02d}:{mi:02d}"
        unica = "uma vez" in q or "amanha" in q
        return ("unica" if unica else "diaria"), hora, None, _ts(hora, amanha="amanha" in q)
    raise ValueError("Formato inválido. Use: agora | HH:MM (todos os dias) | uma vez HH:MM | "
                     "amanhã HH:MM | cada N minutos/horas.")


class Autonomo:
    def __init__(self, cfg, emitir, ocupado, falar, criar_cerebro, ocioso=None):
        self.cfg, self.emitir, self.ocupado = cfg, emitir, ocupado
        self.falar, self.criar_cerebro, self.ocioso = falar, criar_cerebro, ocioso
        self.db = DBSeguro(os.path.join(BASE, "orion_jobs.db"))
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(
                id INTEGER PRIMARY KEY, nome TEXT, modo TEXT, tipo TEXT, quando TEXT,
                instrucao TEXT, hora TEXT, intervalo_min INTEGER, proxima REAL,
                ativo INTEGER DEFAULT 1, ultima REAL);
            CREATE TABLE IF NOT EXISTS resultados(
                id INTEGER PRIMARY KEY, ts REAL, job TEXT, texto TEXT, visto INTEGER DEFAULT 0);
        """)
        self.db.commit()
        self.ativo = False
        self._parar = threading.Event()

    # ---------------- agendamento ----------------
    def agendar(self, nome, instrucao, quando, modo="cerebro"):
        tipo, hora, intervalo, prox = interpretar(quando)
        self.db.execute("DELETE FROM jobs WHERE nome=?", (nome,))
        self.db.execute("INSERT INTO jobs(nome, modo, tipo, quando, instrucao, hora, intervalo_min, proxima) "
                        "VALUES(?,?,?,?,?,?,?,?)", (nome, modo, tipo, quando, instrucao, hora, intervalo, prox))
        self.db.commit()
        return datetime.datetime.fromtimestamp(prox).strftime("%d/%m %H:%M")

    # ---------------- ciclo ----------------
    def iniciar(self):
        self.ativo = True
        self._parar.clear()
        threading.Thread(target=self._loop, daemon=True, name="autonomo").start()

    def parar(self):
        self.ativo = False
        self._parar.set()

    def _loop(self):
        while not self._parar.wait(15):
            try:
                self._tick()
            except Exception as e:
                self.emitir("sistema", f"[segundo plano] erro: {e}")

    def _tick(self):
        if self.ocupado():
            return
        devidos = self.db.execute(
            "SELECT id, nome, modo, tipo, instrucao, hora, intervalo_min FROM jobs "
            "WHERE ativo=1 AND proxima<=? ORDER BY proxima", (time.time(),)).fetchall()
        for j in devidos:
            if self.ocupado():
                return
            self._correr(j)
        if not devidos and self.ocioso:
            self.ocioso()

    def _correr(self, j):
        jid, nome, modo, tipo, instrucao, hora, intervalo = j
        self.emitir("job", f"A executar '{nome}'...")
        try:
            if modo == "lembrete":
                texto = instrucao
                self.falar(texto)
            else:
                texto = self.criar_cerebro().responder(instrucao)
        except Exception as e:
            texto = f"Falhou: {e}"
        self.db.execute("INSERT INTO resultados(ts, job, texto) VALUES(?,?,?)", (time.time(), nome, texto))
        if tipo == "unica":
            self.db.execute("UPDATE jobs SET ativo=0, ultima=? WHERE id=?", (time.time(), jid))
        else:
            prox = _ts(hora) if tipo == "diaria" else time.time() + intervalo * 60
            self.db.execute("UPDATE jobs SET proxima=?, ultima=? WHERE id=?", (prox, time.time(), jid))
        self.db.commit()
        self.emitir("job", f"'{nome}' concluído: {texto[:200]}")

    # ---------------- resultados ----------------
    def relatorio_pendente(self):
        rows = self.db.execute("SELECT id, job, texto FROM resultados WHERE visto=0 "
                               "ORDER BY id LIMIT 4").fetchall()
        if not rows:
            return ""
        for r in rows:
            self.db.execute("UPDATE resultados SET visto=1 WHERE id=?", (r[0],))
        self.db.commit()
        partes = " ".join(f"{job or ''}: {(texto or '')[:140].rstrip('. ')}." for _, job, texto in rows)
        return f"Entretanto, em segundo plano, tratei de {len(rows)} coisa(s). {partes}"


# ======================= FERRAMENTAS =======================
def _a():
    return CTX["autonomo"]


@ferramenta("agendar_job",
            "Agenda um trabalho para correr em segundo plano, mesmo sem o utilizador presente. "
            "Só pode usar ferramentas seguras (resumos, listas, criar/editar código, organizar pastas).",
            {"nome": "nome curto do trabalho", "instrucao": "o que fazer, como se o utilizador pedisse",
             "quando": "agora | HH:MM (todos os dias) | uma vez HH:MM | amanhã HH:MM | cada N minutos/horas"})
def agendar_job(nome, instrucao, quando):
    return f"Trabalho '{nome}' agendado. Próxima execução: {_a().agendar(nome, instrucao, quando)}."


@ferramenta("agendar_lembrete", "Agenda um aviso falado a uma hora.",
            {"texto": "o que dizer", "quando": "HH:MM (todos os dias) | uma vez HH:MM | amanhã HH:MM | cada N minutos"})
def agendar_lembrete(texto, quando):
    prox = _a().agendar("lembrete: " + texto[:30], texto, quando, modo="lembrete")
    return f"Lembrete agendado para {prox}."


@ferramenta("listar_jobs", "Lista os trabalhos e lembretes agendados.")
def listar_jobs():
    rows = _a().db.execute("SELECT nome, modo, quando, proxima FROM jobs WHERE ativo=1 ORDER BY proxima").fetchall()
    if not rows:
        return "Não há trabalhos agendados."
    return "; ".join(f"{n} [{m}, {q}] próxima {datetime.datetime.fromtimestamp(p):%d/%m %H:%M}"
                     for n, m, q, p in rows)


@ferramenta("cancelar_job", "Cancela um trabalho ou lembrete agendado.", {"nome": "nome (ou parte) do trabalho"})
def cancelar_job(nome):
    cur = _a().db.execute("DELETE FROM jobs WHERE nome LIKE ?", (f"%{nome}%",))
    _a().db.commit()
    return f"{cur.rowcount} trabalho(s) cancelado(s)."


@ferramenta("ver_resultados", "Mostra o que foi feito em segundo plano (últimos resultados).")
def ver_resultados():
    rows = _a().db.execute("SELECT job, texto, ts FROM resultados ORDER BY id DESC LIMIT 5").fetchall()
    _a().db.execute("UPDATE resultados SET visto=1")
    _a().db.commit()
    if not rows:
        return "Ainda não há resultados."
    return " | ".join(f"{datetime.datetime.fromtimestamp(ts):%d/%m %H:%M} {j or ''}: {(t or '')[:300]}" for j, t, ts in rows)
