import os
from pathlib import Path
from datetime import datetime

class ObsidianBridge:
    def __init__(self, vault_path: str):
        """
        Inicializa a ponte para o cofre do Obsidian.
        :path: Caminho absoluto para a pasta do cofre no teu computador.
        """
        self.vault_path = Path(vault_path)
        if not self.vault_path.exists():
            try:
                self.vault_path.mkdir(parents=True, exist_ok=True)
            except Exception:
                raise FileNotFoundError(f"O cofre do Obsidian não foi encontrado em: {vault_path}")

    def ler_nota(self, nome_nota: str) -> str:
        """Lê o conteúdo de uma nota Markdown no cofre."""
        if not nome_nota.endswith(".md"):
            nome_nota += ".md"
            
        ficheiro = self.vault_path / nome_nota
        if ficheiro.exists():
            with open(ficheiro, "r", encoding="utf-8") as f:
                return f.read()
        return f"[Aviso: A nota '{nome_nota}' não foi encontrada.]"

    def escrever_nota(self, nome_nota: str, conteudo: str, subpasta: str = "") -> str:
        """Cria ou substitui o conteúdo de uma nota."""
        if not nome_nota.endswith(".md"):
            nome_nota += ".md"
            
        destino_pasta = self.vault_path / subpasta
        destino_pasta.mkdir(parents=True, exist_ok=True)
        
        ficheiro = destino_pasta / nome_nota
        with open(ficheiro, "w", encoding="utf-8") as f:
            f.write(conteudo)
            
        return f"Nota '{nome_nota}' escrita com sucesso em '{destino_pasta}'."

    def adicionar_a_nota(self, nome_nota: str, texto_para_adicionar: str) -> str:
        """Adiciona (append) novo texto/registo ao final de uma nota existente."""
        if not nome_nota.endswith(".md"):
            nome_nota += ".md"
            
        ficheiro = self.vault_path / nome_nota
        ficheiro.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        bloco = f"\n\n--- \n*Registo automático em {timestamp}:*\n{texto_para_adicionar}"
        
        with open(ficheiro, "a", encoding="utf-8") as f:
            f.write(bloco)
            
        return f"Conteúdo anexado com sucesso à nota '{nome_nota}'."

# --- Exemplo de Teste Prático ---
if __name__ == "__main__":
    # Substitui pelo caminho real do teu cofre do Obsidian
    CAMINHO_COFRE = os.environ.get("ORION_VAULT_PATH", "")
    
    try:
        orion_obsidian = ObsidianBridge(CAMINHO_COFRE)
        
        # Testar a escrita de uma nota de segurança ou resumo
        resposta = orion_obsidian.escrever_nota(
            nome_nota="ORION-Status.md", 
            conteudo="# Estado do Sistema ORION\n\n- [x] Criptografia Ativa\n- [x] Langflow Conectado\n- Estado: Operacional.",
            subpasta="ORION-Logs"
        )
        print(resposta)
        
        # Testar a leitura da nota criada
        conteudo_lido = orion_obsidian.ler_nota("ORION-Logs/ORION-Status.md")
        print("\nConteúdo lido do Obsidian:\n", conteudo_lido)
        
    except Exception as e:
        print(f"Erro: {e}")
        