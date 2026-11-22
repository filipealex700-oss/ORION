"""Gestão pessoal local: tarefas/trabalhos, candidaturas a emprego e carteira de ações.
Tudo em SQLite (orion_gestao.db), sem APIs. Os preços das ações são os que tu registas."""
import datetime
import os

from config import BASE
from dbutil import DBSeguro
from tools import ferramenta

db = DBSeguro(os.path.join(BASE, "orion_gestao.db"))
db.executescript("""
CREATE TABLE IF NOT EXISTS tarefas(
    id INTEGER PRIMARY KEY, titulo TEXT, prazo TEXT, estado TEXT DEFAULT 'pendente',
    projeto TEXT, criada TEXT);
CREATE TABLE IF NOT EXISTS candidaturas(
    id INTEGER PRIMARY KEY, empresa TEXT, cargo TEXT, estado TEXT, data_entrevista TEXT,
    link TEXT, notas TEXT, atualizada TEXT);
CREATE TABLE IF NOT EXISTS posicoes(
    ticker TEXT PRIMARY KEY, quantidade REAL, preco_medio REAL, preco_atual REAL, atualizado TEXT);
CREATE TABLE IF NOT EXISTS operacoes(
    id INTEGER PRIMARY KEY, ts TEXT, ticker TEXT, tipo TEXT, quantidade REAL, preco REAL);
""")
db.commit()

ESTADOS = ("a candidatar", "candidatado", "entrevista", "oferta", "aceite", "rejeitado")


def _agora():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _data(s):
    s = (s or "").strip()
    if not s:
        return ""
    try:
        datetime.datetime.fromisoformat(s)
    except ValueError:
        raise ValueError("Data inválida. Use AAAA-MM-DD (ou AAAA-MM-DD HH:MM).")
    return s


# ======================= TAREFAS / TRABALHOS =======================
@ferramenta("adicionar_tarefa", "Adiciona uma tarefa ou trabalho à lista de gestão.",
            {"titulo": "descrição da tarefa", "prazo": "opcional, AAAA-MM-DD", "projeto": "opcional"})
def adicionar_tarefa(titulo, prazo="", projeto=""):
    prazo = _data(prazo)
    db.execute("INSERT INTO tarefas(titulo, prazo, projeto, criada) VALUES(?,?,?,?)",
               (titulo.strip(), prazo, (projeto or "").strip(), _agora()))
    db.commit()
    return f"Tarefa adicionada: {titulo}" + (f" (prazo {prazo})" if prazo else "")


@ferramenta("listar_tarefas", "Lista tarefas/trabalhos.",
            {"estado": "pendente | concluida | todas (por defeito pendente)"})
def listar_tarefas(estado="pendente"):
    q = "SELECT id, titulo, prazo, projeto, estado FROM tarefas"
    args = ()
    if estado in ("pendente", "concluida"):
        q += " WHERE estado=?"
        args = (estado,)
    rows = db.execute(q + " ORDER BY prazo='', prazo, id", args).fetchall()
    if not rows:
        return "Sem tarefas."
    return "; ".join(f"{i}) {t or ''}" + (f" [prazo {p}]" if p else "") + (f" [{pr}]" if pr else "")
                     + ("" if e == "pendente" else " [concluída]") for i, t, p, pr, e in rows)


@ferramenta("concluir_tarefa", "Marca uma tarefa como concluída.",
            {"tarefa": "número da tarefa ou parte do título"})
def concluir_tarefa(tarefa):
    t = str(tarefa).strip()
    if t.isdigit():
        row = db.execute("SELECT id, titulo FROM tarefas WHERE id=? AND estado='pendente'",
                         (int(t),)).fetchone()
    else:
        row = db.execute("SELECT id, titulo FROM tarefas WHERE estado='pendente' AND titulo LIKE ? "
                         "ORDER BY id DESC", (f"%{t}%",)).fetchone()
    if not row:
        return "Não encontrei essa tarefa pendente."
    db.execute("UPDATE tarefas SET estado='concluida' WHERE id=?", (row[0],))
    db.commit()
    return f"Concluída: {row[1]}"


# ======================= EMPREGOS / CANDIDATURAS =======================
@ferramenta("adicionar_candidatura", "Regista uma candidatura a emprego.",
            {"empresa": "nome da empresa", "cargo": "cargo", "estado": f"um de: {', '.join(ESTADOS)}",
             "link": "opcional", "notas": "opcional"})
