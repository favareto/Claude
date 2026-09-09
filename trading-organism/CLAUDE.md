# Organismo de Robôs Autônomos de Trade

Este arquivo é a memória do projeto. Leia isto antes de qualquer tarefa.

## Visão geral

Um "macro-organismo" de robôs de trade autônomos. Cada robô nasce pequeno,
opera uma estratégia validada, e se multiplica (clona) quando dá lucro ou é
eliminado quando dá prejuízo. O objetivo é uma população que evolui: as
estratégias boas se multiplicam, as ruins desaparecem, e o sistema fica cada
vez mais especializado por ativo.

Fase atual: **simulação / paper trading**. Nada de dinheiro real ainda.

## Atores do sistema

### 1. Investigador
Pesquisa na web quais estratégias de trading estão sendo mais lucrativas
(GitHub, arXiv q-fin.TR, listas como `awesome-systematic-trading`,
repositórios de estratégias do Freqtrade). Estrutura cada estratégia
encontrada em formato padronizado (nome, indicadores, regra de entrada,
regra de saída, gestão de risco, fonte) e alimenta o Professor.

### 2. Professor
Recebe o material do Investigador e monta o "currículo" de ensino — mas
personalizado por robô/ativo, não uma regra genérica pra todos. Ensina o
robô a aplicar (e adaptar) a estratégia no ativo em que ele é especialista.

### 3. Estrategista
Gatekeeper em duas camadas:
1. Valida a estratégia geral de um robô quando ele nasce ou quando muda de
   estratégia.
2. Valida CADA sinal de entrada antes de qualquer execução. Se discordar,
   a operação não acontece.
É chamado com muita frequência — pensar nele como um serviço central, não
algo que cada robô roda isolado.

### 4. Agente-robô
- Nasce com **$5**.
- Opera só o ativo em que é especialista.
- Toda entrada precisa passar pelo Estrategista.
- Regras de vida (ver abaixo).

### 5. Macro-organismo (orquestrador central)
Mantém o estado de toda a população: quem existe, saldo de cada um, quem
está operando, histórico de quem já foi eliminado. É a única fonte de
verdade — tanto a simulação quanto a visualização leem daqui.

### 6. Visualizador
Ambiente 2D top-down (estilo Tibia): bonequinhos sentados numa mesa
operando, saldo aparece acima da cabeça, quem não está operando fica de pé
numa "lanchonete virtual". Quando um robô é eliminado, ele simplesmente
desaparece da cena e passa a existir só como registro no painel de
apurações.
Lê o estado do Macro-organismo — não tem lógica de decisão nenhuma.

### 7. Painel de apurações
Dashboard com o histórico completo: todo robô que já existiu, pico de
capital, causa da morte (drawdown) ou geração de clones, tempo de vida,
estratégia usada. Também só lê o estado do Macro-organismo.

## Regras de vida do robô (fixas — não mudar sem avisar)

- Capital inicial: **$5**
- **Clonagem**: quando o capital multiplica **+70%**, o robô clona. O
  capital acumulado é **dividido** entre original + clone (a população
  dobra; o tamanho da aposta por operação **não** dobra).
- **Eliminação**: quando o capital cai **60% a partir do pico** que aquele
  robô já alcançou (drawdown desde o topo, não desde o valor atual), o
  robô é fechado/removido.
- **Sem limite** de multiplicação — a intenção é crescimento exponencial.
- Auto-otimização = o próprio evento de clonagem (não há ajuste de
  parâmetro "por fora" disso, por enquanto).

## Fluxo de decisão (por robô, a cada candle/tick)

```
Investigador → Professor (currículo por robô/ativo)
                     ↓
              Agente-robô decide operar
                     ↓
      Estrategista valida (estratégia + entrada específica)
                     ↓
        aprovado? → executa (simulação/paper)
        recusado? → não opera, segue no próximo ciclo
                     ↓
        checagem de +70% (clona) ou -60% do pico (elimina)
```

## Stack sugerida (ponto de partida, não definitivo)

- **Core / lógica do organismo**: Python (`src/core`)
- **Simulação / paper trading**: começar com motor próprio simples; migrar
  ou se inspirar no **Freqtrade** (já tem dry-run, backtest e conecta a
  100+ exchanges via CCXT) quando sair do zero-ao-primeiro-teste.
