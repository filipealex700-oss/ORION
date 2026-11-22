# ORION Web — interface minimalista (primeira versão)

Esta pasta acrescenta uma interface Web ao ORION sem reescrever o motor Python.
A integração foi alinhada com `nucleo.py`: reutiliza `Orion(cfg, emitir)`,
`iniciar()`, `parar()` e `enviar_texto(texto)`. O callback mantém o contrato
`emitir(tipo, texto, **extra)` documentado no núcleo.

## O que esta versão já inclui

- Interface responsiva, minimalista e em português.
- Chat Web ligado a `Orion.enviar_texto`.
- Atualização em tempo real dos eventos emitidos pelo ORION através de WebSocket.
- Apresentação do estado, voz e eventos recentes.
- Autenticação por token quando o servidor é exposto à rede local.

## O que ainda não inclui

Esta primeira versão é deliberadamente visual. Não implementa ainda páginas de
gestão de memória, tarefas, definições de voz ou aprovação de ferramentas.
Essas funções exigem conhecer os módulos `tools.py`, `memoria.py`, `config.py`
e o esquema real da base de dados, que não foram incluídos no conjunto recebido.

## Instalação

1. Copia a pasta `web` para a raiz do projeto ORION, ao lado de `nucleo.py`.
2. Instala as dependências no mesmo ambiente Python do ORION:

   ```bash
   pip install fastapi uvicorn
   ```

3. O `nucleo.py` recebido importa `config`, mas o respetivo `config.py` e o
   ponto de entrada que constrói `Janela(cfg, ...)` não vieram nos ficheiros.
   Exporta para JSON o mesmo dicionário `cfg` que já passas à GUI, ou adapta
   `load_config()` em `app.py` para chamar o carregador real do teu projeto.
4. Testa primeiro apenas no próprio computador:

   ```bash
   python web/app.py --config config.json
   ```

5. Abre `http://127.0.0.1:8765`.

## Acesso pela rede local

No computador onde o ORION corre, define um token longo e inicia o servidor
a escutar na rede:

PowerShell:

```powershell
$env:ORION_WEB_TOKEN = "substitui-por-uma-chave-aleatoria-com-mais-de-24-caracteres"
python web/app.py --host 0.0.0.0 --port 8765 --config config.json
```

Depois, noutro dispositivo da mesma rede Wi-Fi, abre:

`http://IP-DO-COMPUTADOR:8765`

Introduz o mesmo token no ecrã de entrada. Permite a porta 8765 apenas na rede
privada do Windows Firewall. Não encaminhes esta porta para a Internet nem
uses uma rede Wi-Fi pública. Para acesso remoto fora de casa, usa uma VPN
privada (por exemplo, Tailscale) ou configura HTTPS e autenticação apropriada.

## Integração com a configuração

O ficheiro `config.py` não foi enviado. Por isso, `load_config()` lê um JSON
explícito em vez de presumir que existe `config.CFG`, `config.carregar()` ou
outra função. Se o teu projeto carrega a configuração por código, adapta
apenas `load_config()` para chamar o carregador real e devolver o dicionário
esperado por `Orion`.

## Notas de integração

- Mantém o `gui.py` durante os testes. Não o apagues.
- Não inicies simultaneamente duas instâncias do motor ORION a usar a mesma
  memória/microfone. Fecha a GUI antes de arrancar a versão Web.
- O callback `emitir(tipo, texto="", **kwargs)` foi mantido compatível com o
  formato usado em `gui.py`.
- O áudio/microfone continua a ser gerido pelo motor Python no computador
  principal; esta interface inicial não transmite áudio do telemóvel.
- A interface não executa nem aprova código. A aprovação de ferramentas deve
  continuar a exigir revisão explícita no processo já existente.


## Estado da análise do código recebido

O `nucleo.py` confirma que `Orion` emite eventos com a assinatura
`emitir(tipo, texto, **extra)` e que `enviar_texto()` coloca a mensagem na fila
de processamento. A interface Web consome estes eventos e não tenta executar
o cérebro diretamente. A lista de eventos visuais é baseada nos tipos
documentados no cabeçalho do núcleo e nos usados por `gui.py`.

Para fechar a integração sem suposições, ainda são necessários `config.py`
(ou o ficheiro que constrói `cfg`) e, idealmente, `tools.py` para uma fase
posterior de apresentação de aprovações e ferramentas.
