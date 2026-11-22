import os
import time
import subprocess
import traceback
import sys
import requests
from pathlib import Path
import ollama

# Configurações do ambiente ORION
BASE_DIR = Path(__file__).resolve().parent
VAULT_DIR = BASE_DIR / "Vault" / "ORION"
PENDENTES_DIR = BASE_DIR / "orion_core" / "pendentes"
PLUGINS_DIR = BASE_DIR / "orion_core" / "plugins"
PESQUISAS_DIR = BASE_DIR / "orion_core" / "pesquisas"
PESQUISAS_CONCLUIDAS_DIR = BASE_DIR / "orion_core" / "pesquisas_concluidas"
SUGESTOES_DIR = BASE_DIR / "orion_core" / "sugestoes"
APROVADAS_DIR = BASE_DIR / "orion_core" / "aprovadas"
DATASETS_DIR = BASE_DIR / "datasets"
MODELO_CODIGO = "qwen2.5:3b"  # Modelo leve para economizar CPU

# Tópicos de pesquisa automática (reduzidos para economizar CPU)
TOPICOS_PESQUISA = [
    "Datasets de áudio em português para fine-tuning do Whisper",
    "Melhores práticas de fine-tuning do Whisper com LoRA",
    "Comparação de modelos Whisper - base vs small vs medium"
]

# Config Langflow
LANGFLOW_URL = "http://localhost:7860"  # Langflow corre na porta 7860
LANGFLOW_FLOW_ID = "88a874d9-2a2d-4446-ac15-949a3cf6bcf1"
LANGFLOW_API_KEY = os.environ.get("ORION_LANGFLOW_API_KEY", "")

# Garantir que as pastas existem
PENDENTES_DIR.mkdir(parents=True, exist_ok=True)
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
PESQUISAS_DIR.mkdir(parents=True, exist_ok=True)
PESQUISAS_CONCLUIDAS_DIR.mkdir(parents=True, exist_ok=True)
SUGESTOES_DIR.mkdir(parents=True, exist_ok=True)
APROVADAS_DIR.mkdir(parents=True, exist_ok=True)
DATASETS_DIR.mkdir(parents=True, exist_ok=True)

# Log file
LOG_FILE = BASE_DIR / "agente_autonomo.log"

def log(msg):
    """Escreve no log e no stdout."""
    timestamp = time.strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def pesquisar_na_web_via_langflow(termo_pesquisa):
    """Envia o termo de pesquisa para o fluxo do Langflow executar as ferramentas de Web Search/URL."""
    LANGFLOW_API_URL = f"{LANGFLOW_URL}/api/v1/run/{LANGFLOW_FLOW_ID}"
    headers = {"Content-Type": "application/json"}
    if LANGFLOW_API_KEY:
        headers["x-api-key"] = LANGFLOW_API_KEY
    
    payload = {
        "input_value": termo_pesquisa,
        "output_type": "chat",
        "input_type": "chat"
    }
    try:
        response = requests.post(LANGFLOW_API_URL, headers=headers, json=payload, timeout=60)
        if response.status_code == 200:
            data = response.json()
            # Extrai o resultado processado pelo agente no Langflow com acesso à web
            resultado = data.get("outputs", [{}])[0].get("outputs", [{}])[0].get("results", {}).get("message", {}).get("text", "")
            return resultado
        else:
            log(f"[ERRO LANGFLOW] Falha na API: {response.status_code} - {response.text}")
            return ""
    except Exception as e:
        log(f"[ERRO DE CONEXÃO LANGFLOW] {e}")
        return ""


def pesquisar_huggingface(termo_pesquisa):
    """Pesquisa datasets no HuggingFace Hub."""
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        
        # Procurar datasets de áudio/whisper relevantes
        datasets = api.list_datasets(search="whisper", limit=20)
        
        resultados = []
        for ds in datasets:
            # Filtrar apenas datasets relevantes para áudio/ASR
            if any(keyword in ds.id.lower() for keyword in ["whisper", "asr", "speech", "audio", "portuguese", "pt", "portuguese"]):
                resultados.append(f"Dataset: {ds.id}\n- Descrição: {getattr(ds, 'description', 'N/A')}\n- Downloads: {getattr(ds, 'downloads', 'N/A')}\n- Likes: {getattr(ds, 'likes', 'N/A')}\n")
        
        return "\n".join(resultados) if resultados else "Nenhum dataset relevante encontrado."
    except Exception as e:
        log(f"[ERRO HUGGINGFACE] {e}")
        return ""


