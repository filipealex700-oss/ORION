import time
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "daemon_autonomy.log"

def log(msg):
    """Escreve no log e no stdout."""
    timestamp = time.strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def ciclo_global():
    hora_atual = datetime.now().strftime("%H:%M:%S")
    log(f"[AUTÓNOMO] A iniciar ciclo de aprendizagem e código...")
    try:
        # Importar e correr o agente directamente
        sys.path.insert(0, str(BASE_DIR))
        import agente_autonomo
        agente_autonomo.ciclo_autonomo_codigo()
        agente_autonomo.pesquisa_automatica()  # Pesquisa automática sem ficheiros .txt
        agente_autonomo.processar_sugestoes_aprovadas()
        log("[AUTÓNOMO] Ciclo concluído. A aguardar...")
    except Exception as e:
        log(f"[ERRO NO CICLO] {e}")

if __name__ == "__main__":
    log("=== DAEMON AUTÓNOMO DO ORION ATIVO (TEMPO REAL) ===")
    log("Pressiona Ctrl+C para interromper.\n")
    while True:
        ciclo_global()
        time.sleep(300)  # 5 minutos em vez de 60 segundos