- **Investigador (produção, 24h)**: script separado chamando a API da
  Anthropic com a ferramenta de busca web habilitada, rodando por cron ou
  GitHub Actions — não depende de sessão interativa do Claude Code.
- **Visualização**: Phaser.js (motor 2D JS) + Tiled (editor de mapas)
- **Painel**: dashboard web simples, pode ser a mesma stack do visualizador
- **Versionamento**: GitHub (este repositório)

## Referências de projetos existentes (estudar, não copiar direto)

- `TauricResearch/TradingAgents` — framework multi-agente (analistas,
  trader, risco) que inspira a separação Investigador/Professor/Estrategista.
- `EJMM17/Bot` (Darwin Agent) — o mais parecido com o conceito de organismo:
  ciclo de vida evolutivo, nascimento/morte, sistema de saúde, paper trading
  por padrão.
- `TradingGoose` — prova de que um sistema multi-agente de trading dá pra
  construir inteiramente dentro do Claude Code.

## O que NÃO fazer sem perguntar

- Não trocar as regras de vida (70% / 60% / sem limite) sem confirmação.
- Não conectar a dinheiro real / corretora de produção nesta fase.
- Não simplificar a arquitetura de 2 camadas do Estrategista pra "só uma
  validação".

## Ponto de partida: NÃO construir do zero

Este projeto nasceu a partir de um clone do repositório
**`EJMM17/Bot` ("Darwin Agent")** — https://github.com/EJMM17/Bot — porque
ele já implementa boa parte do ciclo de vida que descrevemos: agentes que
nascem, operam, morrem e passam conhecimento pra próxima geração, com
sistema de saúde que elimina quem tem desempenho ruim, capital inicial
pequeno, e paper trading/testnet como padrão de segurança.

O código original (v2.3) foi trazido para esta pasta (`trading-organism/`).
A documentação de arquitetura original dos autores está preservada em
`UPSTREAM_CLAUDE.md`, para referência.

**Mapeamento — o que já existe lá vs. o que precisamos adaptar/criar:**

| Peça do nosso organismo | Está no Darwin Agent? | O que fazer |
|---|---|---|
| Robô com capital inicial e ciclo de vida | Sim (conceito de agente que nasce/opera/morre) | Adaptar os números: capital inicial $5, clona em +70%, morre em -60% de drawdown do pico |
| Sistema de eliminação por desempenho | Sim (sistema de saúde/HP) | Ajustar o gatilho pra ser exatamente o drawdown de 60% desde o pico |
| Clonagem que divide capital em vez de dobrar risco | Não tem exatamente assim | Precisa implementar: ao clonar, dividir capital acumulado entre original + clone |
| Investigador (pesquisa de estratégias na web) | Não | Construir como sub-agente novo (`.claude/agents/investigador.md`) |
| Professor (currículo por robô/ativo) | Não | Construir como sub-agente novo |
| Estrategista de 2 camadas (valida estratégia E cada entrada) | Parcialmente (há alguma validação de risco) | Precisa isolar isso como serviço central próprio, chamado antes de cada entrada |
| Conexão com exchange / paper trading | Sim (Bybit testnet/paper por padrão) | Reaproveitar; trocar de exchange depois se quiser |
| Visualização 2D estilo Tibia | Não (o dashboard dele é web simples) | Construir depois, à parte, lendo o mesmo estado |

A primeira tarefa real dentro do Claude Code deve ser pedir pra ele **ler o
código do Darwin Agent clonado e comparar com este `CLAUDE.md`**, apontando
exatamente que arquivos mexer pra cada linha da tabela acima — antes de
escrever qualquer código novo.

## Próximos passos sugeridos

1. ~~Clonar `EJMM17/Bot` como base do repositório.~~ Feito — código em `trading-organism/`.
2. Pedir ao Claude Code pra mapear o código existente contra a tabela acima.
3. Ajustar as regras de vida (capital, %, drawdown) pros valores exatos deste documento.
4. Validar o ciclo nascer→operar→clonar→morrer em simulação pura, sem Investigador/Professor reais ainda.
5. Só depois: construir Investigador, Professor e Estrategista como peças separadas; visualização e painel vêm por último.
