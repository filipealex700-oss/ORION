"""Skills locais: ficheiros .md na pasta 'skills' com instruções para tipos de trabalho.
Formato: 1.ª linha '# Nome'; 1.º parágrafo = quando usar; o resto = instruções.
Quando um pedido se parece com uma skill, as instruções entram no prompt."""
from pathlib import Path

import numpy as np


class Skills:
    def __init__(self, pasta, memoria, min_score=0.55):
        self.mem, self.min_score, self.itens = memoria, min_score, []
        Path(pasta).mkdir(exist_ok=True)
        for f in sorted(Path(pasta).glob("*.md")):
            linhas = f.read_text(encoding="utf-8").strip().splitlines()
            if not linhas:
                continue
            nome = linhas[0].lstrip("# ").strip() or f.stem
            corpo = "\n".join(linhas[1:]).strip()
            descr = corpo.split("\n\n")[0].strip() or nome
            try:
                self.itens.append((nome, corpo, memoria._emb(f"{nome}. {descr}")))
            except Exception:
                pass

    def buscar(self, consulta):
        if not self.itens:
            return None
        q = self.mem._emb(consulta)
        score, nome, corpo = max(((float(np.dot(q, e)), n, c) for n, c, e in self.itens), key=lambda x: x[0])
        return (nome, corpo) if score >= self.min_score else None