def adicionar_candidatura(empresa, cargo, estado="candidatado", link="", notas=""):
    estado = estado.lower().strip()
    if estado not in ESTADOS:
        return f"Estado inválido. Use: {', '.join(ESTADOS)}"
    db.execute("INSERT INTO candidaturas(empresa, cargo, estado, link, notas, atualizada) "
               "VALUES(?,?,?,?,?,?)", (empresa.strip(), cargo.strip(), estado, link, notas, _agora()))
    db.commit()
    return f"Candidatura registada: {cargo} na {empresa} ({estado})."


@ferramenta("atualizar_candidatura", "Atualiza o estado, entrevista ou notas de uma candidatura.",
            {"empresa": "nome (ou parte) da empresa", "estado": f"opcional: {', '.join(ESTADOS)}",
             "data_entrevista": "opcional, AAAA-MM-DD ou AAAA-MM-DD HH:MM", "notas": "opcional"})
def atualizar_candidatura(empresa, estado="", data_entrevista="", notas=""):
    row = db.execute("SELECT id, empresa, notas FROM candidaturas WHERE empresa LIKE ? "
                     "ORDER BY id DESC", (f"%{empresa.strip()}%",)).fetchone()
    if not row:
        return f"Não encontrei candidatura em {empresa}."
    if estado:
        estado = estado.lower().strip()
        if estado not in ESTADOS:
            return f"Estado inválido. Use: {', '.join(ESTADOS)}"
        db.execute("UPDATE candidaturas SET estado=? WHERE id=?", (estado, row[0]))
    if data_entrevista:
        db.execute("UPDATE candidaturas SET data_entrevista=? WHERE id=?",
                   (_data(data_entrevista), row[0]))
    if notas:
        db.execute("UPDATE candidaturas SET notas=? WHERE id=?",
                   (((row[2] or "") + " | " + notas).strip(" |"), row[0]))
    db.execute("UPDATE candidaturas SET atualizada=? WHERE id=?", (_agora(), row[0]))
    db.commit()
    return f"Candidatura da {row[1]} atualizada."


@ferramenta("listar_candidaturas", "Lista as candidaturas a emprego.",
            {"estado": "opcional, para filtrar"})
def listar_candidaturas(estado=""):
    q, args = "SELECT empresa, cargo, estado, data_entrevista FROM candidaturas", ()
    if estado:
        q += " WHERE estado=?"
        args = (estado.lower().strip(),)
    rows = db.execute(q + " ORDER BY id DESC", args).fetchall()
    if not rows:
        return "Sem candidaturas."
    return "; ".join(f"{e or ''} — {c or ''} [{s or ''}]" + (f" entrevista {d}" if d else "") for e, c, s, d in rows)


# ======================= CARTEIRA DE AÇÕES =======================
@ferramenta("registar_operacao", "Regista uma compra ou venda de ações na carteira.",
            {"ticker": "símbolo, ex: AAPL", "tipo": "compra | venda",
             "quantidade": "número de ações", "preco": "preço por ação"})
def registar_operacao(ticker, tipo, quantidade, preco):
    tk, tipo = ticker.upper().strip(), tipo.lower().strip()
    q, p = float(quantidade), float(preco)
    if tipo not in ("compra", "venda") or q <= 0 or p < 0:
        return "Dados inválidos (tipo compra/venda, quantidade > 0)."
    pos = db.execute("SELECT quantidade, preco_medio FROM posicoes WHERE ticker=?", (tk,)).fetchone()
    if tipo == "compra":
        nq = (pos[0] + q) if pos else q
        pm = ((pos[0] * pos[1] + q * p) / nq) if pos else p
        db.execute("INSERT INTO posicoes(ticker, quantidade, preco_medio, preco_atual, atualizado) "
                   "VALUES(?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET "
                   "quantidade=excluded.quantidade, preco_medio=excluded.preco_medio, "
                   "preco_atual=excluded.preco_atual, atualizado=excluded.atualizado",
                   (tk, nq, pm, p, _agora()))
        msg = f"Compra registada: {q:g} {tk} a {p:g}. Tens {nq:g} com preço médio {pm:.2f}."
    else:
        if not pos or pos[0] < q - 1e-9:
            return f"Não tens {q:g} {tk} registadas."
        nq = pos[0] - q
        ganho = (p - pos[1]) * q
        if nq <= 1e-9:
            db.execute("DELETE FROM posicoes WHERE ticker=?", (tk,))
        else:
            db.execute("UPDATE posicoes SET quantidade=?, preco_atual=?, atualizado=? WHERE ticker=?",
                       (nq, p, _agora(), tk))
        msg = f"Venda registada: {q:g} {tk} a {p:g}. Resultado realizado: {ganho:+.2f}."
    db.execute("INSERT INTO operacoes(ts, ticker, tipo, quantidade, preco) VALUES(?,?,?,?,?)",
               (_agora(), tk, tipo, q, p))
    db.commit()
    return msg


