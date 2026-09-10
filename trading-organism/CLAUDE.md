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
  ver `markets/symbol_universe.py`. **Não é só cripto** — também índices
  globais, commodities, futuros e ações de bolsa via `markets/yahoo.py`
  (Yahoo Finance/`yfinance`, grátis, sem cadastro nem chave — decisão
  explícita do usuário, ver "Macro-organismo" abaixo pro porquê dessa
  fonte). `Organism`/`DarwinAgentV2` só conversam com a interface abstrata
  `MarketAdapter` (`markets/base.py`) — adicionar OUTRA classe de ativo
  ainda (ex: uma fonte paga com contrato de verdade) é só escrever mais um
  adapter, não reescrever o organismo.
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

**Multi-asset (além de cripto) — Feito.** Pedido explícito do usuário:
não é só cripto, também índices globais, commodities, futuros e ações de
bolsa. Decisão de fonte de dados (o usuário escolheu entre 3 opções, ver
histórico): **Yahoo Finance via `yfinance`**, não TradingView (sem API
oficial, só scraping) nem Alpha Vantage/Twelve Data (API oficial de
verdade, mas cadastro + chave + cobertura mais fraca de índices/commodities
no tier grátis). `yfinance` também não é oficial — mesma categoria de
ressalva do TradingView, só que é uma lib madura e amplamente usada, ao
contrário de scraping ad-hoc; pode quebrar sem aviso se a Yahoo mudar algo,
sem SLA. Trocar de fonte depois é só escrever outro `MarketAdapter`.

- `markets/yahoo.py: YahooFinanceAdapter` — só fornece preços (igual todo
  adapter deste projeto, nunca executa ordem real). `yfinance` é síncrono/
  bloqueante — toda chamada passa por `asyncio.to_thread` pra não travar o
  event loop e os outros robôs concorrentes. Não tem intervalo nativo de
  4h — busca 1h e reamostra via `pandas.resample` (OHLC agregado
  corretamente: open=primeiro, high=máx, low=mín, close=último, volume=soma).
- `markets/multi_asset_universe.py` — lista curada à mão (Yahoo não tem um
  endpoint público de "lista todos os símbolos", diferente da Bybit) com
  índices (`^GSPC`, `^BVSP`, `^DJI`...), commodities/futuros (`GC=F` ouro,
  `CL=F` WTI...), ações US (`AAPL`, `MSFT`...) e ações B3 (`PETR4.SA`,
  `VALE3.SA`...).
- **Roteamento por classe de ativo** — o ponto estrutural real desse
  trabalho, não só "adicionar um adapter": um robô especialista em AAPL não
  pode tentar conversar com a Bybit, e vice-versa. `Organism(asset_classes=
  {symbol: market_name})` mapeia cada símbolo pro mercado certo;
  `Organism._new_config()` só deixa HABILITADO, na config daquele robô
  específico, o mercado da classe de ativo do símbolo dele (todos os outros
  ficam desligados ali, mesmo que estejam ligados globalmente). CLI:
  `--assets crypto,stocks` (ou só um dos dois) liga as classes desejadas
  nessa execução.
- **Dois bugs reais na mesma categoria, achados e corrigidos**: (1)
  `_fetch_recent_candles` (candles pro currículo do Professor e pro
  backtest) pegava "o primeiro mercado habilitado" em vez do mercado da
  classe de ativo do símbolo — com crypto+stocks habilitados ao mesmo
  tempo, isso faria o Organism backtestar AAPL com adapter/dado de cripto.
  (2) O loop de diagnóstico de pre-flight em `main.py` (`bybit_errors.
  run_diagnostics`) rodava pra QUALQUER mercado habilitado, inclusive
  "stocks" — mas é um diagnóstico específico da Bybit (assinatura HMAC,
  endpoints da API), sem sentido nenhum pra um mercado sem chave/API key
  como o Yahoo. Os dois corrigidos com checagem explícita por nome de
  mercado.