def verificar_datasets_locais():
    """Verifica datasets locais disponíveis."""
    datasets_locais = []
    base_dir = BASE_DIR
    
    # Procurar pastas de datasets
    for pasta in ["DataSET", "datasets", "data", "mls_portuguese"]:
        caminho = base_dir / pasta
        if caminho.exists() and caminho.is_dir():
            datasets_locais.append(f"Dataset local encontrado: {caminho}")
            # Listar conteúdo
            for item in caminho.iterdir():
                if item.is_dir():
                    datasets_locais.append(f"  - Subpasta: {item.name}")
    
    # Verificar pasta whisper-portuguese-finetuned
    whisper_dir = base_dir / "whisper-portuguese-finetuned"
    if whisper_dir.exists():
        datasets_locais.append(f"Modelo Whisper fine-tuned: {whisper_dir}")
        
        # Verificar se tem dataset
        dataset_dir = whisper_dir / "dataset"
        if dataset_dir.exists():
            datasets_locais.append(f"  - Dataset: {dataset_dir}")
    
    return "\n".join(datasets_locais) if datasets_locais else "Nenhum dataset local encontrado."


def processar_pesquisas():
    """Processa ficheiros de pesquisa pendentes."""
    # Apenas ficheiros que não são resultados (não começam com 'resultado_')
    pesquisas = [f for f in list(PESQUISAS_DIR.glob("*.txt")) + list(PESQUISAS_DIR.glob("*.md")) 
                 if not f.name.startswith("resultado_")]
    log(f"Encontradas {len(pesquisas)} pesquisa(s) pendente(s)")
    
    for pesquisa_file in pesquisas:
        tema = pesquisa_file.read_text(encoding="utf-8", errors="replace")
        log(f"A pesquisar: {tema}")
        
        # Verificar datasets locais primeiro
        datasets_locais = verificar_datasets_locais()
        
        # Tentar Langflow primeiro
        resultado = pesquisar_na_web_via_langflow(f"Pesquise informações sobre: {tema}. Resuma os pontos principais.")
        
        # Se Langflow falhar, usar HuggingFace
        if not resultado:
            log("Langflow falhou, a tentar HuggingFace...")
            resultado = pesquisar_huggingface(tema)
        
        # Adicionar informação sobre datasets locais
        if datasets_locais:
            resultado = f"{datasets_locais}\n\n{resultado}" if resultado else datasets_locais
        
        if resultado:
            # Guardar resultado
            resultado_file = PESQUISAS_DIR / f"resultado_{pesquisa_file.stem}.txt"
            resultado_file.write_text(f"# Pesquisa: {tema}\n\n{resultado}", encoding="utf-8")
            log(f"Pesquisa concluída e guardada em: {resultado_file}")
            
            # Mover para pasta de pesquisas concluídas (com tratamento de erro)
            try:
                destino = PESQUISAS_CONCLUIDAS_DIR / pesquisa_file.name
                if destino.exists():
                    # Se já existe, adicionar timestamp
                    destino = PESQUISAS_CONCLUIDAS_DIR / f"{int(time.time())}_{pesquisa_file.name}"
                pesquisa_file.rename(destino)
            except Exception as e:
                log(f"Erro ao mover pesquisa: {e}")
            
            # Analisar pesquisa e gerar sugestões
            gerar_sugestoes_de_pesquisa(tema, resultado)
        else:
            log(f"Falha na pesquisa de: {tema}")


def pesquisa_automatica():
    """Pesquisa automática de tópicos sem precisar de ficheiros .txt."""
    log("A iniciar pesquisa automática...")
    
    # Escolher um tópico aleatório da lista
    import random
    tema = random.choice(TOPICOS_PESQUISA)
    log(f"A pesquisar: {tema}")
    
    # Verificar datasets locais primeiro
    datasets_locais = verificar_datasets_locais()
    
    # Tentar Langflow primeiro
    resultado = pesquisar_na_web_via_langflow(f"Pesquise informações sobre: {tema}. Resuma os pontos principais.")
    
    # Se Langflow falhar, usar HuggingFace
    if not resultado:
        log("Langflow falhou, a tentar HuggingFace...")
        resultado = pesquisar_huggingface(tema)
    
    # Adicionar informação sobre datasets locais
    if datasets_locais:
        resultado = f"{datasets_locais}\n\n{resultado}" if resultado else datasets_locais
    
    if resultado:
        # Guardar resultado
        resultado_file = PESQUISAS_DIR / f"resultado_auto_{int(time.time())}.txt"
        resultado_file.write_text(f"# Pesquisa Automática: {tema}\n\n{resultado}", encoding="utf-8")
        log(f"Pesquisa automática concluída e guardada em: {resultado_file}")
        
        # Analisar pesquisa e gerar sugestões
        gerar_sugestoes_de_pesquisa(tema, resultado)
    else:
        log(f"Falha na pesquisa automática de: {tema}")


