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
**NÃO é um repositório fixo de poucas estratégias.** É um fluxo contínuo de
pesquisa: a cada rodada (produção: script separado, cron/GitHub Actions,
API da Anthropic com busca web habilitada), ele traz estratégias NOVAS —
GitHub, arXiv q-fin.TR, `awesome-systematic-trading`, repositórios do
Freqtrade — e injeta na fila (`ingest`). Estrutura cada uma em formato
padronizado (nome, indicadores, regra de entrada, regra de saída, gestão
de risco, fonte) e alimenta o Professor. A mesma implementação (ex:
"momentum") pode reaparecer várias vezes com parâmetros/fontes diferentes
conforme a pesquisa avança — nunca é "as mesmas 4 estratégias de sempre".

**Fluxo de nascimento de um avatar novo (raiz, sem pai):** o Investigador
traz UMA estratégia estruturada → o Estrategista valida essa proposta
(camada 1) → se aprovada, nasce exatamente UM boneco novo, especialista
naquela estratégia + o ativo escolhido. Uma proposta recusada não gera
avatar nenhum. Implementado em `investigator.py` (`StrategyProposal`,
`Investigador.ingest`/`next_new`) + `strategist.py` (`validate_proposal`) +
`organism.py` (`Organism.propose_and_spawn`).

Hoje (fase de desenvolvimento) a fila é populada manualmente por
`bootstrap_feed()` com estratégias já pesquisadas de verdade (fontes reais
citadas no código); em produção isso é substituído por pesquisa contínua
de verdade, sem depender de sessão interativa do Claude Code.

### 2. Professor
Recebe o material do Investigador e monta o "currículo" de ensino — mas
personalizado por robô/ativo, não uma regra genérica pra todos. Ensina o
robô a aplicar (e adaptar) a estratégia no ativo em que ele é especialista.

### 3. Estrategista
Gatekeeper em duas camadas, com **autonomia real pra reprovar qualquer
estratégia ou operação sempre que consultado** — não é um carimbo
automático. Mesmo uma proposta com schema perfeito é recusada se o
histórico real da população mostrar que ela não está performando:
1. Valida a estratégia geral de um robô quando ele nasce ou quando muda de
   estratégia. Camada de mérito: se `N` ou mais robôs já nasceram com essa
   combinação (estratégia + ativo) e a taxa de morte for alta demais
   (≥75%, com amostra mínima de 3 tentativas — configurável em
   `Strategist.MIN_ATTEMPTS_BEFORE_JUDGING`/`MAX_DEATH_RATE`), o
   Estrategista recusa novas tentativas naquela combinação especificamente
   — a mesma estratégia continua liberada em outro ativo com histórico
   limpo. Implementado em `strategist.py` (`TrackRecord`,
   `validate_proposal`), calculado por `organism.py` (`Organism._track_record`)
   a partir dos robôs já nascidos.
2. Valida CADA sinal de entrada antes de qualquer execução (`validate_entry`,
   reaproveitando `RiskManager`: confiança mínima adaptativa, limite diário
   de perdas, R:R mínimo, posições máximas). Se discordar, a operação não
   acontece.
É chamado com muita frequência — pensar nele como um serviço central, não
algo que cada robô roda isolado. Hoje o julgamento em ambas as camadas é
determinístico (regras + histórico real); é o ponto de extensão pra um
agente/LLM julgar com mais nuance depois, sem mudar quem o chama.

### 4. Agente-robô
- Nasce com **$5**.
- Opera só o ativo em que é especialista **e só a estratégia com que
  nasceu** (validada pelo Estrategista) — não escolhe livremente entre
  outras estratégias implementadas. Um clone herda a mesma estratégia do
  pai (é uma clonagem literal).
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