- Testado de ponta a ponta: unit puro do roteamento (`_new_config` sem
  precisar de rede/adapter nenhum), `YahooFinanceAdapter` com candles
  mockados (1h, reamostragem pra 4h, preço atual, falha de rede não
  derruba o robô), e um robô de ação nascendo pelo caminho de PRODUÇÃO
  real (sem injetar adapter de teste) conectando de verdade num
  `YahooFinanceAdapter` — e uma execução real via `--assets stocks` que
  chegou a tentar rede de verdade (bloqueada neste sandbox por política,
  mas os robôs nasceram e degradaram graciosamente sem crashar, exatamente
  como o resto do sistema já fazia pra falha de rede da Bybit).

**Retomada de estado (resume) — Feito.** Decisão do usuário: rodar de
graça no próprio computador, desligando quando quiser, mas SEM perder
progresso a cada restart (capital acumulado, cérebro de Q-learning
aprendido, marco de clonagem). Antes disso, `main.py run_forever` sempre
nascia uma população nova do zero a cada execução — `population.json` era
só um retrato pro painel, não um ponto de retomada.

Agora existe um segundo arquivo, `data/organism_state.json` (separado do
`population.json` leve, pra não inchar o que o painel lê), com tudo que é
necessário pra religar cada robô vivo EXATAMENTE de onde parou:
- `Organism.save_full_state()` — grava o `RobotRecord` de todo mundo (vivo
  e morto) + `DarwinAgentV2.export_state()` de cada robô vivo (saúde,
  cérebro via `selector.export_for_dna()` — reaproveitando a mesma
  infraestrutura que já existia pra herança de clone —, marco de
  clonagem, cooldown) + o ranking de estratégias + a fila de pendências da
  Sala de Risco + o índice de rotação de símbolos. Chamado no mesmo
  intervalo do save leve dentro de `run_until`, e mais uma vez no
  `finally` de `main.py` (Ctrl+C não pode perder o intervalo entre saves).
- `Organism.resume_from_state()` — lê esse arquivo (se existir) e religa
  cada robô vivo como uma `DarwinAgentV2` nova + `import_state()` (não
  nasce de novo); robôs mortos voltam só como registro histórico, sem
  religar tarefa nenhuma. Retorna `False` se não havia nada salvo
  (primeira execução) — `main.py` só bootstrap uma população nova nesse
  caso (ou se a população salva estava extinta).

**Dois bugs reais encontrados e corrigidos no caminho** (só apareceriam
com retomada de verdade, por isso passaram despercebidos até agora):
1. `_init_markets()` sempre criava o `PaperTradingAdapter` com saldo =
   `starting_capital` (nunca o capital acumulado) — um robô retomado com
   $23 veria o saldo voltar pra $5 assim que a primeira posição fechasse
   e `get_balance()` fosse lido. Corrigido com `_paper_balance_override`.
2. `Brain.import_brain()` aplica um "boost" de epsilon (`min(0.3,
   epsilon*1.5)`) pensado pra herança de CLONE (mais exploração no filho)
   — ignorava `mutation_rate=0.0` e distorcia o epsilon numa retomada
   exata (não é um clone, é o mesmo robô). `DarwinAgentV2.import_state()`
   restaura o epsilon salvo ao pé da letra por cima, sem tocar no método
   compartilhado (clonagem continua com o comportamento de sempre).

Testado de ponta a ponta com objetos reais: population + capital + cérebro
(pesos não-triviais) + marco de clonagem + clones_generated + leaderboard
+ fila da Sala de Risco, tudo simulando um "restart do processo"
(`Organism` novo do zero lendo o arquivo salvo pelo `Organism` anterior) —
cada valor bate exatamente com o que foi salvo, robô morto não religa, e
o saldo do adapter de paper trading não reseta.

### 6. Visualizador — ABANDONADO (decisão explícita)
Ideia original: ambiente 2D top-down estilo Tibia/escritório (bonequinhos
sentados operando, Estrategista/Investigador/Macro-organismo como salas
especiais). Chegou a ser avaliada com referência de mercado
(`paulrobello/claude-office`, MIT, Next.js+PixiJS+FastAPI — visual bem
próximo do que se imaginava aqui) e esbarrou num problema real de escala
nunca resolvido: população sem teto de nicho não escala visualmente num
escritório literal sem alguma estratégia de agregação por andares/salas.

