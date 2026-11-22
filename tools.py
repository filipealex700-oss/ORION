"""Mãos e pés do ORION: ferramentas que controlam o Windows, o quarto e a memória."""
import ast
import base64
import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import uuid
import webbrowser
from pathlib import Path

import psutil

import ha
import seguranca
from config import BASE

try:
    import requests
    from bs4 import BeautifulSoup
    WEB_TOOLS_AVAILABLE = True
except ImportError:
    WEB_TOOLS_AVAILABLE = False

FERRAMENTAS = {}
CTX = {}  # preenchido pelo main: {"cfg":..., "memoria":...}

PROTEGIDOS = {"explorer.exe", "system", "svchost.exe", "winlogon.exe", "csrss.exe",
              "lsass.exe", "services.exe", "wininit.exe", "dwm.exe",
              "python.exe", "pythonw.exe", "ollama.exe", "ollama app.exe"}
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ferramenta(nome, descricao, parametros=None):
    def deco(fn):
        FERRAMENTAS[nome] = {"descricao": descricao, "parametros": parametros or {}, "fn": fn}
        return fn
    return deco


def executar(nome, args, origem="assistente"):
    f = FERRAMENTAS.get(nome)
    if not f:
        return f"Ferramenta desconhecida: {nome}"
    kwargs = dict(args or {})
    try:
        import inspect
        params = inspect.signature(f["fn"]).parameters
        if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
            # O LLM pequeno inventa nomes de argumentos: descarta os que a função não aceita
            kwargs = {k: v for k, v in kwargs.items() if k in params}
        r = f["fn"](**kwargs)
        r = str(r) if r is not None else "Feito."
    except TypeError as e:
        r = f"Argumentos inválidos: {e}"
    except Exception as e:
        r = f"Erro: {e}"
    if CTX.get("seguranca"):
        CTX["seguranca"].registar_acao(nome, args, r, origem)
    return r


# ---------------- confirmação de ações sensíveis ----------------
PENDENTE = {"descricao": None, "fn": None}


def pedir_confirmacao(descricao, fn):
    """Guarda uma ação para só correr depois do utilizador dizer 'sim'."""
    PENDENTE["descricao"], PENDENTE["fn"] = descricao, fn
    print(f"[confirmação pendente] {descricao}")
    return (f"AINDA NÃO EXECUTADO. Pergunte ao utilizador, numa frase, se confirma: {descricao}. "
            "A ação só corre se ele responder sim.")


def resolver_confirmacao(sim):
    fn = PENDENTE["fn"]
    PENDENTE["descricao"], PENDENTE["fn"] = None, None
    if not fn:
        return ""
    return str(fn()) if sim else "Cancelado."


# ---------------- pastas do Windows ----------------
def _desktop():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        p = os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0])
        if os.path.isdir(p):
            return Path(p)
    except Exception:
        pass
    return Path.home() / "Desktop"


def _pasta(nome):
    n = nome.lower().strip()
    if n in ("desktop", "ambiente de trabalho", "secretária", "secretaria"):
        return _desktop()
    if n in ("downloads", "transferências", "transferencias"):
        return Path.home() / "Downloads"
    if n in ("documentos", "documents"):
        return Path.home() / "Documents"
    p = Path(nome)
    if p.is_dir():
        return p
    raise ValueError(f"Pasta desconhecida: {nome}")


# ---------------- aplicações ----------------
@ferramenta("abrir_programa", "Abre uma aplicação do Windows.",
            {"nome": "nome da app, ex: chrome, vscode, spotify, calculadora"})
def abrir_programa(nome):
    chave = nome.lower().strip()
    cmd = CTX["cfg"]["programas"].get(chave)
    if cmd:
        subprocess.Popen(cmd, shell=True, creationflags=SEM_JANELA)
        return f"{nome} aberto."
    if re.search(r'[&|<>^%"]', nome):
        return "Nome inválido."
    subprocess.Popen(["cmd", "/c", "start", "", nome], creationflags=SEM_JANELA)
    return f"Pedido de abertura de {nome} enviado."


@ferramenta("fechar_programa", "Fecha uma aplicação em execução.",
            {"nome": "nome da app, ex: chrome, discord, steam"})
