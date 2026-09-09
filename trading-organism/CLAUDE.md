# Organismo de Robôs Autônomos de Trade

Este arquivo é a memória do projeto. Leia isto antes de qualquer tarefa.

## Visão geral

Um "macro-organismo" de robôs de trade autônomos. Cada robô nasce pequeno,
opera uma estratégia validada, e se multiplica (clona) quando dá lucro ou é
eliminado quando dá prejuízo. O objetivo é uma população que evolui: as
estratégias boas se multiplicam, as ruins desaparecem, e o sistema fica cada
vez mais especializado por ativo.

**Não é um sistema fechado de 2-3 ativos nem de 4 estratégias fixas.** São
dois eixos abertos, ambos em constante atualização:
- **Ativos**: até ~1000 símbolos negociáveis reais (não uma listinha fixa) —
  ver `markets/symbol_universe.py`.
- **Estratégias**: um ranking vivo de até 500, realimentado continuamente
  pelo Investigador e reordenado pelos resultados reais dos robôs — ver
  `leaderboard.py`.

Cada robô é especialista num nicho bem específico — **estratégia × ativo ×
timeframe** — pra maximizar a chance de acerto dele. Um robô de 1 minuto
pode fazer 50 operações por dia; outro, no semanal, faz uma operação por
mês — os dois são válidos, contanto que seja a melhor estratégia no melhor
timeframe no melhor ativo pra aquele nicho.

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
citadas no código, cobrindo timeframes bem diferentes — de 5min a 1
semana); em produção isso é substituído por pesquisa contínua de verdade,
sem depender de sessão interativa do Claude Code.

**Cadência**: a cada ~30 minutos, uma rodada de pesquisa tenta trazer uma
estratégia nova. Cada proposta nova primeiro disputa uma vaga no ranking de
até 500 estratégias ativas (`leaderboard.py` — ver Estrategista abaixo);
uma estratégia melhor pode sobrepor (substituir) uma pior quando o ranking
está cheio.

**Pesquisa contínua de verdade — `investigator_research.py`.** Script
SEPARADO (não roda dentro do processo do Organism): chama a API da
Anthropic com a ferramenta de busca web habilitada, pede uma estratégia
atual e estruturada, e grava o resultado em `data/strategy_feed/*.json`.
Uso: `export ANTHROPIC_API_KEY=... && python -m darwin_agent.investigator_research --loop`
(roda pra sempre, uma rodada a cada `--interval` segundos — padrão 1800 =
30min; ou agendar via cron/GitHub Actions chamando sem `--loop`). O
processo principal (`Organism.poll_strategy_feed`, iniciado junto com
`run_forever` em `main.py`) observa esse diretório e injeta cada proposta
nova automaticamente — pesquisa (lenta, externa, precisa de API key) fica
desacoplada do loop de trading (rápido, sempre rodando). Testado offline
de ponta a ponta: escrevi um arquivo de proposta manualmente no diretório
e confirmei que o `Organism` detectou e fez nascer o robô certo — não
testei a chamada real à API (sem chave configurada neste ambiente de
desenvolvimento), mas o parser da resposta (`parse_proposal`) foi testado
com respostas limpas, com texto extra ao redor do JSON, e com campos
inválidos.

### 2. Professor
Recebe o material do Investigador e monta o "currículo" de ensino — mas
personalizado por robô/ativo, não uma regra genérica pra todos. Ensina o
robô a aplicar (e adaptar) a estratégia no ativo em que ele é especialista.

Implementado em `professor.py: Professor.build_curriculum(proposal, symbol)`
— pega os `params` que o Investigador trouxe (se algum) e AJUSTA pro ativo
específico: ativos "major" (BTC, ETH...) usam os parâmetros como vieram;
ativos mais ruidosos ("alt") ganham indicadores um pouco mais lentos e
stops mais largos por padrão (só preenche o que o Investigador não
especificou — a proposta original sempre tem prioridade). Se há candles
reais disponíveis, afina ainda mais pela volatilidade medida. O currículo
resultante vira `StrategyProposal`/robô com uma instância PARAMETRIZADA da
estratégia (`strategies/base.py: STRATEGY_CLASSES` + `Strategy.params`/
`Strategy.p()`) — não é mais só 4 comportamentos fixos, é 4 motores
configuráveis por proposta. Um clone herda o currículo do pai (mesmos
`params`) — clonagem literal.