- Capital inicial: **$5** — todo robô nasce com $5, seja ele raiz ou clone.
- **Clonagem**: quando o capital do robô multiplica **+70%** sobre o seu
  último marco (o marco começa em $5 no nascimento — ou seja, o primeiro
  clone dispara em $8,50), o robô clona. O **clone nasce com $5 novos**; o
  **original NÃO reseta** — segue operando com o saldo cheio que já tinha, e
  seu próprio marco de clonagem avança para esse novo saldo (então o
  próximo clone dele exige +70% em cima do valor atual, não de novo sobre
  $5). A população dobra a cada clonagem; o tamanho da aposta por operação
  não dobra.
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

**Mapeamento — o que já existe lá vs. o que foi adaptado/criado (atualizado):**

| Peça do nosso organismo | Está no Darwin Agent original? | Status |
|---|---|---|
| Robô com capital inicial e ciclo de vida | Sim, mas era **linhagem única sequencial** (1 agente por vez, morre → nasce a próxima geração) | **Feito** — `core/agent_v2.py`: cada robô é uma task assíncrona independente; N robôs rodam concorrentes (ver `organism.py`) |
| Capital inicial $5 | Não (default $50) | **Feito** — `utils/config.py: AgentConfig.starting_capital = 5.0` |
| Sistema de eliminação por desempenho | Sim, mas era um HP (0-100) alimentado por vários fatores, drawdown só tirava HP, não matava direto | **Feito** — `core/health.py` reescrito: morte só por `current_drawdown_pct >= death_drawdown_pct` (60%, desde o pico do próprio robô). `hp`/`max_hp` viraram só uma projeção cosmética do drawdown, mantidos por compatibilidade |
| Clonagem em +70%, clone nasce com $5, original NÃO reseta | Não existia (só herança de DNA pra próxima geração, sequencial) | **Feito** — `core/agent_v2.py: _check_clone()`: marco de clonagem por robô, clone nasce com `starting_capital`, original segue com saldo cheio e ganha novo marco. O clone herda o cérebro (Q-learning) do pai via `inherit_brain_from()` — clonagem literal, sem mutação (auto-otimização = o próprio evento de clonar) |
| Sem limite de multiplicação, população cresce | Não (era sempre 1 agente vivo) | **Feito** — `organism.py: Organism`: cada clone vira uma nova `asyncio.Task`, sem teto |
| Macro-organismo (fonte única de verdade) | Não | **Feito** — `organism.py`: registro central de todos os robôs (vivos e mortos), persistido em `data/population.json` |
| Investigador (fluxo contínuo de pesquisa, NÃO um catálogo fixo) | Não | **Esqueleto feito** — `investigator.py: Investigador` é uma fila (`ingest`/`next_new`), não uma lista fixa. Hoje populada manualmente por `bootstrap_feed()` com 3 estratégias já pesquisadas de verdade (momentum/EMA, mean_reversion/Bollinger, scalping/VWAP — fontes reais no código); falta virar script de pesquisa contínua de verdade (LLM + busca web, cron/GitHub Actions, como descrito no CLAUDE.md) |
| Professor (currículo por robô/ativo) | Não | **Pendente** — construir como sub-agente novo |
| Estrategista (2 camadas, com autonomia real de veto) | Parcial (só `RiskManager.approve_trade`, sem camada 1) | **Feito** — `strategist.py: Strategist`, serviço único compartilhado por toda a população. Camada 2 (`validate_entry`, cada sinal) reaproveita `RiskManager`. Camada 1: `validate_strategy` (sanidade genérica) + `validate_proposal` (schema + **veto por histórico real**: `TrackRecord` conta tentativas/mortes por combinação estratégia+ativo, calculado por `Organism._track_record`; ≥75% de morte com ≥3 tentativas = recusa, mesmo com schema perfeito). Validado: 3 mortes seguidas em momentum/BTCUSDT → 4ª tentativa recusada; mesma estratégia em ETHUSDT (histórico limpo) → aprovada normalmente |
| Nasce 1 boneco novo por proposta aprovada | Não existia esse fluxo | **Feito** — `organism.py: Organism.propose_and_spawn()`: Investigador traz proposta → Estrategista valida → se aprovada, nasce exatamente 1 avatar; se recusada, nenhum. Robô fica travado na estratégia com que nasceu (`ml/brain.py: SingleStrategyBrain` — restringe o espaço de ação do Q-learning a `[estratégia, hold]`, nunca migra pra outra) |
| Agente-robô opera só 1 ativo | Não (varria uma watchlist de até 10 símbolos) | **Feito** — `AgentConfig.symbol` (um só), atribuído pelo `Organism` no nascimento |
| Conexão com exchange / paper trading | Sim (Bybit testnet + paper) | Reaproveitado sem mudanças — `markets/crypto.py` |
| Simulação pura (sem exchange, sem chaves) | Não | **Novo** — `markets/simulated.py: SimulatedMarketAdapter` (preços sintéticos), usado por `simulate.py` |
| Visualização 2D estilo Tibia | Não (dashboard web simples) | **Pendente** — o `dashboard.py` antigo ainda assume 1 agente global; precisa ser refeito lendo `data/population.json` |
| Painel de apurações | Parcial (`evolution/dna.py: create_death_report`, por geração/linhagem) | **Pendente** — hoje o histórico de mortos já fica em `Organism.records` / `population.json`; falta uma UI |