**Decisão do usuário: abandonar o jogo/escritório 2D.** Em vez disso, o
painel de apurações (dados, tabela/grade) é o único "visual" do sistema —
mais leve, mais informativo, e escala por scroll em vez de sprites.
Não retomar esta ideia sem o usuário pedir explicitamente de novo. Ver
"Como cada robô opera" na seção 7 pra como a visão por robô foi resolvida
dentro do painel (blocos coloridos + lista).

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

**Como cada robô opera** — depois de abandonar o Visualizador 2D (ver
seção 6), este é o substituto: dois modos de visão, alternáveis por botão
(`▦ Blocos` / `☰ Lista`), sem recarregar dados (cache local do último
`/api/state`, `renderOpsSection()` em `dashboard.py`):
- **Blocos (padrão, leve)** — um pequeno retângulo arredondado por robô
  (`.robot-tile`, ~68x62px), cor pelo RESULTADO (verde por faixas de ganho,
  cinza pra flat, vermelho pra perda/morto, "✕" nos mortos), mostrando
  ativo + **saldo acumulado em $** (não só %) + % de ganho/perda como linha
  secundária, detalhe completo (estratégia, capital, trades, entrada/
  saída/risco, histórico do Estrategista, causa da morte) no tooltip
  (`title`, sem JS extra). Sem teto de exibição — testado com 70 robôs
  simultâneos, renderiza tudo (viável porque cada bloco é pequeno; o antigo
  card grande tinha um teto de 40 por peso visual).
- **Lista (detalhado)** — os cards antigos (símbolo, estratégia, timeframe,
  **saldo acumulado explícito** ("Saldo acumulado: $X (pico $Y)"),
  indicadores em chips, entrada/saída/risco por extenso, e o **histórico do
  Estrategista pra aquela combinação exata** — estratégia+ativo: tentativas,
  clones, mortes, % de mortalidade, o mesmo número que
  `Strategist.validate_proposal` usa pra julgar), agora dentro de um
  contêiner com scroll pra não pesar a página inteira.

Dados por trás dos dois modos: `organism.py`: `RobotRecord` tem os campos
de descrição da estratégia (`strategy_indicators/entry_rule/exit_rule/
risk_management`, herdados pelo clone do pai) e `Organism._all_track_records()`
calcula o histórico por (estratégia, ativo) pra toda combinação que já
existiu, incluído em `population.json` como `track_records`. Testado com
screenshot real nos dois modos (70 robôs sintéticos, ganhos/perdas
variados) e confirmando a troca de modo sem duplicar exibição.

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

### 8. Sala de Risco (Estrategista toma conta)

Motivada por um problema real identificado na própria arquitetura: seleção
por multiplicação sem controle de concentração significa que uma estratégia
vencedora pode virar dezenas de robôs apostando exatamente a mesma coisa,
no mesmo ativo, ao mesmo tempo — se o mercado se mover contra essa aposta,
todos morrem juntos (drawdown correlacionado), não um por um como a regra
de eliminação individual (-60% do pico) sozinha sugere. A Sala de Risco é
essa camada de contenção — toda a autoridade de decisão vive em
`strategist.py: Strategist` (constantes e métodos abaixo), o `organism.py`
só apura os fatos (contagens) e executa.

**Camada 1 — teto por nicho (`MAX_ROBOTS_PER_NICHE = 10`)**: no máximo 10
robôs vivos simultâneos numa combinação EXATA de estratégia+ativo
(`Organism._niche_key` — mesmo `strategy_id`, não só a família
"momentum"). Quando um robô bate +70% e o nicho dele já está no teto
(`Strategist.check_niche_capacity`), a clonagem não gera uma cópia
idêntica — vira um pedido de otimização.

**Otimização automática (`Strategist.suggest_optimization`)**: parte do
robô de MAIOR capital atual no nicho saturado (`Organism._best_in_niche`,
não do robô que disparou o evento) e aplica um jitter aleatório de ±15%
nos parâmetros numéricos da estratégia. O resultado ganha um `strategy_id`
novo (`Strategist.variant_strategy_id`, hash dos parâmetros) — ou seja,
vira um NICHO PRÓPRIO, com attempts=0 e seu próprio teto de 10, sem
competir pela cota do nicho que o originou. V1 deliberadamente simples
(perturbação aleatória, não guiada por atribuição de qual parâmetro
historicamente correlaciona com melhor resultado) — um próximo passo
natural de evolução, não construído ainda.