def fechar_programa(nome):
    chave = nome.lower().strip()
    alvo = CTX["cfg"]["processos"].get(chave, chave).lower()
    if not alvo.endswith(".exe"):
        alvo += ".exe"
    if alvo in PROTEGIDOS:
        return f"{alvo} é um processo protegido e não será fechado."
    n = 0
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() == alvo:
            try:
                p.terminate()
                n += 1
            except Exception:
                pass
    return f"{n} processo(s) de {nome} fechado(s)." if n else f"{nome} não estava a correr."


# ---------------- web ----------------
@ferramenta("pesquisar_web", "Pesquisa no Google pelo navegador.",
            {"consulta": "o que pesquisar"})
def pesquisar_web(consulta):
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(consulta))
    return f"Pesquisa aberta: {consulta}"


@ferramenta("abrir_site", "Abre um site no navegador.", {"url": "endereço do site"})
def abrir_site(url):
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    return f"{url} aberto."


@ferramenta("pesquisar_web_resultados", "Abre o Google no navegador DO UTILIZADOR (ele é que vê os resultados; "
            "você NÃO recebe os dados). Use só quando ele pedir para pesquisar ou mostrar algo no ecrã.",
            {"consulta": "o que pesquisar"})
def pesquisar_web_resultados(consulta):
    """Pesquisa na internet abrindo o navegador com os resultados."""
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(consulta))
    return (f"Pesquisa aberta no navegador para: {consulta}. O UTILIZADOR é que vê os resultados — "
            "você não recebeu nenhum dado. Se precisa da informação para responder, use pesquisar_respostas.")


@ferramenta("ler_pagina_web", "Lê e resume o conteúdo de uma página web.",
            {"url": "endereço da página"})
def ler_pagina_web(url):
    """Lê e resume o conteúdo de uma página web."""
    if not WEB_TOOLS_AVAILABLE:
        return "Ferramentas web não disponíveis. Instale: pip install requests beautifulsoup4"

    try:
        if not url.startswith("http"):
            url = "https://" + url

        response = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Remover scripts e estilos
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()

        # Extrair texto
        texto = soup.get_text()

        # Limpar espaços extras
        linhas = (line.strip() for line in texto.splitlines())
        texto = "\n".join(line for line in linhas if line)

        # Limitar tamanho
        max_chars = 5000
        if len(texto) > max_chars:
            texto = texto[:max_chars] + "... [conteúdo truncado]"

        return f"Conteúdo de {url}:\n\n{texto}"
    except Exception as e:
        return f"Erro ao ler página web: {e}"


_CONSULTA_GENERICA = {"preco", "precos", "valor", "quanto", "quanta", "como", "qual", "quais",
                      "onde", "quando", "porque", "sera", "qual-e", "diz", "diz-me"}


def _variantes_consulta(q):
    """O Bing falha quando a query começa por palavra genérica ('preço bitcoin' -> spam)
    ou é uma frase ('quanto custa bitcoin'). Devolve variantes com keywords primeiro."""
    import unicodedata
    def sem_acento(t):
        return "".join(c for c in unicodedata.normalize("NFD", t.lower())
                       if unicodedata.category(c) != "Mn")
    toks = q.split()
    variantes = []
    if len(toks) > 2:
        resto = list(toks)
        while resto and sem_acento(resto[0]).strip(".,?!:;\"'") in _CONSULTA_GENERICA:
            resto.pop(0)
        if resto and resto != toks:
            variantes.append(" ".join(resto))
    return variantes


@ferramenta("pesquisar_respostas", "Pesquisa na internet e DEVOLVE-TE os resultados com resumos — é assim que "
            "obténs dados para responder. Use SEMPRE que precisa da informação: preços atuais, notícias, "
            "resultados, estatísticas, qualquer facto que não saiba de cor. "
            "A 'consulta' deve ser palavras-chave curtas (ex.: 'bitcoin preço hoje'), nunca uma frase.",
            {"consulta": "palavras-chave do que pesquisar", "max_resultados": "número (por defeito 5)"})
