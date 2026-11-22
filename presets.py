"""Presets por hardware: python main.py --preset equilibrado [--descarregar]"""
import json
import os
import subprocess

from config import BASE


def aplicar(nome, descarregar=False):
    with open(os.path.join(BASE, "presets.json"), encoding="utf-8") as f:
        presets = json.load(f)
    if nome not in presets:
        raise SystemExit("Presets disponíveis: " + ", ".join(f"{k} ({v.get('descricao', 'sem descrição')})" for k, v in presets.items()))
    caminho = os.path.join(BASE, "config.json")
    with open(caminho, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.update(presets[nome]["config"])
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    modelos = list(dict.fromkeys(m for m in (cfg.get("modelo_llm"), cfg.get("modelo_rapido"),
                                             cfg.get("modelo_codigo"), cfg.get("modelo_embeddings")) if m))
    print(f"Preset '{nome}' aplicado ao config.json ({presets[nome]['descricao']}).")
    for m in modelos:
        print(f"  ollama pull {m}")
        if descarregar:
            subprocess.run(["ollama", "pull", m])
    if not descarregar:
        print("Corre os comandos acima (ou repete com --descarregar).")