def gerar_sugestoes_de_pesquisa(tema, resultado):
    """Analisa a pesquisa e gera sugestões de melhoria."""
    log(f"A analisar pesquisa: {tema}")
    
    # Usar o modelo para analisar a pesquisa e gerar sugestões (otimizado para menos CPU)
    system_prompt = (
        "És o ORION, um assistente de IA que analisa pesquisas e gera sugestões de melhoria para o sistema. "
        "Analisa o resultado da pesquisa e gera sugestões práticas e específicas para melhorar o ORION. "
        "Responde em JSON com o formato: {\"sugestoes\": [{\"tipo\": \"codigo|whisper|config\", \"descricao\": \"...\", \"prioridade\": \"alta|media|baixa\"}]}"
    )
    
    # Limitar o tamanho do prompt para economizar CPU
    prompt = f"Analisa esta pesquisa sobre '{tema}' e gera sugestões de melhoria para o ORION:\n\n{resultado[:1000]}"
    
    try:
        resposta = consultar_modelo(prompt, system_prompt)
        
        # Tentar extrair JSON da resposta
        import json
        try:
            dados = json.loads(resposta)
            sugestoes = dados.get("sugestoes", [])
        except:
            # Tentar extrair JSON do texto
            import re
            json_match = re.search(r'\{.*\}', resposta, re.DOTALL)
            if json_match:
                dados = json.loads(json_match.group())
                sugestoes = dados.get("sugestoes", [])
            else:
                sugestoes = []
        
        if sugestoes:
            # Limitar a 5 sugestões para economizar recursos
            sugestoes = sugestoes[:5]
            
            # Guardar sugestões
            sugestoes_file = SUGESTOES_DIR / f"sugestoes_{tema.replace(' ', '_')[:30]}.json"
            sugestoes_file.write_text(json.dumps({
                "tema": tema,
                "data": time.strftime("%Y-%m-%d %H:%M:%S"),
                "sugestoes": sugestoes
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"Geradas {len(sugestoes)} sugestão(ões) em: {sugestoes_file}")
        
    except Exception as e:
        log(f"Erro ao gerar sugestões: {e}")


def processar_sugestoes_aprovadas():
    """Processa sugestões que foram aprovadas."""
    # Procurar ficheiros de sugestões aprovadas
    aprovadas = list(APROVADAS_DIR.glob("*.json"))
    log(f"Encontradas {len(aprovadas)} sugestão(ões) aprovada(s)")
    
    for arquivo in aprovadas:
        try:
            import json
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
            tema = dados.get("tema", "")
            sugestoes = dados.get("sugestoes", [])
            
            log(f"A aplicar sugestões para: {tema}")
            
            for sugestao in sugestoes:
                tipo = sugestao.get("tipo", "")
                descricao = sugestao.get("descricao", "")
                
                if tipo == "whisper":
                    # Adicionar à fila de fine-tuning
                    adicionar_dataset_para_finetuning(descricao)
                elif tipo == "codigo":
                    # Criar tarefa de código
                    criar_tarefa_codigo(descricao)
                elif tipo == "config":
                    # Guardar para análise manual
                    log(f"Sugestão de configuração: {descricao}")
            
            # Mover para processadas
            arquivo.rename(APROVADAS_DIR / f"processada_{arquivo.name}")
            
        except Exception as e:
            log(f"Erro ao processar sugestão aprovada: {e}")


def adicionar_dataset_para_finetuning(descricao):
    """Adiciona dataset para fine-tuning do Whisper."""
    # Criar tarefa de pesquisa para encontrar datasets
    pesquisa_file = PESQUISAS_DIR / f"dataset_{int(time.time())}.txt"
    pesquisa_file.write_text(f"Dataset para fine-tuning do Whisper: {descricao}", encoding="utf-8")
    log(f"Adicionado dataset para pesquisa: {descricao}")


def criar_tarefa_codigo(descricao):
    """Cria uma tarefa de código para melhorar o ORION."""
    tarefa_file = PENDENTES_DIR / f"melhoria_{int(time.time())}.txt"
    tarefa_file.write_text(descricao, encoding="utf-8")
    log(f"Criada tarefa de código: {descricao[:50]}...")

def consultar_modelo(prompt, system_prompt=""):
    """Envia um pedido ao Qwen2.5-Coder através do Ollama."""
    try:
        log("A comunicar com Ollama...")
        response = ollama.chat(
            model=MODELO_CODIGO,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            options={"temperature": 0.2}
        )
        log("Resposta recebida do Ollama")
        return response['message']['content']
    except Exception as e:
        log(f"[ERRO OLLAMA] Falha ao comunicar com o modelo: {e}")
        return ""

def executar_sandbox(ficheiro_path):
    """Executa o script gerado num ambiente isolado para validar erros."""
    try:
        resultado = subprocess.run(
            ["python", str(ficheiro_path)],
            capture_output=True,
            text=True,
            timeout=10
        )
        if resultado.returncode == 0:
            return True, "Sucesso na execução."
        else:
            return False, resultado.stderr
    except subprocess.TimeoutExpired:
        return False, "Erro: O script excedeu o tempo limite de execução (timeout)."
    except Exception as e:
        return False, str(e)

def ciclo_autonomo_codigo():
    log("A verificar tarefas pendentes de código...")
    
    # Exemplo: Procurar ficheiros de tarefas ou pedidos na pasta de pendentes ou cofre do Obsidian
    # Filtrar apenas ficheiros que não são falhas (não começam com 'falha_')
    tarefas_encontradas = [f for f in list(PENDENTES_DIR.glob("*.txt")) + list(PENDENTES_DIR.glob("*.md")) 
                          if not f.name.startswith("falha_")]
    log(f"Encontradas {len(tarefas_encontradas)} tarefa(s) pendente(s)")
    
    for tarefa_file in tarefas_encontradas:
        objetivo = tarefa_file.read_text(encoding="utf-8", errors="replace")
        log(f"A processar objetivo: {tarefa_file.name}")
        
        system_prompt = (
            "És o ORION, um engenheiro de software autónomo especializado em Python. "
            "Gera apenas código Python válido, limpo e funcional para resolver o objetivo pedido. "
            "Não coloques texto explicativo fora dos blocos de código."
        )
        
        tentativas = 3
        sucesso = False
        codigo_gerado = ""
        erro_atual = ""
        
        for tentativa in range(tentativas):
            log(f"Tentativa de geração {tentativa + 1}/{tentativas}...")
            
            if tentativa == 0:
                prompt = f"Escreve um script completo em Python que cumpra o seguinte objetivo:\n\n{objetivo}"
            else:
                prompt = (
                    f"O código anterior falhou com o seguinte erro:\n{erro_atual}\n\n"
                    f"Corrige o código e fornece a versão totalmente funcional em Python para o objetivo:\n{objetivo}"
                )
            
            resposta = consultar_modelo(prompt, system_prompt)
            
            # Extrair bloco de código da resposta do LLM
            if "```python" in resposta:
                partes = resposta.split("```python")
                codigo_gerado = partes[1].split("```")[0].strip()
            elif "```" in resposta:
                partes = resposta.split("```")
                codigo_gerado = partes[1].split("```")[0].strip()
            else:
                codigo_gerado = resposta.strip()
                
            # Guardar temporariamente para teste
            temp_script = BASE_DIR / "temp_teste.py"
            temp_script.write_text(codigo_gerado, encoding="utf-8")
            
            # Testar em sandbox
            sucesso, erro_atual = executar_sandbox(temp_script)
            
            if sucesso:
                log(f"Código validado com sucesso na tentativa {tentativa + 1}!")
                break
            else:
                log(f"Falha detetada: {erro_atual[:150]}... A auto-corrigir.")
        
        if sucesso:
            # Mover o código validado para a pasta definitiva de plugins/código base
            nome_final = tarefa_file.stem + ".py"
            destino = PLUGINS_DIR / nome_final
            destino.write_text(codigo_gerado, encoding="utf-8")
            log(f"Módulo integrado com sucesso em: {destino}")
            
            # Apagar tarefa concluída
            tarefa_file.unlink()
        else:
            log(f"A tarefa {tarefa_file.name} foi rejeitada após esgotar as tentativas de auto-correção.")
            # Opcional: Mover para uma pasta de erros para análise futura
            tarefa_file.rename(PENDENTES_DIR / f"falha_{tarefa_file.name}")

if __name__ == "__main__":
    log("=== AGENTE DE PROGRAMAÇÃO AUTÓNOMA DO ORION ATIVO ===")
    log("A aguardar 5 segundos para iniciar...")
    time.sleep(5)
    while True:
        try:
            ciclo_autonomo_codigo()
            pesquisa_automatica()  # Pesquisa automática sem ficheiros .txt
            processar_sugestoes_aprovadas()
        except Exception as e:
            log(f"[ERRO CRÍTICO NO AGENTE] {e}")
            traceback.print_exc()
        
        # O agente verifica novas tarefas a cada 60 segundos de forma autónoma
        log("A aguardar 60 segundos para próximo ciclo...")
        time.sleep(60)