def pesquisar_respostas(consulta="", max_resultados=5, **kw):
    """Pesquisa real: devolve títulos, URLs e excertos dos resultados (Bing)."""
    consulta = (consulta or "").strip()
    if not consulta:
        # O LLM pequeno inventa nomes de argumentos (ex.: "palavras_chave"): usa o 1º texto disponível
        for v in kw.values():
            if isinstance(v, str) and v.strip():
                consulta = v.strip()
                break
    if not consulta:
        consulta = (CTX.get("pedido_atual") or "").strip()
    if not consulta:
        return "Pesquisa sem consulta: chama novamente com o argumento 'consulta' preenchido."
    if not WEB_TOOLS_AVAILABLE:
        return "Ferramentas web não disponíveis. Instale: pip install requests beautifulsoup4"
    max_resultados = max(1, min(int(max_resultados or 5), 8))

    def buscar(q):
        r = requests.get("https://www.bing.com/search",
                         params={"q": q, "setlang": "pt", "cc": "pt"},
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"},
                         timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for res in soup.select("li.b_algo")[:max_resultados]:
            a = res.select_one("h2 a")
            sn = res.select_one(".b_caption p")
            if not a:
                continue
            url = a.get("href", "")
            m = re.search(r"[?&]u=a1([^&]+)", url)  # redirect do Bing -> URL real (base64)
            if m:
                try:
                    url = base64.urlsafe_b64decode(m.group(1) + "==").decode("utf-8", "ignore")
                except Exception:
                    pass
            out.append(f"- {a.get_text(' ', strip=True)}\n  {url}\n"
                       f"  {sn.get_text(' ', strip=True) if sn else ''}")
        return out

    import unicodedata as _ud
    def _norm_txt(t):
        return "".join(c for c in _ud.normalize("NFD", t.lower())
                       if _ud.category(c) != "Mn")

    def _score(resultados, consulta):
        """Fração dos tokens relevantes da consulta presentes nos resultados (deteta spam do Bing)."""
        toks = {t for t in re.findall(r"\w+", _norm_txt(consulta)) if len(t) > 2}
        if not toks:
            return 0.0
        texto = _norm_txt("\n".join(resultados))
        return sum(1 for t in toks if t in texto) / len(toks)

    try:
        out, melhor_score = [], -1.0
        for q in _variantes_consulta(consulta) + [consulta]:
            res = buscar(q)
            sc = _score(res, consulta)
            if sc > melhor_score:
                out, melhor_score = res, sc
            if melhor_score >= 0.5:
                break
        return ("\n".join(out) if out else
                "Sem resultados. Tenta pesquisar_web_resultados para abrir o Google no navegador.")
    except Exception as e:
        return f"Erro na pesquisa: {e}"


@ferramenta("preco_cripto", "Devolve o preço ATUAL de criptomoedas (Bitcoin, Ethereum, etc.) em euros e dólares. "
            "Use para perguntas de preço de cripto — mais fiável e rápido que pesquisa web.",
            {"moeda": "bitcoin | ethereum | solana | ... (por defeito bitcoin)"})
def preco_cripto(moeda="bitcoin"):
    ids = {"bitcoin": "bitcoin", "ethereum": "ethereum", "solana": "solana",
           "cardano": "cardano", "dogecoin": "dogecoin", "bnb": "binancecoin",
           "polkadot": "polkadot", "avalanche": "avalanche-2", "litecoin": "litecoin",
           "chainlink": "chainlink", "polygon": "matic-network"}
    cid = ids.get(str(moeda).lower().strip(), str(moeda).lower().strip())
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price",
                         params={"ids": cid, "vs_currencies": "eur,usd",
                                 "include_24hr_change": "true"}, timeout=15)
        d = r.json().get(cid)
        if not d:
            return f"Sem dados para '{moeda}'."
        variacao = d.get("eur_24h_change")
        var = f", {variacao:+.1f}% nas últimas 24h" if variacao is not None else ""
        return (f"{moeda}: {d['eur']:,.0f} EUR ({d['usd']:,.0f} USD){var}. "
                "Fonte: CoinGecko, agora mesmo.")
    except Exception as e:
        return f"Erro ao obter preço: {e}"


# ---------------- multimédia ----------------
@ferramenta("media", "Controla a música/vídeo em reprodução.",
            {"acao": "play_pause | proxima | anterior"})
def media(acao):
    import pyautogui
    teclas = {"play_pause": "playpause", "proxima": "nexttrack", "anterior": "prevtrack"}
    if acao not in teclas:
        return "Ação inválida."
    pyautogui.press(teclas[acao])
    return f"Media: {acao}."


@ferramenta("ajustar_volume", "Ajusta o volume do computador.",
            {"direcao": "mais | menos | mudo", "passos": "número de passos (cada um ≈2%), por defeito 5"})
