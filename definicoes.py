"""Definições do utilizador que mudam em execução (voz masculina/feminina, velocidade...)."""
import json
import os
import threading

from config import BASE


class Definicoes(dict):
    def __init__(self, cfg):
        super().__init__({
            "genero": cfg.get("genero_padrao", "feminino"),
            "velocidade": cfg.get("voz_velocidade", 175),
            "silencio": False,
            "voz_nome": cfg.get("voz_nome", ""),
        })
        self._caminho = os.path.join(BASE, "definicoes.json")
        self._l = threading.Lock()
        try:
            with open(self._caminho, encoding="utf-8") as f:
                self.update(json.load(f))
        except Exception:
            pass

    def set(self, chave, valor):
        with self._l:
            self[chave] = valor
            with open(self._caminho, "w", encoding="utf-8") as f:
                json.dump(dict(self), f, ensure_ascii=False, indent=2)
