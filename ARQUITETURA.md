# Arquitetura do ORION (inspirada no OpenJarvis)

O OpenJarvis (Stanford, "Personal AI, On Personal Devices") organiza uma IA pessoal em cinco primitivas.
O ORION segue a mesma ideia, adaptada a voz, Windows e 100% local:

| Primitiva (OpenJarvis) | No ORION | Ficheiros |
|---|---|---|
| **Inteligência** (modelos) | `modelo_llm`, `modelo_rapido`, `modelo_codigo`, Whisper; presets por hardware | `config.json`, `presets.json`, `presets.py` |
| **Motor** (runtime) | Ollama local | `brain.py`, `memory.py` (chamadas ao Ollama) |
| **Agentes** | simples (conversa, sem ferramentas) · ferramentas (ações) · trabalhos agendados (segundo plano) | `brain.py`, `routing.py`, `autonomo.py` |
| **Ferramentas e Memória** | ~40 ferramentas, skills em `.md`, memória vetorial local, plugins aprovados por ti | `tools.py`, `gestao.py`, `codigo.py`, `skills.py`, `memory.py`, `plugins/` |
| **Aprendizagem** | traços de cada pedido, roteamento aprendido, factos, hábitos, correções de voz, feedback | `routing.py`, `aprendizagem.py`, `treino/` |

## Modos de execução
- **A pedido:** falas ou escreves e ela responde.
- **Agendado:** `agendar_job` / `agendar_lembrete` (a horas certas ou de X em X tempo).
- **Contínuo:** o ciclo de aprendizagem nos tempos livres e o arranque com o Windows.

## Fluxo de um pedido
voz → Whisper (texto + confiança) → palavra "ORION" → **router** (simples ou principal) →
cérebro (+ memórias + skill, se houver) → ferramenta(s) → resposta falada → **traço** guardado (modelo, ferramentas, latência, avaliação).

## Roteamento por complexidade
Conversa simples vai para o modelo rápido sem lista de ferramentas (prompt curto, resposta mais depressa).
Pedidos de ação, números, frases longas ou respostas a perguntas dela vão para o modelo principal com ferramentas.
Se avaliares mal 5 ou mais respostas da rota rápida, ela desliga-se sozinha ("rota rápida ligar" volta a ativá-la).
Pergunta "como estão as métricas?" para veres latência e avaliações por rota.

## Skills
Cada `skills/*.md` descreve um tipo de trabalho (1.ª linha `# Nome`, 1.º parágrafo = quando usar, resto = passos).
Quando o pedido se parece com uma skill, os passos entram no prompt. Cria as tuas.

## Avaliar modelos no teu PC
`python avaliar.py llama3.1:8b qwen2.5:14b` testa 15 pedidos e mostra quantas ferramentas cada modelo escolheu
bem e o tempo por pedido. Usa-o para decidir o preset.

## O que NÃO foi adotado (de propósito)
- Motores na nuvem, canais (Telegram, Slack...) e a "pesquisa de specs" assistida por modelos de nuvem: exigem APIs.
- Importação de skills de outros ecossistemas: não verifiquei o formato, por isso as skills são só as tuas.
- Ficheiro de especificação tipado (`config.toml`): o ORION usa `config.json` + `presets.json`.
- Aprendizagem dos pesos do modelo (SFT/GRPO): precisa de GPU; o `treino/feedback.jsonl` fica pronto para isso.