def ajustar_volume(direcao, passos=5):
    import pyautogui
    tecla = {"mais": "volumeup", "menos": "volumedown", "mudo": "volumemute"}.get(direcao)
    if not tecla:
        return "Direção inválida."
    pyautogui.press(tecla, presses=1 if direcao == "mudo" else int(passos))
    return f"Volume: {direcao}."


# ---------------- informação ----------------
DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
        "sexta-feira", "sábado", "domingo"]


@ferramenta("hora_data", "Diz a data e hora atuais.")
def hora_data():
    a = datetime.datetime.now()
    return f"{DIAS[a.weekday()]}, {a:%d/%m/%Y}, {a:%H:%M}"


@ferramenta("estado_sistema", "Devolve CPU, RAM, disco e bateria do computador.")
def estado_sistema():
    r = psutil.virtual_memory()
    d = psutil.disk_usage(os.path.abspath(os.sep))
    txt = (f"CPU {psutil.cpu_percent(interval=0.5):.0f}%, "
           f"RAM {r.percent:.0f}% ({r.used / 2**30:.1f} de {r.total / 2**30:.1f} GB), "
           f"disco {d.percent:.0f}% usado")
    b = psutil.sensors_battery()
    if b:
        txt += f", bateria {b.percent:.0f}%"
    return txt


# ---------------- organização de ficheiros ----------------
CATEGORIAS = {
    "Imagens": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".heic"},
    "Documentos": {".pdf", ".doc", ".docx", ".txt", ".odt", ".rtf", ".md"},
    "Folhas de cálculo": {".xls", ".xlsx", ".csv", ".ods"},
    "Apresentações": {".ppt", ".pptx", ".odp"},
    "Vídeos": {".mp4", ".mkv", ".avi", ".mov", ".wmv"},
    "Áudio": {".mp3", ".wav", ".flac", ".m4a", ".ogg"},
    "Arquivos comprimidos": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Programas": {".exe", ".msi"},
    "Código": {".py", ".js", ".ts", ".html", ".css", ".json", ".java", ".c", ".cpp", ".cs"},
}
IGNORAR = {".lnk", ".url", ".ini"}
LOG_ORG = Path(BASE) / "organizar_log.json"


def _categoria(ext):
    for nome, exts in CATEGORIAS.items():
        if ext in exts:
            return nome
    return "Outros"


@ferramenta("organizar_pasta",
            "Organiza os ficheiros soltos de uma pasta em subpastas por tipo. Pode ser desfeito.",
            {"pasta": "desktop | downloads | documentos (por defeito desktop)"})
def organizar_pasta(pasta="desktop"):
    base = _pasta(pasta)
    movidos = []
    for f in base.iterdir():
        if not f.is_file() or f.suffix.lower() in IGNORAR:
            continue
        destino_dir = base / _categoria(f.suffix.lower())
        destino_dir.mkdir(exist_ok=True)
        destino = destino_dir / f.name
        i = 1
        while destino.exists():
            destino = destino_dir / f"{f.stem} ({i}){f.suffix}"
            i += 1
        shutil.move(str(f), str(destino))
        movidos.append([str(f), str(destino)])
    LOG_ORG.write_text(json.dumps(movidos, ensure_ascii=False), encoding="utf-8")
    return f"{len(movidos)} ficheiro(s) organizado(s) em {base.name}."


@ferramenta("desfazer_organizacao", "Desfaz a última organização de pasta.")
def desfazer_organizacao():
    if not LOG_ORG.exists():
        return "Não há nada para desfazer."
    movidos = json.loads(LOG_ORG.read_text(encoding="utf-8"))
    n = 0
    for origem, destino in reversed(movidos):
        if os.path.exists(destino) and not os.path.exists(origem):
            shutil.move(destino, origem)
            n += 1
    LOG_ORG.unlink()
    return f"{n} ficheiro(s) repostos."


@ferramenta("ler_ficheiro",
            "Lê o conteúdo de um ficheiro de texto do computador.",
            {"caminho": "caminho completo do ficheiro"})