### 3. Estrategista
Gatekeeper em duas camadas, com **autonomia real pra reprovar qualquer
estratégia ou operação sempre que consultado** — não é um carimbo
automático. Mesmo uma proposta com schema perfeito é recusada se o
histórico real da população mostrar que ela não está performando. Tem TRÊS
frentes de julgamento (todas em `strategist.py`):

1. **Ranking de estratégias (`leaderboard.py`, até 500)** — quando o
   Investigador traz uma proposta nova, ela primeiro disputa uma vaga:
   entra se houver espaço, ou sobrepõe a pior colocada se for melhor. Cada
   entrada é pontuada por uma razão suavizada `(clones+1)/(mortes+1)`:
   - Robô com aquela estratégia **clona** (+70%) → estratégia é
     **promovida** (sobe no ranking).
   - Robô com aquela estratégia é **eliminado** (-60% do pico) → estratégia
     é **rebaixada** (desce no ranking).
   Isso é a autonomia do Estrategista expressa como mérito acumulado real,
   não opinião.
2. **Mérito por combinação (estratégia + ativo) — `TrackRecord`**: mesmo
   uma estratégia bem colocada no ranking geral pode ser recusada pra um
   ativo ESPECÍFICO se `N` ou mais robôs já nasceram ali e a taxa de morte
   for alta demais (≥75%, amostra mínima de 3 — configurável em
   `Strategist.MIN_ATTEMPTS_BEFORE_JUDGING`/`MAX_DEATH_RATE`). A mesma
   estratégia continua liberada em outro ativo com histórico limpo.
3. **Cada sinal de entrada** antes de qualquer execução (`validate_entry`,
   reaproveitando `RiskManager`: confiança mínima adaptativa, limite diário
   de perdas, R:R mínimo, posições máximas). Se discordar, a operação não
   acontece.
4. **Pesquisa em fonte aberta, com poder de sugerir mudança** —
   `strategist_research.py` (script separado, mesmo padrão do
   Investigador: API da Anthropic + busca web habilitada). Pra cada
   proposta nova em `data/strategy_feed/`, verifica a fonte citada (ainda é
   válida? o contexto mudou?) e decide `approve` (aceita como veio),
   `reject` (recusa com motivo — a proposta NÃO nasce) ou `revise` (aceita,
   mas com `suggested_params` sobrepondo os parâmetros da proposta antes
   do nascimento). `Organism.poll_strategy_feed` espera até 60s por essa
   revisão antes de decidir nascer o robô — se não chegar a tempo, segue
   sem ela (pesquisa é reforço, não trava o sistema por atraso externo).
   Validado offline: proposta com review "reject" não gera avatar nenhum;
   proposta com review "revise" nasce com os `suggested_params` realmente
   aplicados (conferido no robô de verdade); proposta sem review dentro do
   prazo nasce normalmente depois da janela de graça.

**Resumindo como o Estrategista avalia hoje**: 3 frentes são regras
determinísticas sobre o histórico REAL da população (ranking de mérito,
taxa de morte por ativo, regras de risco por trade) — nada de opinião, só
resultado; a 4ª frente é a única que efetivamente "pesquisa" (usa uma LLM
com busca web pra checar a fonte e propor ajuste), e roda como processo
separado, assíncrono, sem travar o nascimento se atrasar. É chamado com
muita frequência — pensar nele como um serviço central, não algo que cada
robô roda isolado.

### 4. Agente-robô
- Nasce com **$5**.
- Opera um nicho bem específico: **um ativo + uma estratégia + um
  timeframe** — não escolhe livremente entre outras estratégias
  implementadas nem troca de timeframe. O timeframe vem da proposta do
  Investigador (uma estratégia de scalping roda em 1-5min; uma de swing,
  em 1d-1w) — é isso que permite um robô de 1min fazendo dezenas de trades
  por dia CONVIVER com um robô semanal fazendo ~1 por mês, cada um
  especialista no seu nicho. Um clone herda ativo + estratégia + timeframe
  do pai (é uma clonagem literal).
