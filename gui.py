"""Janela interativa do ORION (tkinter): vês o que ela ouve, o que diz, o estado, e controlas a voz."""
import queue
import shutil
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import arranque
import tools
from nucleo import Orion

C = {"fundo": "#0f1419", "painel": "#161d26", "texto": "#d6dde6", "azul": "#6cb6ff", "verde": "#7ee787",
     "cinza": "#8b949e", "laranja": "#f0b072", "roxo": "#c297ff", "vermelho": "#ff7b72"}
ESTADOS = {"a carregar": ("A carregar...", "laranja"), "pronto": ("À escuta (diz “ORION”)", "verde"),
           "a ouvir": ("A ouvir...", "azul"), "a transcrever": ("A perceber o que disseste...", "azul"),
           "a pensar": ("A pensar...", "roxo"), "a falar": ("A falar...", "verde"),
           "erro": ("Erro", "vermelho")}


class Janela:
    def __init__(self, cfg, minimizado=False):
        self.cfg = cfg
        self.q = queue.Queue()
        self.root = tk.Tk()
        self.root.title(cfg["nome"])
        self.root.geometry("1040x680")
        self.root.configure(bg=C["fundo"])
        self.root.protocol("WM_DELETE_WINDOW", self._fechar)
        self.orion = Orion(cfg, lambda t, x="", **k: self.q.put((t, x, k)))
        self._construir()
        if minimizado:
            self.root.iconify()
        threading.Thread(target=self._arranque, daemon=True).start()
        self.root.after(80, self._bombear)

    # ---------------------------------------------------------------- interface
    def _construir(self):
        r = self.root
        topo = tk.Frame(r, bg=C["painel"])
        topo.pack(fill="x")
        self.estado = tk.Label(topo, text="A carregar...", bg=C["painel"], fg=C["laranja"],
                               font=("Segoe UI", 14, "bold"), padx=12, pady=8)
        self.estado.pack(side="left")
        self.nivel = ttk.Progressbar(topo, length=140, maximum=100)
        self.nivel.pack(side="left", padx=8)
        self.voz_lbl = tk.Label(topo, text="", bg=C["painel"], fg=C["cinza"], font=("Segoe UI", 9))
        self.voz_lbl.pack(side="right", padx=12)

        ctrl = tk.Frame(r, bg=C["fundo"])
        ctrl.pack(fill="x", padx=10, pady=6)
        self.genero = tk.StringVar(value=self.cfg.get("genero_padrao", "feminino"))
        for txt, val in (("Mulher", "feminino"), ("Homem", "masculino")):
            tk.Radiobutton(ctrl, text=txt, value=val, variable=self.genero, command=self._mudar_genero,
                           bg=C["fundo"], fg=C["texto"], selectcolor=C["painel"],
                           activebackground=C["fundo"], activeforeground=C["texto"]).pack(side="left")
        tk.Label(ctrl, text="  Velocidade:", bg=C["fundo"], fg=C["texto"]).pack(side="left")
        self.vel = tk.Scale(ctrl, from_=120, to=230, orient="horizontal", length=130, bg=C["fundo"],
                            fg=C["texto"], highlightthickness=0, troughcolor=C["painel"])
        self.vel.set(175)
        self.vel.pack(side="left")
        self.vel.bind("<ButtonRelease-1>", lambda e: self._def("velocidade", int(self.vel.get())))
        self.v_mic, self.v_sil, self.v_arr = tk.BooleanVar(value=True), tk.BooleanVar(), tk.BooleanVar(value=arranque.ativo())
        for txt, var, cmd in (("Microfone", self.v_mic, self._mic), ("Só texto (sem voz)", self.v_sil, self._silencio),
                              ("Iniciar com o Windows", self.v_arr, self._arranque_win)):
            tk.Checkbutton(ctrl, text=txt, variable=var, command=cmd, bg=C["fundo"], fg=C["texto"],
                           selectcolor=C["painel"], activebackground=C["fundo"],
                           activeforeground=C["texto"]).pack(side="left", padx=6)
        for txt, cmd in (("Testar voz", self._testar_voz), ("Vozes", self._ver_vozes),
                         ("Aprovar ferramentas", self._aprovar)):
            ttk.Button(ctrl, text=txt, command=cmd).pack(side="right", padx=3)

        corpo = tk.Frame(r, bg=C["fundo"])
        corpo.pack(fill="both", expand=True, padx=10)
        esq = tk.Frame(corpo, bg=C["fundo"])
        esq.pack(side="left", fill="both", expand=True)
        tk.Label(esq, text="Conversa (o que ouvi e o que disse)", bg=C["fundo"], fg=C["cinza"]).pack(anchor="w")
        self.chat = self._texto(esq)
        dir_ = tk.Frame(corpo, bg=C["fundo"], width=330)
        dir_.pack(side="right", fill="both", padx=(8, 0))
        tk.Label(dir_, text="Ações e segundo plano", bg=C["fundo"], fg=C["cinza"]).pack(anchor="w")
        self.lado = self._texto(dir_, largura=38)

        base = tk.Frame(r, bg=C["fundo"])
        base.pack(fill="x", padx=10, pady=8)
        self.entrada = tk.Entry(base, bg=C["painel"], fg=C["texto"], insertbackground=C["texto"],
                                font=("Segoe UI", 11), relief="flat")
        self.entrada.pack(side="left", fill="x", expand=True, ipady=6)
        self.entrada.bind("<Return>", lambda e: self._enviar())
        ttk.Button(base, text="Enviar", command=self._enviar).pack(side="left", padx=6)

    def _texto(self, pai, largura=60):
        t = scrolledtext.ScrolledText(pai, wrap="word", width=largura, bg=C["painel"], fg=C["texto"],
                                      font=("Segoe UI", 10), relief="flat", state="disabled")
        t.pack(fill="both", expand=True)
        for tag, cor in (("ouvi", "azul"), ("fraco", "laranja"), ("ignorado", "cinza"), ("disse", "verde"),
                         ("acao", "cinza"), ("sistema", "laranja"), ("job", "roxo"), ("aprendi", "roxo")):
            t.tag_config(tag, foreground=C[cor])
        return t

    def _linha(self, widget, texto, tag):
        widget.configure(state="normal")
        widget.insert("end", f"[{time.strftime('%H:%M:%S')}] {texto}\n", tag)
        widget.configure(state="disabled")
        widget.see("end")

    # ---------------------------------------------------------------- eventos
    def _arranque(self):
        try:
            self.orion.iniciar()
        except Exception as e:
            self.q.put(("erro", str(e), {}))

    def _bombear(self):
        for _ in range(60):
            try:
                t, x, k = self.q.get_nowait()
            except queue.Empty:
                break
            self._evento(t, x, k)
        voz = getattr(self.orion, "voz", None)
        self.nivel["value"] = min(100, (getattr(voz, "nivel", 0) or 0) * 500)
        self.root.after(80, self._bombear)

    def _evento(self, t, x, k):
        nome = self.cfg["nome"]
        if t == "estado" and x in ESTADOS:
            txt, cor = ESTADOS[x]
            self.estado.configure(text=txt, fg=C[cor])
        elif t == "ouvi":
            if k.get("ignorado"):
                self._linha(self.chat, f"(ouvi, mas sem “{self.cfg['wake_word']}”) {x}", "ignorado")
            else:
                conf = k.get("conf", 1.0)
                pct = f"  [{conf * 100:.0f}% certeza]" if k.get("origem") == "voz" else ""
                fraco = k.get("origem") == "voz" and conf < self.cfg.get("confianca_minima", 0.45)
                self._linha(self.chat, f"Tu: {x}{pct}", "fraco" if fraco else "ouvi")
        elif t == "disse":
            self._linha(self.chat, f"{nome}: {x}", "disse")
        elif t == "sistema":
            self._linha(self.chat, x, "sistema")
        elif t in ("acao", "job", "aprendi"):
            self._linha(self.lado, x, t)
        elif t == "voz":
            self.voz_lbl.configure(text=f"Voz: {x}")
        elif t == "iniciado":
            d = self.orion.defs
            self.genero.set(d["genero"])
            self.vel.set(d["velocidade"])
            self.v_sil.set(bool(d["silencio"]))
        elif t == "erro":
            self.estado.configure(text="Erro", fg=C["vermelho"])
            messagebox.showerror(nome, x)
        elif t == "sair":
            self.root.after(1500, self._fechar)

    # ---------------------------------------------------------------- controlos
    def _def(self, chave, valor):
        if hasattr(self.orion, "defs"):
            self.orion.defs.set(chave, valor)

    def _mudar_genero(self):
        self._def("genero", self.genero.get())
        self._linha(self.chat, f"Voz e personalidade: {self.genero.get()}.", "sistema")

    def _mic(self):
        if hasattr(self.orion, "voz"):
            self.orion.voz.mic_on = self.v_mic.get()

    def _silencio(self):
        self._def("silencio", self.v_sil.get())

    def _arranque_win(self):
        try:
            arranque.definir(self.v_arr.get())
        except Exception as e:
            messagebox.showerror("Iniciar com o Windows", str(e))

    def _testar_voz(self):
        if hasattr(self.orion, "voz"):
            threading.Thread(target=self.orion.voz.falar,
                             args=("Olá. Esta é a minha voz. Consegue ouvir-me bem?",), daemon=True).start()

    def _ver_vozes(self):
        try:
            vozes = self.orion.voz.listar_vozes()
            linhas = [f"{v.get('nome', '?')}  ({v.get('genero', '?')}, idioma {v.get('lang', '?')})" for v in vozes]
            messagebox.showinfo("Vozes instaladas", "\n".join(linhas) + "\n\nIdioma 816 = português de Portugal, "
                                "416 = português do Brasil.\nPara mais vozes: Definições > Hora e idioma > Voz.")
        except Exception as e:
            messagebox.showerror("Vozes", str(e))

    def _enviar(self):
        t = self.entrada.get().strip()
        self.entrada.delete(0, "end")
        if t:
            self.orion.enviar_texto(t)

    def _aprovar(self):
        pend = sorted(tools.PENDENTES.glob("*.py")) if tools.PENDENTES.exists() else []
        if not pend:
            messagebox.showinfo("Ferramentas", "Não há ferramentas pendentes.")
            return
        for f in pend:
            self._rever(f)

    def _rever(self, f):
        win = tk.Toplevel(self.root)
        win.title(f"Rever ferramenta: {f.name}")
        win.geometry("760x560")
        tk.Label(win, text="Lê o código com atenção: depois de aprovado corre com as tuas permissões.",
                 fg=C["laranja"]).pack(pady=4)
        t = scrolledtext.ScrolledText(win, font=("Consolas", 10))
        t.insert("1.0", f.read_text(encoding="utf-8"))
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)

        def aprovar():
            tools.PLUGINS.mkdir(exist_ok=True)
            shutil.move(str(f), str(tools.PLUGINS / f.name))
            messagebox.showinfo("Aprovada", "Reinicia o ORION para a carregar.")
            win.destroy()

        def rejeitar():
            f.unlink()
            win.destroy()

        b = tk.Frame(win)
        b.pack(pady=6)
        ttk.Button(b, text="Aprovar", command=aprovar).pack(side="left", padx=6)
        ttk.Button(b, text="Rejeitar", command=rejeitar).pack(side="left", padx=6)
        win.transient(self.root)
        win.wait_window()

    def _fechar(self):
        self.orion.parar()
        self.root.destroy()


def executar(cfg, minimizado=False):
    Janela(cfg, minimizado).root.mainloop()