**Camada 2 — teto global (`MAX_POPULATION_ALIVE = 180`)**: no máximo 180
robôs vivos no total, qualquer nicho. Contém o capital real total sob
gestão (cada robô vivo é uma conta operando de verdade, mesmo que a aposta
por trade continue ancorada em `starting_capital`).

**Fila de espera, não recusa definitiva**: um pedido de clone/otimização
barrado só por teto (não por mérito) entra em `Organism._pending_clones`
(FIFO) em vez de ser descartado. Toda morte real (-60% do pico) libera
exatamente uma vaga — `Organism._drain_pending_clones` primeiro tenta
atender quem esperava pelo MESMO nicho que acabou de perder um robô,
senão atende o pedido mais antigo da fila que já cabe. Se o robô-base de
um pedido morrer enquanto espera, o pedido é descartado (não faz sentido
clonar de quem não existe mais).

**Camada 0 — backtest antes de nascer (`backtest.py`)**: antes de QUALQUER
proposta nova arriscar capital real (mesmo só $5), roda a mesma lógica de
análise que o robô usaria ao vivo (`strategies/base.py: Strategy.analyze`)
sobre candles históricos reais (mesmo adapter que os robôs usam,
`Organism._run_backtest`), com janela deslizante e fills simplificados por
stop/take-profit. `Strategist.judge_backtest` decide: sem dados
históricos ou amostra menor que `MIN_BACKTEST_TRADES=5` não bloqueia
sozinho (inconclusivo); abaixo de `MIN_BACKTEST_WIN_RATE=0.35` de acerto
OU retorno pior que `MAX_BACKTEST_LOSS_PCT=-20%` reprova antes de gastar
capital real. Testado com candles sintéticos de random walk puro (sem
edge real) — o backtest corretamente reprovou 2 das 4 estratégias-semente
nesse cenário, confirmando que a camada tem poder de discriminação de
verdade, não é carimbo automático.

**Aposta menor por trade = track record mais longo**: `RiskConfig.
max_position_pct` reduzido de 2.0% para 1.0% (`utils/config.py`) — aposta
menor sobre o `risk_basis` ancorado significa mais trades até bater
+70%/-60%, dando ao Estrategista/leaderboard uma amostra maior antes de
julgar por mérito (mitiga julgamento por amostra pequena, um risco
identificado nesta mesma rodada de revisão).

**Painel**: card "Sala de Risco (Estrategista)" no `dashboard.py`, lendo
`population.json: risk_room` (calculado por `Organism._risk_room_report`,
sem rota nova — já vinha no `/api/state` existente): barra de
uso do teto de população, barra de nichos no limite, aviso de pedidos
pendentes, tabela de concentração por nicho (com badge "otimização" nas
variantes) e por ativo. Testado com screenshot real: nicho saturado em
10/10, 3 variantes de otimização com `strategy_id` distintos, 2 pedidos
pendentes visíveis, tudo lido do estado real da população.

### 9. A Mesa (aprovação humana de estratégia nova) — Feito