- Toda entrada precisa passar pelo Estrategista.
- Regras de vida (ver abaixo).

### 5. Macro-organismo (orquestrador central)
Mantém o estado de toda a população: quem existe, saldo de cada um, quem
está operando, histórico de quem já foi eliminado. É a única fonte de
verdade — tanto a simulação quanto a visualização leem daqui.

Distribui os robôs sobre um **universo de até ~1000 ativos reais**
(`markets/symbol_universe.py` — busca símbolos negociáveis de verdade na
Bybit via API pública, spot + perpétuos USDT combinados; cai num fallback
curado de ~30 pares líquidos se a rede falhar). Não é um sistema fechado
de Bitcoin/Ethereum: qualquer ativo negociável na exchange integrada entra
no pool de onde o Organism sorteia especialistas.

### 6. Visualizador
Ambiente 2D top-down (estilo Tibia): bonequinhos sentados numa mesa
operando, saldo aparece acima da cabeça, quem não está operando fica de pé
numa "lanchonete virtual". Quando um robô é eliminado, ele simplesmente
desaparece da cena e passa a existir só como registro no painel de
apurações.
Lê o estado do Macro-organismo — não tem lógica de decisão nenhuma.

**Conceito ampliado (discutido, ainda não construído):** escritório com
hierarquia visível — robôs-trader sentados em mesas/computadores no chão
do escritório; o Estrategista numa mesa/sala de supervisão (visão de
"head de operações", mostrando o ranking); o Investigador numa mesa de
pesquisa por perto; o Macro-organismo representado como a "sala da
presidência"/painel central, com a visão consolidada de tudo.

**Problema real de escala, sem resposta fácil ainda:** a população não tem
teto (ver Regras de vida) — pode crescer pra centenas ou milhares de
robôs. Um escritório literal com todo mundo visível numa tela só não
escala visualmente passado umas poucas dezenas de bonequinhos. Não dá pra
"escanear" (renderizar) a população inteira de uma vez de forma legível
sem alguma estratégia de agregação — andares/salas por faixa de
performance, uma visão de grade/heatmap pra escala + clique pra abrir o
escritório individual, ou um teto de bonequinhos visíveis com o resto
resumido num contador. Isso precisa de uma decisão de design antes de
qualquer código de jogo — o painel de apurações (tabela, já pronto) não
tem esse problema porque tabela escala por scroll/paginação, jogo com
sprites não escala do mesmo jeito.

Stack sugerida (ainda a mesma da concepção original, não mudou):
Phaser.js + Tiled. É um projeto de verdade à parte (arte de sprite, mapa,
lógica de câmera/interação) — maior que qualquer peça construída até
agora nesta sessão.

### 7. Painel de apurações
Dashboard com o histórico completo: todo robô que já existiu, pico de
capital, causa da morte (drawdown) ou geração de clones, tempo de vida,
estratégia usada. Também só lê o estado do Macro-organismo.

**Feito** — `dashboard.py` reescrito do zero (a versão antiga assumia 1
agente global, não fazia mais sentido). Web app em tempo real (aiohttp +
HTML/JS puro, polling a cada 3s — não precisa de websocket, os heartbeats
dos robôs já são de dezenas de segundos a horas): estatísticas gerais
(vivos/total/capital/ranking), tabela do ranking de estratégias, e tabela
com TODO robô que já existiu (pai, ativo, estratégia, timeframe, status,
capital, pico, drawdown, trades, win rate, clones gerados, tempo de vida,
causa da morte). Sobe automaticamente junto com `main.py run_forever` na
porta `config.dashboard_port`; só leitura, sem lógica de decisão. Testado
de verdade: gerei um `population.json` com clonagem em cadeia e uma morte,
subi o servidor, e tirei um screenshot via Chromium headless confirmando
que renderiza certo (hierarquia pai/filho, badges de status, cores por
score/drawdown).