@ferramenta("atualizar_preco", "Atualiza manualmente o preço atual de uma ação da carteira.",
            {"ticker": "símbolo", "preco": "preço atual por ação"})
def atualizar_preco(ticker, preco):
    tk = ticker.upper().strip()
    cur = db.execute("UPDATE posicoes SET preco_atual=?, atualizado=? WHERE ticker=?",
                     (float(preco), _agora(), tk))
    db.commit()
    return f"Preço de {tk} atualizado para {float(preco):g}." if cur.rowcount else f"Não tens posição em {tk}."


def _carteira():
    rows = db.execute("SELECT ticker, quantidade, preco_medio, preco_atual, atualizado FROM posicoes "
                      "ORDER BY ticker").fetchall()
    custo = sum(q * pm for _, q, pm, _, _ in rows)
    valor = sum(q * pa for _, q, _, pa, _ in rows)
    return rows, custo, valor


@ferramenta("ver_carteira", "Mostra a carteira de ações com custo, valor e ganho/perda (com os preços registados).")
def ver_carteira():
    rows, custo, valor = _carteira()
    if not rows:
        return "A carteira está vazia."
    linhas = []
    for tk, q, pm, pa, upd in rows:
        pl = q * (pa - pm)
        linhas.append(f"{tk}: {q:g} ações, médio {pm:.2f}, atual {pa:.2f} (de {upd[:10]}), "
                      f"{pl:+.2f} ({(pa / pm - 1) * 100:+.1f}%)" if pm else f"{tk}: {q:g}")
    tot = valor - custo
    pct = (tot / custo * 100) if custo else 0
    return " | ".join(linhas) + f" || Total investido {custo:.2f}, valor {valor:.2f}, resultado {tot:+.2f} ({pct:+.1f}%)."


# ======================= RESUMO / BRIEFING =======================
def _resumo():
    hoje = datetime.date.today()
    partes = []
    pend = db.execute("SELECT titulo, prazo FROM tarefas WHERE estado='pendente'").fetchall()
    atrasadas = [t for t, p in pend if p and p[:10] < hoje.isoformat()]
    hoje_l = [t for t, p in pend if p[:10] == hoje.isoformat()]
    limite = (hoje + datetime.timedelta(days=3)).isoformat()
    breve = [t for t, p in pend if p and hoje.isoformat() < p[:10] <= limite]
    if atrasadas:
        partes.append(f"{len(atrasadas)} tarefa(s) em atraso: {', '.join(atrasadas[:3])}")
    if hoje_l:
        partes.append(f"para hoje: {', '.join(hoje_l[:3])}")
    if breve:
        partes.append(f"nos próximos 3 dias: {', '.join(breve[:3])}")
    if pend and not (atrasadas or hoje_l or breve):
        partes.append(f"{len(pend)} tarefa(s) pendente(s) sem prazo próximo")
    fim = (hoje + datetime.timedelta(days=7)).isoformat()
    ent = db.execute("SELECT empresa, data_entrevista FROM candidaturas WHERE data_entrevista<>'' "
                     "AND substr(data_entrevista,1,10) BETWEEN ? AND ? ORDER BY data_entrevista",
                     (hoje.isoformat(), fim)).fetchall()
    if ent:
        partes.append("entrevistas: " + ", ".join(f"{e or ''} em {d or ''}" for e, d in ent))
    return "; ".join(partes)


@ferramenta("resumo_do_dia", "Resumo de tarefas em atraso/para hoje e entrevistas próximas.")
def resumo_do_dia():
    return _resumo() or "Sem pendências."


def briefing_arranque():
    r = _resumo()
    return f"Resumo: {r}." if r else ""