def ler_ficheiro(caminho):
    """Lê o conteúdo de um ficheiro de texto."""
    try:
        caminho = Path(caminho)
        if seguranca.caminho_bloqueado(caminho):
            return "Bloqueado pela segurança: esse ficheiro contém segredos ou credenciais e não o vou ler."
        if not caminho.exists():
            return f"Ficheiro não encontrado: {caminho}"
        if not caminho.is_file():
            return f"Não é um ficheiro: {caminho}"

        # Verificar se é ficheiro de texto
        ext = caminho.suffix.lower()
        extensoes_texto = {".txt", ".md", ".py", ".js", ".html", ".css", ".json", ".xml",
                          ".csv", ".log", ".yaml", ".yml", ".ini", ".cfg", ".conf",
                          ".bat", ".sh", ".sql", ".r", ".rb", ".go", ".java", ".c", ".cpp",
                          ".h", ".hpp", ".cs", ".php", ".ts", ".tsx", ".jsx", ".vue"}

        if ext not in extensoes_texto:
            return f"Aviso: O ficheiro '{caminho}' pode não ser de texto. Extensão: {ext}"

        with open(caminho, "r", encoding="utf-8", errors="replace") as f:
            conteudo = f.read()

        # Limitar tamanho para não sobrecarregar
        max_chars = 10000
        if len(conteudo) > max_chars:
            conteudo = conteudo[:max_chars] + f"\n\n... [ficheiro truncado, mostrando primeiros {max_chars} caracteres de {len(conteudo)}]"

        return f"Conteúdo de {caminho}:\n\n{conteudo}"
    except Exception as e:
        return f"Erro ao ler ficheiro: {e}"


@ferramenta("listar_pasta",
            "Lista os ficheiros e pastas num diretório.",
            {"caminho": "caminho da pasta", "extensao": "opcional, ex: .py para filtrar"})
def listar_pasta(caminho, extensao=None):
    """Lista ficheiros numa pasta."""
    try:
        caminho = Path(caminho)
        if not caminho.exists():
            return f"Pasta não encontrada: {caminho}"
        if not caminho.is_dir():
            return f"Não é uma pasta: {caminho}"

        itens = []
        for item in caminho.iterdir():
            if extensao and item.suffix.lower() != extensao.lower():
                continue
            tipo = "[pasta]" if item.is_dir() else "[ficheiro]"
            tamanho = f" ({item.stat().st_size} bytes)" if item.is_file() else ""
            itens.append(f"{tipo} {item.name}{tamanho}")

        if not itens:
            return f"Pasta vazia ou sem ficheiros com extensão '{extensao}'."

        return f"Conteúdo de {caminho}:\n\n" + "\n".join(itens)
    except Exception as e:
        return f"Erro ao listar pasta: {e}"


@ferramenta("treinar_reconhecimento",
            "Analisa o feedback e treina automaticamente o reconhecimento de voz.")
def treinar_reconhecimento():
    """Analisa feedback negativo e melhora o reconhecimento automaticamente."""
    try:
        mem = CTX.get("memoria")
        if not mem:
            return "Memória não disponível."

        # Obter feedbacks recentes com notas baixas (1-2)
        feedbacks = mem.db.execute(
            "SELECT pergunta, resposta, comentario FROM feedback WHERE avaliacao <= 2 ORDER BY ts DESC LIMIT 5"
        ).fetchall()

        if not feedbacks:
            return "Não há feedback negativo recente para analisar."

        # Coletar todas as palavras únicas para adicionar em batch
        palavras_adicionar = set()

        for pergunta, resposta, comentario in feedbacks:
            # Se o comentário mencionar que percebeu mal, tentar extrair correção
            if comentario and ("percebeu" in comentario.lower() or "entendeu" in comentario.lower()):
                # Tentar extrair padrões do comentário
                palavras = re.findall(r'\b\w+\b', comentario.lower())
                for palavra in palavras:
                    if len(palavra) > 2:
                        palavras_adicionar.add(palavra)

            # Adicionar palavras das perguntas ao vocabulário
            palavras_pergunta = re.findall(r'\b\w+\b', pergunta.lower())
            for palavra in palavras_pergunta:
                if len(palavra) > 2:
                    palavras_adicionar.add(palavra)

        # Limitar a 50 palavras para evitar sobrecarga
        if len(palavras_adicionar) > 50:
            palavras_adicionar = set(list(palavras_adicionar)[:50])

        # Adicionar em batch para eficiência
        if palavras_adicionar:
            mem.db.executemany(
                "INSERT OR IGNORE INTO vocabulario(palavra) VALUES(?)",
                [(p,) for p in palavras_adicionar]
            )
            mem.db.commit()

        return f"Treino concluído. {len(palavras_adicionar)} palavras adicionadas ao vocabulário."
    except Exception as e:
        return f"Erro ao treinar reconhecimento: {e}"