Decisão explícita do usuário, além de tudo que a Sala de Risco já filtra
automaticamente: **nenhuma estratégia nova senta à mesa sem você
aprovar**, depois de passar por toda a análise (ranking, track record,
teto de nicho/população, backtest). Isso é só pra ESTRATÉGIA NOVA (robô
raiz) — **clones continuam 100% automáticos**, sem gate humano nenhum
(multiplicação de uma estratégia já aprovada não é "estratégia nova
pedindo cadeira"). Execução de cada trade individual também continua
automática (Q-learning + `Strategist.validate_entry`) — a aprovação
humana é só sobre "essa estratégia merece existir", nunca sobre "esse
trade específico pode acontecer".

**A Mesa tem 10 cadeiras** (`Strategist.MAX_ROOT_SEATS = 10`) — no máximo
10 estratégias distintas com um robô RAIZ vivo ao mesmo tempo. Uma cadeira
representa o ROBÔ raiz especificamente (decisão do usuário): se a raiz
morre, a cadeira libera — mesmo que aquela estratégia ainda tenha clones
vivos e lucrativos por aí (os clones continuam operando normalmente, só
não "seguram" a cadeira da linhagem). Cadeiras OCUPADAS OU RESERVADAS
(vivas + pendentes de aprovação) contam pro teto — sem isso dava pra
enfileirar 20 propostas e aprovar todas, furando o limite de 10 (bug real
encontrado e corrigido durante os testes).

**Cadência de 30 minutos** (`Strategist.MIN_MINUTES_BETWEEN_ROOTS = 30`)
— fora do bootstrap inicial, uma cadeira vaga só é oferecida ao
Investigador de novo a cada 30 minutos (`Organism._last_root_proposal_at`),
mesmo que a fila de pesquisa contínua (`poll_strategy_feed`) tenha mais
propostas prontas. O bootstrap inicial (`main.py --roots 10`,
`simulate.py`) usa `propose_and_spawn(..., bypass_root_cooldown=True)`
pra encher a mesa de largada sem esperar 5 horas (10 × 30min) — a
cadência é pra regime permanente, não pro primeiro preenchimento.

**Fluxo**: `Organism.propose_and_spawn()` roda TODA a análise automática
igual antes (ranking, track record, cadeira, cadência, Sala de Risco,
backtest) — mas em vez de nascer no final, empacota tudo
(`_queue_for_approval`) numa entrada de `_pending_approvals`: o texto da
estratégia (nome/indicadores/regras de entrada-saída-risco/fonte), o
**track record real** dessa combinação (estratégia+ativo) até agora
(`Organism._track_record`, o mesmo número que o Estrategista usa pra
julgar), e **por que o Estrategista acha que é vencedora** (as 3 razões
que ela já passou: admissão no ranking, mérito por track record, backtest).
`Organism.approve_pending(id)` spawna de verdade com os dados já
calculados (currículo, backtest); `Organism.reject_pending(id)` só
descarta.

**Painel deixa de ser só leitura — única exceção deliberada**: novo card
"A Mesa — aprovações pendentes" (barra de cadeiras, aviso de cadência,
lista de propostas com botão Aprovar/Recusar por proposta). `dashboard.py`
ganha `set_organism()` — como o painel roda no MESMO processo/event loop
que o `Organism` (`asyncio.create_task` dentro de `main.py`), as rotas
`POST /api/approve`/`POST /api/reject` chamam `approve_pending`/
`reject_pending` diretamente, sem precisar do padrão de arquivo-como-IPC
usado em `strategy_feed`/`strategy_reviews`. Isso não quebra "painel sem
lógica de decisão": o painel só relay a SUA decisão (o clique), o
julgamento inteiro (ranking/track record/backtest/cadeira) já rodou antes,
no Organism, sem o painel participar.

**Bootstrap expandido pra 10 propostas distintas**: `investigator.py:
bootstrap_feed()` tinha só 4 estratégias-semente; agora tem 10 (mesmo
estilo — fontes reais citadas, indicadores/regras concretas), cobrindo os
4 engines existentes (`momentum`/`mean_reversion`/`scalping`/`breakout`)
com timeframes/ativos variados — o número não é acidental, é o suficiente
pra encher as 10 cadeiras sem depender de `investigator_research.py`
rodando de verdade (precisa de `ANTHROPIC_API_KEY`) só pra testar local.
`main.py --roots` mudou o padrão de 1 pra 10 pra bater com "a mesa começa
cheia".

Testado de ponta a ponta com objetos reais: as 10 propostas do bootstrap
entram na fila e NENHUMA nasce sozinha; 11ª proposta recusada por falta
de cadeira mesmo com todas as 10 ainda só *pendentes* (não vivas ainda —
prova do bug de contagem corrigido); aprovar as 10 nasce 10 robôs de
verdade; mesa cheia recusa proposta nova; morte de uma raiz libera
cadeira; cadência de 30min bloqueia sem `bypass_root_cooldown`; recusar
descarta sem nascer; clonagem continua automática sem passar pela fila.
Fila de aprovação + timestamp de cadência sobrevivem a um restart do
processo (retomada de estado). E um teste real via Playwright clicando
Aprovar/Recusar no painel de verdade (não só chamando o método Python
direto) — o robô aprovado aparece em "Como cada robô opera" e no ranking,
o recusado some da fila sem deixar rastro.

**Revisão pós-implementação (`código-review` em `darwin_agent/`) achou e
corrigiu 3 bugs reais**, todos girando em torno de "aprovação é uma ação
manual, sem prazo — o mundo pode mudar enquanto a proposta espera":
1. `approve_pending` tirava a proposta de `_pending_approvals` ANTES de
   spawnar; se `_spawn` explodisse no meio (ex.: currículo/param
   inesperado), a proposta desaparecia pra sempre sem nascer robô e sem
   deixar rastro — nem a cadeira reservada voltava. Corrigido: só remove
   da fila depois que o robô nasce de verdade; se `_spawn` falhar, a
   entrada volta pra `_pending_approvals` (e a exceção sobe, o painel
   devolve erro em JSON em vez de 500 mudo).
2. `approve_pending` nunca reconferia o teto de nicho/população da Sala de
   Risco antes de spawnar — só checava uma vez, no momento de ENFILEIRAR.
   Como a aprovação pode demorar (é manual!), outros clones podiam
   preencher o nicho enquanto a proposta esperava, e aprovar furava o teto
   que a Sala de Risco existe pra proteger. Corrigido: reconfere capacidade
   dentro do próprio `approve_pending`; se mudou, recusa ali mesmo e a
   proposta continua na mesa (você pode tentar de novo depois).
3. `_drain_pending_clones` tinha o mesmo padrão "tira da fila antes de
   confirmar que nasceu" pra clones/otimizações pendentes — mesma correção
   (só remove de `_pending_clones` depois que `_fulfill_pending` termina
   sem exceção).
Também achou que `poll_strategy_feed` chamava `propose_and_spawn` sem
try/except — uma proposta problemática vinda do feed (`investigator_research.py`,
processo externo) travava a task de polling pra sempre, silenciosamente
(sem re-tentar, sem log, sem crashar visivelmente). Corrigido com
try/except ao redor da chamada, logando em `events.jsonl` (tipo `error`) e
seguindo pro próximo arquivo do feed. Todos os 4 fixes verificados com
objetos `Organism` reais forçando cada cenário de falha (`_spawn` mockado
pra explodir, `check_niche_capacity` mockado pra recusar no momento certo).

### 10. Log de Eventos — janela separada — Feito

Pedido explícito do usuário: um painel de risco (Sala de Risco) mostra o
financeiro; faltava um segundo painel mostrando **o que está
acontecendo** — "robô 1 foi eliminado, robô 2 foi promovido, Estrategista
recusou tal coisa por tal motivo" — numa **janela própria**, separada do
painel principal, pra deixar sempre aberta.

`Organism._log_event(tipo, mensagem, **extra)` grava uma linha em
`data/events.jsonl` (append-only, mesmo padrão de `history.jsonl`) —
chamado em todo ponto de decisão real da população:
- **Nascimento/clone/otimização** — em `_spawn` (ponto único, cobre robô
  raiz aprovado, clone exato, variante de otimização, e pendência da Sala
  de Risco atendida — todos passam por ali).
- **Morte + rebaixamento** — em `_handle_death`, com a causa exata.
- **Promoção** — em `_handle_clone`, quando bate +70%.
- **Toda recusa do Estrategista em `propose_and_spawn`** — ranking cheio,
  track record ruim, sem cadeira, cadência, teto de nicho/população,
  backtest reprovado — cada uma com o motivo exato que já ia na resposta
  da função, agora também registrado.
- **Decisões da Mesa** — proposta entrou na fila esperando você, você
  aprovou, você recusou.

**Painel separado (`/eventos`)** — não é um card dentro do painel
principal, é uma PÁGINA própria (`dashboard.py: EVENTS_HTML`,
`handle_events_page`), com link "📜 Log de eventos ↗" no cabeçalho do
painel principal (abre em nova aba). Lê `GET /api/events` (lê
`events.jsonl`, mais recente primeiro). Lista de eventos com badge
colorido por tipo (verde = nascimento/clone/promoção/aprovado, vermelho =
morte/rebaixamento/recusado, amarelo = recusas do Estrategista/aguardando
aprovação, azul = otimização), filtro por tipo, atualiza sozinho a cada 3s
— igual o painel principal, só que mais leve (uma lista, não um dashboard
inteiro) pra rodar numa janela à parte sem pesar.

Testado com eventos reais de ponta a ponta (`simulate.py` gerando
nascimento/aprovação, e um cenário forçado com clone + morte + recusa +
pendência) e confirmado visualmente por screenshot — a página renderiza
os 8 tipos de evento com badge/cor certos, e o filtro por tipo funciona.

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
- **Revisão explícita (avisada) da regra "sem limite"**: a intenção
  original continua — boas estratégias **têm que rentabilizar** e as ruins
  são **demitidas** (-60% do pico), a seleção nunca é um limite artificial
  sobre o MÉRITO. Mas exposição CORRELACIONADA (muitos robôs apostando
  exatamente a mesma coisa ao mesmo tempo) é um risco real de capital que a
  regra original não via — por isso agora existem dois tetos, os dois sob
  autoridade do Estrategista (`strategist.py: Strategist`), ver seção
  "Sala de Risco" abaixo:
  - **Teto por nicho (estratégia+ativo) = 10 robôs vivos.** Um nicho que já
    provou o valor dele 10x não ganha mais réplicas IDÊNTICAS — a pressão de
    clonagem além disso vira pedido de pequena otimização de parâmetros
    (novo nicho próprio), não duplicação da mesma aposta.
  - **Teto global = 180 robôs vivos.** Contém o capital real total sob
    gestão (cada robô vivo é uma conta operando de verdade).
  - Nenhum dos dois teto é eliminação por mérito — um robô barrado só por
    teto (nicho ou população cheios) entra numa fila e nasce assim que uma
    morte (real, por -60%) libera vaga. A seleção continua acontecendo
    através da eliminação normal; o teto só limita QUANTAS apostas iguais
    coexistem ao mesmo tempo.
  - Validado (forçando eventos reais): nicho satura em exatamente 10 e
    passa a gerar variantes com `strategy_id` novo; teto global enfileira e
    uma morte de verdade drena a fila corretamente.
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

- Não trocar as regras de vida (70% / 60% / teto de 10 por nicho / teto
  global de 180) sem confirmação.
- Não conectar a dinheiro real / corretora de produção nesta fase.
- Não simplificar a arquitetura de 2 camadas do Estrategista pra "só uma
  validação".
- Não fazer estratégia NOVA (robô raiz) nascer sem passar por "A Mesa"
  (aprovação humana) — `bypass_root_cooldown=True` só pula a CADÊNCIA de
  30min, nunca a fila de aprovação em si. Só `simulate.py` auto-aprova
  (ferramenta de teste do ciclo de vida, documentado ali o porquê).

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
| Multiplicação de robôs, população cresce por mérito | Não (era sempre 1 agente vivo) | **Feito, com revisão explícita** — cada clone vira uma nova `asyncio.Task`. Seleção por mérito continua sem teto (nicho provado nunca é "demitido" por estar cheio); o que ganhou teto foi CONCENTRAÇÃO — ver "Sala de Risco" abaixo |
| Sala de Risco: teto de concentração por nicho (10) e população (180), fila de espera, otimização automática quando saturado | Não existia | **Feito** — `strategist.py: Strategist` (`MAX_ROBOTS_PER_NICHE`, `MAX_POPULATION_ALIVE`, `check_niche_capacity`, `check_population_capacity`, `suggest_optimization`), `organism.py: Organism` (`_niche_key`, `_pending_clones`, `_drain_pending_clones`, `_risk_room_report`). Validado: nicho satura em exatamente 10 e passa a gerar variantes; teto global enfileira e uma morte real drena a fila |
| Backtest sobre dados históricos ANTES de arriscar capital real numa proposta nova | Não existia | **Feito** — `backtest.py: run_backtest()` (mesma lógica de análise ao vivo, `Strategy.analyze`, sobre candles históricos reais) + `Strategist.judge_backtest()`. Testado com random walk sintético (sem edge real): reprovou 2/4 estratégias-semente, prova que a camada discrimina de verdade |
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
| Visualização 2D estilo Tibia (bonequinhos, escritório) | Não (dashboard web simples) | **Abandonado por decisão do usuário** — ver seção "Visualizador" acima. Substituído por blocos coloridos + lista no painel de apurações |
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
13. ~~Sala de Risco (exposição correlacionada): teto de 10 robôs por nicho
    (estratégia+ativo) com otimização automática quando saturado, teto
    global de 180 robôs vivos com fila de espera drenada por morte real,
    backtest sobre candles históricos antes de qualquer capital real, e
    aposta por trade reduzida (2.0% -> 1.0%) pra track record mais longo
    antes do julgamento por mérito.~~ Feito — ver seção "Sala de Risco"
    acima. Validado com eventos reais (niche satura em exatamente 10, fila
    drena numa morte real, backtest reprova estratégia sem edge de
    verdade). Próximo passo natural: guiar a otimização automática por
    atribuição real (qual parâmetro historicamente correlaciona com melhor
    resultado), hoje é jitter aleatório.
14. ~~Visualizador 2D (o "jogo").~~ **Abandonado por decisão do usuário** —
    ver seção "Visualizador" acima. Não retomar sem pedido explícito.
15. ~~Painel: substituir os cards grandes de "Como cada robô opera" (com
    teto de 40 por peso visual) por algo mais leve.~~ Feito — toggle
    Blocos/Lista, ver "Como cada robô opera" na seção 7. Blocos sem teto
    de exibição (testado com 70 robôs simultâneos).
16. 4 bugs corrigidos numa revisão de código (`code-review` skill, xhigh
    effort): `ml/selector.py` — `_open_trades` era uma entrada única por
    símbolo, virou fila FIFO (um robô pode ter várias posições abertas no
    mesmo símbolo, `max_open_positions=3`); `core/agent_v2.py` —
    cancelamento (shutdown) não marcava `_death_reported`/`phase`, robô
    ficava "pendurado" sem fechar o ciclo de vida (sem disparar `on_death`,
    corretamente — cancelamento não é eliminação por mérito); `organism.py`
    — `Professor.build_curriculum()` nunca recebia candles reais, o ajuste
    por volatilidade nunca rodava; `utils/config.py` — `allowed_timeframes`
    não incluía "1w", rejeitando um timeframe que o resto do sistema já
    suporta.
17. ~~Retomada de estado (resume): rodar de graça no próprio computador
    sem perder progresso a cada restart.~~ Feito — ver "Macro-organismo"
    acima (`Organism.save_full_state`/`resume_from_state`,
    `DarwinAgentV2.export_state`/`import_state`, `data/organism_state.json`).
    Decisão do usuário: rodar local (grátis, sem VM), mas com retomada
    real em vez de aceitar reiniciar do zero. Dois bugs reais corrigidos
    no processo (saldo de paper trading resetando, epsilon do brain
    distorcido por uma fórmula pensada pra herança de clone). Testado de
    ponta a ponta simulando um restart de processo completo.
18. Evoluir o julgamento do Estrategista (hoje é regra de threshold +
    pesquisa determinística) pra um agente/LLM com mais nuance. Testar
    contra a Bybit testnet de verdade
    (`python -m darwin_agent --universe 1000 --roots 5`), incluindo
    `investigator_research.py --loop` e `strategist_research.py --loop`
    rodando em paralelo com uma `ANTHROPIC_API_KEY` de verdade.
19. ~~Expandir pra ativos fora de cripto (índices globais, commodities,
    futuros, ações de bolsa).~~ Feito — ver "Macro-organismo" acima
    (`markets/yahoo.py`, `markets/multi_asset_universe.py`, `--assets`).
20. ~~A Mesa: aprovação humana pra estratégia nova (não clone), 10
    cadeiras, cadência de 30min, painel com card de aprovação.~~ Feito —
    ver seção "A Mesa" acima. Testado de ponta a ponta inclusive clicando
    Aprovar/Recusar no painel de verdade via Playwright.
21. ~~Log de eventos numa janela separada (nascimento/morte/clonagem/
    promoção/recusas do Estrategista com motivo).~~ Feito — ver "Log de
    Eventos" acima (`data/events.jsonl`, painel `/eventos`).
