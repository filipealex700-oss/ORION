"""Programador do ORION: cria, edita, lê e (com confirmação) executa código local.
Usa um modelo de código no Ollama. Os ficheiros ficam só na pasta 'projetos'."""
import datetime
import re
import shutil
import subprocess
from pathlib import Path

import ollama

import juiz
import seguranca
from config import BASE
from tools import CTX, ferramenta, pedir_confirmacao

PROJETOS = Path(BASE) / "projetos"
PROJETOS.mkdir(exist_ok=True)
EXT_OK = {".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".txt",
          ".ino", ".c", ".cpp", ".h", ".java", ".cs"}
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SISTEMA_CODIGO = (
    "És um programador sénior. Devolve APENAS o código completo e funcional do ficheiro pedido, "
    "dentro de um único bloco de código markdown, sem explicações antes nem depois. "
    "Escreve comentários curtos em português. Não uses bibliotecas desnecessárias.")


def _caminho(ficheiro):
    p = (PROJETOS / ficheiro).resolve()
    if PROJETOS.resolve() not in p.parents:
        raise ValueError("Só posso mexer em ficheiros dentro da pasta 'projetos'.")
    if p.suffix.lower() not in EXT_OK:
        raise ValueError(f"Extensão não permitida. Permitidas: {' '.join(sorted(EXT_OK))}")
    return p


def _gerar(sistema, utilizador):
    cfg = CTX["cfg"]
    modelo = cfg.get("modelo_codigo") or cfg["modelo_llm"]
    try:
        r = ollama.chat(model=modelo, options={"temperature": 0.2, "num_ctx": 8192}, keep_alive="2m",
                        messages=[{"role": "system", "content": sistema},
                                  {"role": "user", "content": utilizador}])
    except Exception as e:
        raise RuntimeError(f"Falha no modelo de código '{modelo}'. Corre: ollama pull {modelo} ({e})")
    txt = r["message"]["content"]
    m = re.search(r"```[\w+#-]*\n(.*?)```", txt, re.S)
    if m:
        return m.group(1).strip() + "\n"
    txt = re.sub(r"^```[\w+#-]*\n", "", txt.strip())  # bloco sem fecho (resposta cortada)
    return re.sub(r"\n```\s*$", "", txt).strip() + "\n"


def _abrir_vscode(p):
    try:
        subprocess.Popen(f'code "{p}"', shell=True, creationflags=SEM_JANELA)
    except Exception:
        pass


@ferramenta("criar_codigo",
            "Escreve um ficheiro de código novo (Python, JavaScript, HTML, Arduino .ino, C++...) "
            "com o modelo de código e guarda-o na pasta projetos. Não leia o código em voz alta.",
            {"ficheiro": "nome com extensão, ex: tarefas.py ou luz/luz.ino",
             "pedido": "descrição detalhada do que o código deve fazer"})
def criar_codigo(ficheiro, pedido):
    p = _caminho(ficheiro)
    if p.exists():
        return "Esse ficheiro já existe. Use editar_codigo ou escolha outro nome."
    p.parent.mkdir(parents=True, exist_ok=True)
    codigo = _gerar(SISTEMA_CODIGO, f"Ficheiro: {p.name}\nPedido: {pedido}")
    codigo, reg = _julgar(ficheiro, p, pedido, codigo)
    if not reg["sintaxe_ok"]:
        return f"Não criei o ficheiro: o código tem erros que a IA Juiz não conseguiu corrigir ({reg['motivo']})."
    p.write_text(codigo, encoding="utf-8")
    _abrir_vscode(p)
    return (f"Criado projetos/{ficheiro} com {codigo.count(chr(10))} linhas (tentei abrir no VS Code). "
            + juiz.frase(reg))


@ferramenta("editar_codigo",
            "Altera ou corrige um ficheiro de código existente na pasta projetos. Faz cópia de segurança.",
            {"ficheiro": "nome do ficheiro", "instrucao": "o que alterar ou o erro a corrigir"})
