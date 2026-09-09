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
| Investigador (pesquisa de estratégias) | Não | **Pendente** — construir como sub-agente novo |
| Professor (currículo por robô/ativo) | Não | **Pendente** — construir como sub-agente novo |
| Estrategista (2 camadas) | Parcial (só `RiskManager.approve_trade`, sem camada 1) | **Feito o esqueleto** — `strategist.py: Strategist`, serviço único compartilhado por toda a população. Camada 1 (`validate_strategy`, no nascimento) e camada 2 (`validate_entry`, cada sinal) hoje são checagens determinísticas; ponto de extensão pra virar um agente/LLM depois |
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
5. Construir Investigador, Professor e a camada 1 real do Estrategista
   (hoje é só uma checagem de sanidade); refazer `dashboard.py` e a
   visualização 2D lendo `data/population.json`; depois testar contra a
   Bybit testnet de verdade (`python -m darwin_agent --symbols BTCUSDT`).
