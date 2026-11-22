"""ORION — assistente pessoal local (Windows).
python main.py              -> janela interativa
python main.py --texto      -> consola, só teclado (testes)
python main.py --consola    -> consola com microfone
python main.py --minimizado -> janela minimizada (usado ao iniciar com o Windows)
python main.py --preset equilibrado [--descarregar] -> ajusta os modelos ao teu hardware"""
import argparse
import os
import sys
import threading

import config


def _consola(cfg, texto):
    from nucleo import Orion
    sair = threading.Event()

    def emitir(t, x="", **k):
        if t == "ouvi":
            print(f"Ouvi: {x}" + (f"  [{k['conf'] * 100:.0f}%]" if k.get("origem") == "voz" else ""))
        elif t == "disse":
            print(f"{cfg['nome']} > {x}")
        elif t in ("acao", "sistema", "job", "aprendi"):
            print(f"[{t}] {x}")
        elif t == "sair":
            sair.set()
        elif t == "erro":
            print("ERRO:", x)
            sair.set()

    h = Orion(cfg, emitir, modo_texto=texto)
    try:
        h.iniciar()
    except Exception as e:
        sys.exit(str(e))
    if texto:
        def teclado():
            while not sair.is_set():
                try:
                    h.enviar_texto(input())
                except EOFError:
                    break
        threading.Thread(target=teclado, daemon=True).start()
    try:
        while not sair.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    h.parar()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--texto", action="store_true")
    ap.add_argument("--consola", action="store_true")
    ap.add_argument("--minimizado", action="store_true")
    ap.add_argument("--web", action="store_true", help="inicia interface web")
    ap.add_argument("--preset", help="leve | equilibrado | potente (ajusta modelos ao teu hardware)")
    ap.add_argument("--descarregar", action="store_true", help="com --preset: descarrega os modelos")
    args = ap.parse_args()
    if args.preset:
        import presets
        presets.aplicar(args.preset, args.descarregar)
        return

    if getattr(sys, "frozen", False) or sys.stdout is None:  # .exe sem consola: guarda o registo num ficheiro
        log = open(os.path.join(config.BASE, "orion.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    elif hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cfg = config.carregar()
    if args.web:
        import subprocess
        web_script = os.path.join(config.BASE, "orion_web", "app.py")
        subprocess.run([sys.executable, web_script, "--config", os.path.join(config.BASE, "config.json")])
    elif args.texto or args.consola:
        _consola(cfg, texto=args.texto)
    else:
        import gui
        gui.executar(cfg, minimizado=args.minimizado)


if __name__ == "__main__":
    main()