## Próximos passos sugeridos

1. ~~Clonar `EJMM17/Bot` como base do repositório.~~ Feito — código em `trading-organism/`.
2. ~~Mapear o código existente contra a tabela acima.~~ Feito (tabela acima).
3. ~~Ajustar as regras de vida (capital, %, drawdown) pros valores exatos deste documento.~~ Feito.
4. ~~Validar o ciclo nascer→operar→clonar→morrer em simulação pura, sem Investigador/Professor reais ainda.~~
   Feito — `python -m darwin_agent.simulate` roda a população inteira sobre preços
   sintéticos (sem chaves de API). Validado dos dois jeitos: (a) rodando o
   pipeline completo (preço → decisão do brain → Estrategista → execução →
   capital muda) e (b) forçando os limiares diretamente e confirmando que o
   clone dispara em exatamente +70% do marco e a morte em exatamente -60%
   de drawdown do pico, com o `Organism` registrando pai/filho e causa da
   morte corretamente.
5. ~~Fluxo "Investigador traz estratégia -> Estrategista valida -> nasce 1
   avatar por aprovação".~~ Feito o esqueleto —
   `Organism.propose_and_spawn()`. Validado: proposta bem formada gera
   exatamente 1 boneco; proposta incompleta ou com implementação
   inexistente é recusada e não gera nenhum. Robô nasce travado na
   estratégia aprovada (não migra pra outra).
6. ~~Investigador não pode ser um catálogo fixo; Estrategista precisa de
   autonomia real de veto, não só checagem de schema.~~ Feito —
   `Investigador` agora é uma fila (`ingest`/`next_new`), populada com 3
   estratégias pesquisadas de verdade (não 1 só). `Strategist.validate_proposal`
   ganhou veto por `TrackRecord`: recusa uma combinação estratégia+ativo
   com histórico de morte ruim, mesmo com proposta tecnicamente perfeita.
   Validado com robôs reais morrendo em sequência.
7. Investigador de verdade: virar script de pesquisa CONTÍNUA de verdade
   (LLM + busca web, cron/GitHub Actions) em vez de `bootstrap_feed()`
   manual. Construir o Professor (currículo por robô/ativo) e evoluir o
   julgamento do Estrategista pra um agente/LLM com mais nuance (hoje é
   regra de threshold). Refazer `dashboard.py` e a visualização 2D lendo
   `data/population.json`; depois testar contra a Bybit testnet de verdade
   (`python -m darwin_agent --symbols BTCUSDT`).