**Posições (entrada/saída por operação)** — sem gráfico (decisão consciente:
gráfico de preço pesa a operação sem necessidade agora). Cada posição
fechada vira um registro completo em `data/logs/trades_<robot_id>.jsonl`
(`utils/logger.py: DarwinLogger.position_closed()`): símbolo, lado
(buy/sell), preço/hora de entrada, preço/hora de saída, duração, P&L. Uma
tabela nova no painel (`/api/positions`) mostra isso pra toda a população,
mais recente primeiro. Antes só a ENTRADA era logada; a saída não tinha
registro nenhum — corrigido. Testado com uma operação real (abrir + fechar
via `PaperTradingAdapter`) até aparecer certinho na tabela do painel.
Nota de escala: a API varre todos os arquivos `trades_*.jsonl` a cada
consulta — funciona bem nesta fase, mas com centenas de robôs vai precisar
de índice/banco em vez de varrer arquivo por arquivo.

**Como cada robô opera** — cards por robô mostrando símbolo, estratégia,
timeframe, indicadores (chips), regra de entrada/saída/risco em linguagem
clara, e o **histórico do Estrategista pra aquela combinação exata**
(estratégia+ativo): quantas tentativas, quantos clones, quantas mortes,
% de mortalidade — o mesmo número que `Strategist.validate_proposal` usa
pra julgar, agora visível. `organism.py`: `RobotRecord` ganhou os campos
de descrição da estratégia (`strategy_indicators/entry_rule/exit_rule/
risk_management`, herdados pelo clone do pai) e `Organism._all_track_records()`
calcula o histórico por (estratégia, ativo) pra toda combinação que já
existiu, incluído em `population.json` como `track_records`. Testado:
gerei uma população com uma combinação repetida (2 tentativas, 1 morte) e
confirmei no card exatamente "2 tentativa(s) · 0 clone(s) · 1 morte(s) ·
mortalidade 50%".

**Patrimônio (gráfico de evolução do capital)** — decisão revista: o
gráfico de preço/candle continua fora (pesa a operação sem necessidade),
mas um gráfico de **capital por robô ao longo do tempo** foi pedido e
construído, porque `population.json` só guarda o "agora" (sobrescrito a
cada save) — sem histórico não dava pra desenhar curva nenhuma.
`organism.py: Organism._record_history()` grava um snapshot append-only em
`data/history.jsonl` (timestamp, capital de cada robô vivo, capital vivo
total) periodicamente dentro do próprio `run_until()` (parâmetro
`history_interval_ticks`, mais espaçado que o save de estado — não precisa
de um ponto por tick). Nova rota `/api/history` (`dashboard.py`) expõe as
últimas N linhas. Card novo no painel ("Patrimônio"): filtros por
estratégia/ativo/status pra restringir a lista de robôs, um seletor com
checkbox por robô, toggle **"Mesclar selecionados numa linha"** (soma o
capital dos selecionados em uma única série) vs. modo padrão (uma linha
por robô, cor própria, legenda), e um checkbox **"Global"** (linha com o
capital vivo total da população, independente da seleção). Gráfico é SVG
desenhado à mão em JS puro (sem lib externa, mesmo padrão do resto do
painel — mais robusto pra deploy em VPS sem depender de CDN). Testado de
verdade: população sintética com 5 robôs (1 clone, 1 morte por drawdown)
ao longo de 40 pontos de histórico, screenshot via Chromium headless
confirmando os 4 modos — Global, overlay por robô, mesclado (soma), e
filtro por estratégia restringindo a lista sem perder a seleção já feita.

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
- **O crescimento é só via multiplicação de robôs, nunca via aumento de
  capital por trader.** O saldo de cada robô pode acumular (o original não
  reseta ao clonar, ver acima), mas isso é só um placar — a APOSTA por
  operação fica sempre ANCORADA no capital inicial ($5), nunca cresce
  proporcionalmente ao saldo acumulado. Um robô que já tem $20 arrisca por
  trade o equivalente a quando tinha $5, no dia em que nasceu. Implementado
  em `core/agent_v2.py: _execute()` — `risk_basis = min(starting_capital,
  current_capital)` (só reduz o risco se o robô estiver com MENOS do que
  começou, nunca aumenta por ter mais). Não construir nenhuma feature nova
  de "aposta cresce com o capital acumulado" sem confirmar antes.