# ---------------- modos ----------------
@ferramenta("ativar_modo", "Ativa um modo (programas, luzes, etc.), ex: estudo, cinema, jogo.",
            {"nome": "nome do modo"})
def ativar_modo(nome):
    cfg = CTX["cfg"]
    modo = cfg["modos"].get(nome.lower().strip())
    if not modo:
        return f"Modo desconhecido: {nome}. Modos: {', '.join(cfg.get('modos', {}).keys())}"
    for p in modo.get("fechar", []):
        fechar_programa(p)
    for p in modo.get("abrir", []):
        abrir_programa(p)
    for u in modo.get("urls", []):
        abrir_site(u)
    notas = []
    for passo in modo.get("ha", []):
        try:
            notas.append(ha.controlar(cfg, passo["dispositivo"], passo["acao"], passo.get("brilho")))
        except Exception as e:
            notas.append(f"Home Assistant: {e}")
    return f"Modo {nome} ativado. " + " ".join(notas)


# ---------------- Home Assistant ----------------
@ferramenta("controlar_dispositivo", "Liga/desliga luzes e tomadas do quarto (Home Assistant).",
            {"dispositivo": "nome, ex: luz quarto", "acao": "ligar | desligar | alternar",
             "brilho": "opcional, 1-100, só para luzes"})
def controlar_dispositivo(dispositivo, acao, brilho=None):
    return ha.controlar(CTX["cfg"], dispositivo, acao, brilho)


@ferramenta("ativar_cena", "Ativa uma cena do Home Assistant.", {"nome": "nome da cena"})
def ativar_cena(nome):
    return ha.cena(CTX["cfg"], nome)


# ---------------- memória ----------------
@ferramenta("guardar_memoria", "Guarda na memória de longo prazo uma preferência ou facto sobre o utilizador.",
            {"texto": "frase completa a guardar, ex: 'O utilizador prefere luz azul à noite'"})
def guardar_memoria(texto):
    return CTX["memoria"].guardar(texto)


@ferramenta("esquecer_memoria", "Apaga da memória algo que o utilizador pediu para esquecer.",
            {"texto": "assunto a esquecer"})
def esquecer_memoria(texto):
    return CTX["memoria"].esquecer(texto)


# ---------------- voz e definições ----------------
@ferramenta("mudar_genero", "Muda a voz e a forma de falar entre feminino (mulher) e masculino (homem).",
            {"genero": "feminino | masculino"})
def mudar_genero(genero):
    g = genero.lower().strip()
    g = {"mulher": "feminino", "feminina": "feminino", "homem": "masculino",
         "masculina": "masculino"}.get(g, g)
    if g not in ("feminino", "masculino"):
        return "Género inválido. Use feminino ou masculino."
    CTX["defs"].set("genero", g)
    return f"Voz e personalidade alteradas para {g}."


@ferramenta("ajustar_fala", "Faz a assistente falar mais devagar ou mais depressa.",
            {"direcao": "devagar | depressa"})
def ajustar_fala(direcao):
    v = int(CTX["defs"].get("velocidade", 175))
    v = max(110, v - 20) if direcao.lower().startswith("dev") else min(240, v + 20)
    CTX["defs"].set("velocidade", v)
    return f"Velocidade da fala: {v}."


# ---------------- Langflow ----------------
# Session ID fixo para manter conversação no mesmo chat do Langflow
_LANGFLOW_SESSION_ID = "orion-session-001"

@ferramenta("langflow_aprender",
            "Usa o Langflow para pesquisar informação na internet e aprender sobre um tópico.",
            {"topico": "o que quer aprender, ex: 'inteligência artificial'"})