def editar_codigo(ficheiro, instrucao):
    p = _caminho(ficheiro)
    if not p.exists():
        return "Esse ficheiro não existe."
    original = p.read_text(encoding="utf-8")
    novo = _gerar(SISTEMA_CODIGO + " Recebes o ficheiro atual e uma instrução; devolve o ficheiro "
                  "COMPLETO já alterado.",
                  f"Ficheiro: {p.name}\n\nCÓDIGO ATUAL:\n```\n{original}\n```\n\nINSTRUÇÃO: {instrucao}")
    if len(original) > 200 and len(novo) < 0.3 * len(original):
        return "O resultado parece truncado, por isso não alterei o ficheiro."
    novo, reg = _julgar(ficheiro, p, instrucao, novo)
    if not reg["sintaxe_ok"]:
        return f"Não alterei o ficheiro: a nova versão tem erros que a IA Juiz não corrigiu ({reg['motivo']})."
    bak = p.with_name(f"{p.name}.{datetime.datetime.now():%Y%m%d-%H%M%S}.bak")
    shutil.copy2(p, bak)
    p.write_text(novo, encoding="utf-8")
    return f"Ficheiro atualizado. Cópia de segurança: {bak.name}. " + juiz.frase(reg)


def _julgar(ficheiro, p, pedido, codigo):
    """IA Juiz: o Gerador corrige o que o Crítico e as verificações estáticas apontarem."""
    cfg = CTX["cfg"]
    if not cfg.get("juiz", {}).get("ativo", True):
        return codigo, {"veredicto": "aprovado", "rondas": 0, "problemas": [], "sintaxe_ok": True, "motivo": ""}

    def corrigir(atual, problemas):
        lista = "\n".join(f"- [{x['gravidade']}] {x['descricao']}" for x in problemas)
        return _gerar(SISTEMA_CODIGO + " Recebes código e uma lista de problemas; devolve o ficheiro COMPLETO corrigido.",
                      f"Ficheiro: {p.name}\nPedido original: {pedido}\n\nCÓDIGO:\n```\n{atual}\n```\n\n"
                      f"PROBLEMAS A CORRIGIR:\n{lista}")
    return juiz.rever(cfg, ficheiro, pedido, codigo, p.suffix, corrigir)


@ferramenta("rever_codigo",
            "Pede à IA Juiz (crítico + juiz) uma revisão de um ficheiro da pasta projetos, sem o alterar.",
            {"ficheiro": "nome do ficheiro"})
def rever_codigo(ficheiro):
    p = _caminho(ficheiro)
    if not p.exists():
        return "Esse ficheiro não existe."
    _, reg = juiz.rever(CTX["cfg"], ficheiro, "revisão do ficheiro existente",
                        p.read_text(encoding="utf-8", errors="replace"), p.suffix)
    top = "; ".join(x["descricao"] for x in reg["problemas"][:3])
    return f"Veredicto: {reg['veredicto']}" + (f", pontuação {reg['pontuacao']:.0f}/10" if reg["pontuacao"] is not None else "") + \
        (f". Principais observações: {top}" if top else ". Sem observações.")


@ferramenta("ler_codigo", "Lê o conteúdo de um ficheiro da pasta projetos para o explicar ou analisar.",
            {"ficheiro": "nome do ficheiro"})
def ler_codigo(ficheiro):
    p = _caminho(ficheiro)
    if not p.exists():
        return "Esse ficheiro não existe."
    t = p.read_text(encoding="utf-8", errors="replace")
    return t[:4000] + ("\n[...truncado...]" if len(t) > 4000 else "")


@ferramenta("listar_projetos", "Lista os ficheiros de código criados na pasta projetos.")
def listar_projetos():
    fs = [str(f.relative_to(PROJETOS)) for f in PROJETOS.rglob("*")
          if f.is_file() and f.suffix.lower() in EXT_OK]
    return ", ".join(sorted(fs)[:50]) or "A pasta projetos está vazia."


@ferramenta("executar_codigo",
            "Executa um ficheiro Python (.py) da pasta projetos. Pede confirmação ao utilizador antes.",
            {"ficheiro": "nome do ficheiro .py"})
def executar_codigo(ficheiro):
    p = _caminho(ficheiro)
    if p.suffix.lower() != ".py":
        return "Só executo ficheiros Python (.py)."
    if not p.exists():
        return "Esse ficheiro não existe."

    seg = seguranca.obter(CTX["cfg"])
    avisos = [x["descricao"] for x in juiz.verificacoes_estaticas(p.read_text(encoding="utf-8", errors="replace"), ".py")]
    modo = seg.modo_sandbox()

    def correr():
        m, saida = seg.correr_isolado(p, p.parent, seguranca.python_exec())
        print(f"[executar_codigo] sandbox={m}\n{saida}")
        return f"(sandbox {m}) {saida}"

    onde = "num contentor Docker sem rede" if modo == "docker" else "num Python isolado, sem as tuas chaves secretas"
    extra = f" ATENÇÃO: {' '.join(avisos[:2])}" if avisos else ""
    return pedir_confirmacao(f"executar {ficheiro} {onde}, limite 30 s.{extra}", correr)