- **Eliminação**: quando o capital cai **60% a partir do pico** que aquele
  robô já alcançou (drawdown desde o topo, não desde o valor atual), o
  robô é fechado/removido.
- **Sem limite** de multiplicação — a intenção é crescimento exponencial.
  Não existe (e não deve ser adicionado) nenhum teto de população/clones em
  lugar nenhum do código — nem `Organism`, nem `DarwinAgentV2`. Boas
  estratégias **têm que rentabilizar** (clonar sem parar, geração após
  geração); as ruins são simplesmente **demitidas** (eliminadas em -60% do
  pico) — a seleção é só isso, nunca um limite artificial. Validado:
  forçando 4 gerações seguidas de +70%, a população cresce 1→2→4→8→16 sem
  nenhum teto interferir; uma estratégia perdedora é eliminada normalmente
  no mesmo teste.
- Auto-otimização = o próprio evento de clonagem/eliminação — reforçado
  agora pelo ranking de estratégias (`leaderboard.py`) e pelo currículo do
  Professor (`professor.py`), mas a régua final de quem sobrevive continua
  sendo só isso: rentabiliza e clona, ou não rentabiliza e é demitido.

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
| Investigador (fluxo contínuo de pesquisa, NÃO um catálogo fixo) | Não | **Feito** — `investigator.py: Investigador` é uma fila (`ingest`/`next_new`); `bootstrap_feed()` continua como ponto de partida pra dev/simulação (4 estratégias reais). **Pesquisa contínua de verdade**: `investigator_research.py` — script separado, chama a API da Anthropic com busca web, grava propostas em `data/strategy_feed/`; `Organism.poll_strategy_feed()` absorve automaticamente. Testado offline de ponta a ponta (arquivo → robô nascido); parser de resposta testado com casos limpo/sujo/inválido — chamada real à API não testada (sem chave neste ambiente) |
| Professor (currículo por robô/ativo) | Não | **Feito** — `professor.py: Professor.build_curriculum()`. Ajusta os parâmetros da estratégia pro ativo específico (major vs. alt, e por volatilidade medida quando há candles). Testado: dois robôs com a mesma proposta em BTCUSDT vs. DOGEUSDT recebem currículos diferentes; clone herda o currículo idêntico do pai |
| Parametrização fina por proposta (EMA 9/21 vs 12/26 etc, não só 4 comportamentos fixos) | Não (períodos de indicador hardcoded em cada estratégia) | **Feito** — `strategies/base.py`: `Strategy.__init__(params)` + `Strategy.p(key, default)`; as 4 classes (`MomentumStrategy`, `MeanReversionStrategy`, `ScalpingStrategy`, `BreakoutStrategy`) agora leem período de EMA/RSI/ATR/Bollinger, multiplicadores de stop/TP, etc. dos `params` em vez de literais fixos (comportamento idêntico ao original quando `params` está vazio). `STRATEGY_CLASSES` permite instanciar uma cópia nova e parametrizada por robô (`core/agent_v2.py` troca a entrada do `AdaptiveSelector` correspondente à `strategy_name` do robô) |
| Estrategista (2 camadas, com autonomia real de veto) | Parcial (só `RiskManager.approve_trade`, sem camada 1) | **Feito** — `strategist.py: Strategist`, serviço único compartilhado por toda a população. Camada 2 (`validate_entry`, cada sinal) reaproveita `RiskManager`. Camada 1: `validate_strategy` (sanidade genérica) + `validate_proposal` (schema + **veto por histórico real**: `TrackRecord` conta tentativas/mortes por combinação estratégia+ativo, calculado por `Organism._track_record`; ≥75% de morte com ≥3 tentativas = recusa, mesmo com schema perfeito). Validado: 3 mortes seguidas em momentum/BTCUSDT → 4ª tentativa recusada; mesma estratégia em ETHUSDT (histórico limpo) → aprovada normalmente |
| Nasce 1 boneco novo por proposta aprovada | Não existia esse fluxo | **Feito** — `organism.py: Organism.propose_and_spawn()`: Investigador traz proposta → Estrategista valida → se aprovada, nasce exatamente 1 avatar; se recusada, nenhum. Robô fica travado na estratégia com que nasceu (`ml/brain.py: SingleStrategyBrain` — restringe o espaço de ação do Q-learning a `[estratégia, hold]`, nunca migra pra outra) |
| Agente-robô opera só 1 ativo + 1 estratégia + 1 timeframe | Não (varria uma watchlist de até 10 símbolos, todas as 4 estratégias, timeframe global fixo) | **Feito** — `AgentConfig.symbol`/`scan_timeframe` atribuídos pelo `Organism` no nascimento a partir da proposta; `SingleStrategyBrain` trava a estratégia |
| Universo de ~1000 ativos reais (não fechado em 2-3 símbolos) | Não (watchlist de até 10, hardcoded) | **Feito** — `markets/symbol_universe.py: fetch_symbol_universe()` busca símbolos reais negociáveis na Bybit (API pública `/v5/market/instruments-info`, spot+linear USDT, paginado), com fallback curado se a rede falhar. Testado offline com fixtures (paginação, filtro por moeda/status, dedup entre categorias, fallback) — rede real bloqueada neste sandbox de dev por política de egress, funciona em produção (VPS). `main.py --universe 1000` usa isso |
| Ranking vivo de até 500 estratégias, promovido/rebaixado por resultado real | Não existia | **Feito** — `leaderboard.py: StrategyLeaderboard`. `promote()` no evento de clonagem (+70%), `demote()` no evento de eliminação (-60%), `consider()` decide se uma proposta nova do Investigador entra ou sobrepõe a pior colocada. Score = razão suavizada clones/mortes. Testado: capacidade respeitada, promoção/rebaixamento reais via `Organism._handle_clone`/`_handle_death`, substituição da pior colocada quando o ranking está cheio |
| Timeframe como parte da especialização (1min "diarista" convivendo com 1w "position") | Não (`scan_timeframe` era global, só até 1d) | **Feito** — `StrategyProposal.timeframe`, `TimeFrame.W1` adicionado, `Organism._new_config` aplica por robô; `heartbeat_by_timeframe=True` (main.py) escala o intervalo de checagem pelo timeframe (1min→30s, 1w→6h) — não faz sentido um robô semanal pollar toda hora |
| Conexão com exchange / paper trading | Sim (Bybit testnet + paper) | Reaproveitado sem mudanças — `markets/crypto.py` |
| Simulação pura (sem exchange, sem chaves) | Não | **Novo** — `markets/simulated.py: SimulatedMarketAdapter` (preços sintéticos), usado por `simulate.py` |
| Visualização 2D estilo Tibia (bonequinhos, escritório) | Não (dashboard web simples) | **Pendente** — decisão de design em aberto (ver seção "Visualizador 2D" abaixo); painel de apurações (tabela) já cobre a parte de dados, o "jogo" em si ainda não foi construído |
| Painel de apurações | Parcial (`evolution/dna.py: create_death_report`, por geração/linhagem) | **Feito** — `dashboard.py` reescrito, tempo real, lendo `data/population.json`. Testado com screenshot de verdade (Chromium headless) sobre dados com clonagem em cadeia e morte |

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
7. ~~Universo de ~1000 ativos reais (não fechado); ranking vivo de até 500
   estratégias promovido/rebaixado pelos eventos reais dos robôs; timeframe
   como parte da especialização (robô de 1min convivendo com robô
   semanal).~~ Feito — `markets/symbol_universe.py` (busca real na Bybit,
   testado offline com fixtures por bloqueio de rede no sandbox de dev),
   `leaderboard.py` (`StrategyLeaderboard`, capacidade 500, `consider`/
   `promote`/`demote`), `TimeFrame.W1` + `StrategyProposal.timeframe` +
   `Organism._new_config`. Validado com objetos reais: proposta semanal
   nasce com `scan_timeframe=1w`, clone herda o timeframe do pai, clonagem
   promove a estratégia no ranking (score sobe), morte rebaixa (score
   desce), ranking cheio só aceita entrada nova se ela superar a pior
   colocada.