def langflow_aprender(topico):
    """Usa o Langflow para pesquisar e aprender sobre um tópico."""
    import requests

    cfg = CTX.get("cfg", {})
    langflow_cfg = cfg.get("langflow", {})
    url = langflow_cfg.get("url", "http://localhost:7860")
    flow_id = langflow_cfg.get("flow_id", "")
    api_key = langflow_cfg.get("api_key", "")
    if not flow_id:
        return "Langflow sem flow_id configurado no config.json."

    endpoint = f"{url}/api/v1/run/{flow_id}"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    # Pedido específico para aprendizagem
    prompt = f"Pesquise informações atualizadas sobre: {topico}. Resuma os pontos principais em português de Portugal de forma concisa para aprendizagem."

    payload = {
        "input_value": prompt,
        "output_type": "text",
        "input_type": "chat",
        "session_id": _LANGFLOW_SESSION_ID + "-learn",
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()

        # Extrair texto da resposta
        texto_aprendido = ""
        if "outputs" in data and len(data["outputs"]) > 0:
            outputs = data["outputs"][0].get("outputs", [])
            if outputs and len(outputs) > 0:
                texto_aprendido = outputs[0].get("results", {}).get("message", {}).get("data", {}).get("text", "")

        if not texto_aprendido:
            texto_aprendido = str(data)

        # Guardar na memória de longo prazo
        memoria = CTX.get("memoria")
        if memoria and texto_aprendido:
            memoria.guardar(f"Aprendi sobre {topico}: {texto_aprendido}")
            return f"Aprendi sobre {topico}: {texto_aprendido}"

        return f"Pesquisa sobre {topico}: {texto_aprendido}"
    except Exception as e:
        return f"Erro ao aprender via Langflow: {e}"


@ferramenta("langflow_processo",
            "Executa um fluxo/processo do Langflow para processamento especializado.",
            {"mensagem": "texto para enviar ao fluxo"})
def langflow_processo(mensagem):
    """Envia uma mensagem para o fluxo do Langflow e retorna a resposta."""
    import requests

    cfg = CTX.get("cfg", {})
    langflow_cfg = cfg.get("langflow", {})
    url = langflow_cfg.get("url", "http://localhost:7860")
    flow_id = langflow_cfg.get("flow_id", "")
    api_key = langflow_cfg.get("api_key", "")  # vem do .env (ORION_LANGFLOW_API_KEY)
    if not flow_id:
        return "Langflow sem flow_id configurado no config.json."

    endpoint = f"{url}/api/v1/run/{flow_id}"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key

    # Usar session_id fixo para manter conversação no mesmo chat
    payload = {
        "input_value": mensagem,
        "output_type": "chat",
        "input_type": "chat",
        "session_id": _LANGFLOW_SESSION_ID,
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        data = response.json()
        # Extrair a mensagem de resposta do formato complexo do Langflow
        if "outputs" in data and len(data["outputs"]) > 0:
            outputs = data["outputs"][0].get("outputs", [])
            if outputs and len(outputs) > 0:
                message = outputs[0].get("results", {}).get("message", {}).get("data", {}).get("text", "")
                if message:
                    return message

        return str(data)
    except Exception as e:
        return f"Erro ao comunicar com Langflow: {e}"


# ---------------- Obsidian ----------------
@ferramenta("obsidian_ler",
            "Lê o conteúdo de uma nota do Obsidian antes de responder.",
            {"nome_nota": "nome da nota (com ou sem .md)"})
def obsidian_ler(nome_nota):
    """Lê uma nota do cofre do Obsidian."""
    cfg = CTX.get("cfg", {})
    obsidian_cfg = cfg.get("obsidian", {})

    if not obsidian_cfg.get("ativo", False):
        return "Obsidian não está ativo na configuração."

    vault_path = obsidian_cfg.get("vault_path")
    if not vault_path:
        return "Caminho do cofre Obsidian não configurado."

    try:
        from obsidian_bridge import ObsidianBridge
        bridge = ObsidianBridge(vault_path)
        conteudo = bridge.ler_nota(nome_nota)
        return f"Conteúdo da nota '{nome_nota}':\n\n{conteudo}"
    except Exception as e:
        return f"Erro ao ler nota do Obsidian: {e}"


@ferramenta("obsidian_escrever",
            "Cria ou substitui uma nota no Obsidian. Use se a informação for útil.",
            {"nome_nota": "nome da nota", "conteudo": "conteúdo Markdown", "subpasta": "subpasta opcional"})
def obsidian_escrever(nome_nota, conteudo, subpasta=""):
    """Escreve uma nota no cofre do Obsidian."""
    cfg = CTX.get("cfg", {})
    obsidian_cfg = cfg.get("obsidian", {})

    if not obsidian_cfg.get("ativo", False):
        return "Obsidian não está ativo na configuração."

    vault_path = obsidian_cfg.get("vault_path")
    if not vault_path:
        return "Caminho do cofre Obsidian não configurado."

    try:
        from obsidian_bridge import ObsidianBridge
        bridge = ObsidianBridge(vault_path)
        resultado = bridge.escrever_nota(nome_nota, conteudo, subpasta)
        return resultado
    except Exception as e:
        return f"Erro ao escrever nota no Obsidian: {e}"


@ferramenta("obsidian_adicionar",
            "Adiciona conteúdo ao final de uma nota existente no Obsidian.",
            {"nome_nota": "nome da nota", "texto": "texto a adicionar"})
def obsidian_adicionar(nome_nota, texto):
    """Adiciona conteúdo a uma nota existente do Obsidian."""
    cfg = CTX.get("cfg", {})
    obsidian_cfg = cfg.get("obsidian", {})

    if not obsidian_cfg.get("ativo", False):
        return "Obsidian não está ativo na configuração."

    vault_path = obsidian_cfg.get("vault_path")
    if not vault_path:
        return "Caminho do cofre Obsidian não configurado."

    try:
        from obsidian_bridge import ObsidianBridge
        bridge = ObsidianBridge(vault_path)
        resultado = bridge.adicionar_a_nota(nome_nota, texto)
        return resultado
    except Exception as e:
        return f"Erro ao adicionar à nota do Obsidian: {e}"


# ---------------- segurança ----------------
@ferramenta("estado_seguranca", "Diz o estado da segurança local: watchdog anti-ransomware, alertas e sandbox.")
def estado_seguranca():
    seg = CTX.get("seguranca") or seguranca.obter(CTX.get("cfg"))
    e = seg.estado()
    w = e["watchdog"]
    novos = [a["mensagem"] for a in e["alertas"] if not a["visto"]][:2]
    return (f"Watchdog {'ativo' if w['ativo'] else 'parado'} ({w['resumo'] or 'ainda sem verificação'}); "
            f"{e['alertas_por_ver']} alerta(s) por ver" + (f": {' | '.join(novos)}" if novos else "") +
            f"; sandbox de código: {e['sandbox']['modo']}.")


@ferramenta("verificar_integridade", "Verifica agora as pastas protegidas (HIPON.V3, Obsidian, projetos) contra ransomware.")
def verificar_integridade():
    seg = CTX.get("seguranca") or seguranca.obter(CTX.get("cfg"))
    r = seg.verificar()
    if r["primeira"]:
        return f"Primeira verificação: {r['ficheiros']} ficheiros registados como referência."
    return (f"{r['ficheiros']} ficheiros verificados: {r['novos']} novos, {r['alterados']} alterados, "
            f"{r['apagados']} apagados, {r['alertas']} alerta(s).")


@ferramenta("criar_backup", "Cria uma cópia de segurança .zip das pastas protegidas.")
def criar_backup():
    seg = CTX.get("seguranca") or seguranca.obter(CTX.get("cfg"))
    return seg.backup()


# ---------------- criação de novas ferramentas (com aprovação) ----------------
PENDENTES = Path(BASE) / "plugins_pendentes"
PLUGINS = Path(BASE) / "plugins"


@ferramenta("propor_ferramenta",
            "Escreve o código de uma NOVA ferramenta Python que o ORION ainda não tem. "
            "Fica pendente até o utilizador a aprovar no terminal. O código deve definir "
            "NOME (str), DESCRICAO (str), PARAMETROS (dict nome->descrição) e a função executar(**kwargs) que devolve texto.",
            {"nome": "nome_em_snake_case", "codigo": "código Python completo"})
def propor_ferramenta(nome, codigo):
    nome = re.sub(r"[^a-z0-9_]", "", nome.lower())
    if not nome:
        return "Nome inválido."
    ast.parse(codigo)  # falha se houver erros de sintaxe
    PENDENTES.mkdir(exist_ok=True)
    (PENDENTES / f"{nome}.py").write_text(codigo, encoding="utf-8")
    return (f"Ferramenta '{nome}' escrita e pendente. O utilizador tem de a rever e aprovar "
            "com 'python aprovar_ferramentas.py' antes de poder ser usada.")


def carregar_plugins():
    PLUGINS.mkdir(exist_ok=True)
    for f in PLUGINS.glob("*.py"):
        try:
            spec = importlib.util.spec_from_file_location(f.stem, f)
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            FERRAMENTAS[m.NOME] = {"descricao": m.DESCRICAO,
                                   "parametros": getattr(m, "PARAMETROS", {}),
                                   "fn": m.executar}
            print(f"[plugin] carregado: {m.NOME}")
        except Exception as e:
            print(f"[plugin] erro em {f.name}: {e}")
