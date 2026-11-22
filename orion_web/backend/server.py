"""Apenas para a pré-visualização na cloud: monta o painel do ORION em /api (no Windows usa-se main.py --web)."""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

import config  # noqa: E402

config.ler_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from fastapi import FastAPI  # noqa: E402

from orion_web.app import criar_app  # noqa: E402

painel = criar_app(sem_voz=True)
app = FastAPI()
app.mount("/api", painel)


@app.on_event("startup")
async def _arranque():
    await painel.router.startup()


@app.on_event("shutdown")
async def _fim():
    await painel.router.shutdown()