8. ~~Investigador de pesquisa CONTÍNUA de verdade (script separado, LLM +
   busca web, a cada ~30min); Professor (currículo por robô/ativo);
   parametrização fina por proposta (não só 4 comportamentos fixos).~~
   Feito — `investigator_research.py` (script separado, `--loop`
   embutido ou cron/GitHub Actions, grava em `data/strategy_feed/`) +
   `Organism.poll_strategy_feed()` (absorve automaticamente, iniciado
   junto com `main.py run_forever`). `professor.py: Professor` monta o
   currículo por (proposta, ativo). `strategies/base.py`: as 4 estratégias
   agora leem parâmetros de indicador/stop via `Strategy.params`/`.p()`
   em vez de literais fixos — cada proposta pode ser genuinamente
   diferente, não só 4 comportamentos hardcoded. Testado offline de ponta
   a ponta (arquivo de proposta → robô nascido com o currículo certo);
   chamada real à API da Anthropic não testada nesta sessão (sem
   `ANTHROPIC_API_KEY` configurada aqui).
9. **Reforçado e validado nesta rodada**: não existe (nem deve existir)
   nenhum teto de multiplicação — testado forçando 4 gerações seguidas de
   clonagem (1→2→4→8→16 robôs) e confirmando que uma estratégia perdedora
   é eliminada normalmente no mesmo cenário.
