# Sistema de Aprovação de Sugestões do ORION

## Como funciona:

1. **Pesquisas automáticas**: O agente autónomo pesquisa tópicos em `orion_core/pesquisas/`
2. **Geração de sugestões**: Analisa os resultados e gera sugestões em `orion_core/sugestoes/`
3. **Aprovação manual**: Tu revês as sugestões e aprovas as que queres aplicar
4. **Aplicação**: Sugestões aprovadas são aplicadas automaticamente

## Estrutura de pastas:

- `orion_core/pesquisas/` - Tópicos para pesquisar (coloca ficheiros .txt aqui)
- `orion_core/pesquisas_concluidas/` - Pesquisas já processadas
- `orion_core/sugestoes/` - Sugestões geradas (aguardam aprovação)
- `orion_core/aprovadas/` - Sugestões aprovadas por ti
- `orion_core/pendentes/` - Tarefas de código pendentes
- `orion_core/plugins/` - Código gerado e validado

## Como aprovar sugestões:

1. Vai à pasta `orion_core/sugestoes/`
2. Abre o ficheiro JSON da sugestão
3. Se gostares, move o ficheiro para `orion_core/aprovadas/`
4. O agente autónomo irá aplicar as sugestões no próximo ciclo (60 segundos)

## Tipos de sugestões:

- **codigo**: Melhorias no código do ORION
- **whisper**: Melhorias no reconhecimento de voz
- **config**: Alterações de configuração

## Exemplo de sugestão:

```json
{
  "tema": "Como melhorar o reconhecimento de voz",
  "data": "2026-11-06 16:35:00",
  "sugestoes": [
    {
      "tipo": "whisper",
      "descricao": "Usar dataset MLS Portuguese para fine-tuning",
      "prioridade": "alta"
    },
    {
      "tipo": "codigo",
      "descricao": "Melhorar detecção de fala para sotaques PT",
      "prioridade": "media"
    }
  ]
}
```

## Para aplicar sugestões:

1. Move o ficheiro de `sugestoes/` para `aprovadas/`
2. Aguarda 60 segundos
3. O agente irá processar e aplicar as melhorias