10. ~~Aposta ancorada no capital inicial (não crescer com o saldo
    acumulado); Estrategista pesquisar fonte aberta e poder sugerir
    mudança de parâmetros.~~ Feito — `core/agent_v2.py: _execute()`
    ancora o cálculo de risco em `min(starting_capital, current_capital)`
    (só reduz risco se o robô estiver pior do que quando nasceu, nunca
    aumenta por ter crescido). `strategist_research.py` (script separado,
    API da Anthropic + busca web): revisa cada proposta em
    `data/strategy_feed/`, pode `approve`/`reject`/`revise` (com
    `suggested_params`); `Organism.poll_strategy_feed` espera até 60s pela
    revisão antes de nascer o robô, sem travar se atrasar. Validado
    offline: reject impede o nascimento, revise aplica os params
    sugeridos de verdade no robô, ausência de review dentro do prazo não
    trava o sistema.
11. ~~Painel de apurações lendo `data/population.json`.~~ Feito —
    `dashboard.py` reescrito (tempo real, polling 3s), sobe junto com
    `main.py run_forever`. Testado com screenshot de verdade sobre dados
    reais (clonagem em cadeia + morte).
12. ~~Painel: como cada robô opera (estratégia + histórico do
    Estrategista); posições com entrada/saída; gráfico de patrimônio por
    robô, mesclável e com visão global.~~ Feito — ver seção "Painel de
    apurações" acima (cards "Como cada robô opera", "Posições", e
    "Patrimônio" com `/api/history`, `Organism._record_history()`, SVG
    puro em JS).
13. Visualizador 2D (o "jogo" — escritório, bonequinhos, Estrategista/
    Investigador/Macro-organismo como estações especiais): decisão de
    design pendente sobre como lidar com escala (população sem teto vs.
    tela renderizável) antes de escrever qualquer código — ver seção
    "Visualizador" acima. Evoluir o julgamento do Estrategista (hoje é
    regra de threshold + pesquisa determinística) pra um agente/LLM com
    mais nuance ainda. Testar contra a Bybit testnet de verdade
    (`python -m darwin_agent --universe 1000 --roots 5`), incluindo
    `investigator_research.py --loop` e `strategist_research.py --loop`
    rodando em paralelo com uma `ANTHROPIC_API_KEY` de verdade.
