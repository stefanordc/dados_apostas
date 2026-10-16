# Atualização — Gols, Radar e ML (14/10/2026)

A página **Backtesting · Inteligência de Confrontos** ganhou as abas:

- **Geral:** resumo de resultados recentes e principais médias de cada clube.
- **Gols:** usa `public.minutos_gols`, por `id_jogo`/`jogo_id`, e os placares após cada gol para calcular abertura de marcador, ampliação da vantagem, empate sofrido, vitória/derrota após abrir, gols por tempo e 8 faixas de minuto. Percentuais após abertura têm como denominador apenas os jogos em que o clube abriu o placar; os percentuais de gols por faixa/tempo consideram os gols do próprio clube. Eventos incompletos ou com placar final inconsistente são descartados; o relatório informa a cobertura.
- **Ataque:** xG, chutes, grandes chances, gols, posse e criação.
- **Defesa:** xG sofrido, gols sofridos, chutes sofridos, desarmes, interceptações, recuperações etc.
- **Projeção:** radar Ataque/Defesa/Criatividade/Força; modelos de gols, previsão de 1X2, Over 1,5/2,5, Ambas Marcam, goleada casa/fora, placares provável/menos provável (0×0 até 4×4), zebra vencer 1×0 (0×1 quando visitante) e 20.000 simulações Monte Carlo. Mantém o seletor de mercados e o cálculo de EV.

**Modelagem:** regressão de Poisson supervisionada, treinada com métricas disponíveis ANTES dos jogos e validação temporal nos 20% mais recentes. A regressão só substitui o baseline quando seu log-loss de validação melhora o da referência. Sem amostra suficiente, utiliza Poisson/xG/forma recente como fallback, indicado na tela. Nenhum EV é valor comprovado sem calibração prospectiva.

**Tabela `minutos_gols`:** nenhuma migração é aplicada. O backend detecta nomes comuns das colunas de partida, minuto e placar (incluindo placar único como `1-0` ou colunas casa/fora). Para validar sua estrutura e a cobertura:

```powershell
cd "C:\Users\stefa\Desktop\Portfólio 2026\backtest_apostas\backend"
.\.venv\Scripts\python.exe -m scripts.validar_sofascore
```

**Testes locais:** `pytest -q tests_*.py`. O conjunto inclui eventos de gols nos acréscimos, viradas, empate após abertura, simulações reprodutíveis e regressões anteriores. Os scripts acessam as bases somente para leitura.

---

# Atualização SofaScore — Inteligência de Confrontos (13/10/2026)

A página **Backtesting** foi reformulada para a análise de confrontos entre clubes. Seus dados agora vêm **exclusivamente** de `public.jogos` (placares, data, temporada, nomes e IDs) e de `public.jogo_completo` (SofaScore). As páginas Scanner e Estatísticas permanecem independentes.

- Chave do relacionamento: `jogos.id_jogo = jogo_completo.id_jogo` **E** `jogo_completo.id_clube = jogos.id_mandante` ou `id_visitante`, uma linha de estatística por clube, sem duplicar partidas.
- Filtros: País, Campeonato, Mandante, Visitante e **últimos 5, 10, 20, 30, 50 ou 100 jogos** por clube. O modelo considera partidas encerradas anteriores a hoje, limitando cada lado ao intervalo selecionado e pesando mais os jogos recentes (meia-vida de 240 dias).
- Métricas usadas: xG criado e xG sofrido, gols, finalizações totais/no alvo/na área, grandes chances, posse de bola (influência pequena), escanteios, passes e estatísticas defensivas. xG determina a maior parte do ritmo estimado de gols. Uma métrica de xG precisa de **5 jogos com dados** para entrar na estimativa. Ausência de xG aciona fallback transparente por gols reais.
- `P(gols casa=i, gols visitante=j)` é calculado com Poisson independente a partir dos gols esperados ajustados. Daí saem as probabilidades de 1X2, Over/Under, Ambas Marcam, gols altos, placares exatos, Lay Casa/Fora, Lay Goleada e **Lay do placar exato 1×0 da zebra** (ou 0×1, conforme a equipe menos favorita). H2H dos últimos 2 anos pode ajustar somente 5% da expectativa quando houver 3+ confrontos.
- **EV estimado**: Back `P × odd − 1`, Lay com responsabilidade fixa `P_green/(odd − 1) − P_red`. Todas as odds são exibidas com duas casas decimais. Estatísticas do primeiro tempo não são presumidas a partir do jogo completo; estes mercados aparecem indisponíveis na página.
- **Limitação:** modelo experimental e **não calibrado fora da amostra**. Os percentuais e um EV positivo não comprovam que a aposta tem valor verdadeiro. Antes de usar com stakes reais, fazer backtest temporal e calibração (Brier, Log Loss, confiabilidade) com histórico real não utilizado no ajuste.
- **Banco:** não precisa criar ou alterar colunas. Ambas as tabelas devem estar acessíveis por `HISTORY_DATABASE_URL` no mesmo banco e esquema definido por `HISTORY_SCHEMA` (padrão `public`). Para validar as tabelas na sua instalação: `cd backend; .\.venv\Scripts\python.exe -m scripts.validar_sofascore`.

# ELO Scout — Estatísticas, Scanner e Backtesting (12/10/2026)

Nova navegação: **Estatísticas** (`/estatisticas`), **Scanner** (`/scanner`) e **Backtesting** (`/backtesting`).

- **Estatísticas**: gráficos de ligas/clubes, cartões, resultado histórico e win rate. Usa exclusivamente `historico_jogos`; todas as análises nessa tela enviam `statistics_only=true` e `use_odds=false`.
- **Scanner**: grupos Match Odds HT/FT, Over e Under HT/FT, Ambas Marcam, Dupla Chance e Placar Exato. Consulta colunas disponíveis em `public.odds`, tanto no banco principal quanto no histórico. Retorna odds de equilíbrio, amostra com cotações válidas, ROI e lucro por R$ 100, maior good run e bad run, e faixas candidatas com pelo menos 40 apostas e ROI positivo em 70% inicial / 30% final. É uma varredura exploratória, **não** recomendação validada prospectivamente. Para evitar picos de memória a leitura é limitada a 80 mil partidas por análise; a tela sinaliza se houve truncamento. Ao escolher um grupo HT, minutos de gols ausentes impedem inferir placar no intervalo para jogos que tiveram gol no tempo regulamentar.
- **Backtesting**: filtros País, Campeonato, Mandante, Visitante; comparação de vitórias, empates, gols, médias, cleansheets, gols sofridos etc. para H2H 5/10/todos, últimos 5/10/20, temporada atual e 3 anos. Probabilidades dos oito mercados usando últimos 60 jogos por mando com decaimento de meia-vida 365 dias, bônus aos 5 recentes, H2H suavizado e probabilidades 1X2 somando 100%. EV=(probabilidade*odd -1)*100. A estimativa **não é modelo calibrado** nem garantia de rentabilidade.
- **Fontes**: `public.historico_jogos` no banco histórico de leitura; `public.odds` é buscada nos dois bancos configurados e lida somente de onde existir. Não é necessário criar, renomear ou migrar tabelas para instalar.
- **Como atualizar**: salve o ZIP como `download.zip` na pasta do projeto e execute `atualizar_projeto.ps1` e `iniciar.ps1`. O instalador preserva `backend/.env`.

## Testes desta atualização

`cd backend` e rode `pytest -q tests_*.py`. Para validar o frontend no Windows, execute `npm install` e `npm run build` em `frontend`.

---

## Novo filtro Continente — 12/10/2026

- Filtro opcional **Continente** antes de **País** em todas as abas de Backtesting, incluindo Estatísticas por Campeonato e Estatísticas por Clube. As opções seguintes são restritas ao continente escolhido; apenas **Aplicar filtros** executa a análise.
- A coluna `public.historico_jogos.continente` deve ser criada no **banco histórico**, não no banco principal ELO. Execute o arquivo `sql/20261012_historico_jogos_continente.sql` pelo DBeaver com um usuário que tenha permissão para `ALTER TABLE`, `UPDATE` e criar trigger.
- A migração inclui preenchimento dos países conhecidos e um gatilho para novas inserções/alterações de país. Países desconhecidos ficam com `NULL` para revisão; no filtro aparecem como **Não informado**. O catálogo do site prefere o valor gravado na coluna e usa a padronização dos países como fallback enquanto a migração não é aplicada.
- **Atenção:** o backend se conecta a `historico_jogos` em modo somente leitura. O instalador PowerShell **não aplica esta migração automaticamente**, para preservar o banco correto e evitar alterações não autorizadas. Execute o SQL uma vez e depois atualize o site.
- Para conferir, rode `SELECT continente, COUNT(*) FROM public.historico_jogos GROUP BY 1 ORDER BY 1;` no DBeaver.

## Correção de desempenho — Estatísticas por Clube (11/10/2026)

- A análise **Sem odds**, inclusive Todos os países / Todos os campeonatos / Todos os clubes, usa agora uma **única consulta SQL agregada**, que calcula os 12 mercados e o critério de elegibilidade (mais de 500 partidas em todo o histórico OU pelo menos 100 nos últimos três anos) diretamente no PostgreSQL.
- Os filtros de país, competição e clube são opcionais. A elegibilidade é calculada **antes** do recorte de período/competição, sem excluir clubes experientes por estarem numa amostra parcial.
- A classificação é armazenada em cache por até 3 minutos; a busca de sugestões e o histórico ao clicar no clube evitam consultar novamente todos os candidatos.
- As métricas de lucro/ROI **não são inventadas** quando o modo Sem odds está ligado; Com odds continua usando a conciliação existente.
- O tempo de execução de `POST /api/backtesting/club-statistics` aparece nos logs do servidor.
- Não exige mudanças de tabelas ou execução de scripts de migração.

# ELO Scout — Backtesting (Outubro/2026)

Aplicação **web** com frontend **React/Vite/TypeScript** e backend **FastAPI/PostgreSQL**. Não utiliza Streamlit.

## Nova página Backtesting

O antigo item **Scanner** foi substituído por **Backtesting**. A rota anterior `/scanner` redireciona para `/backtesting`, assim como `/backtest`. A página Backtest antiga não é mais exibida. Os serviços e registros anteriores de métodos **não são apagados do banco**.

Abas: Resultado por Time, MO Casa, MO Fora, Lay Casa, Lay Fora, Lay Goleada Casa, Lay Goleada Fora e Correct Score.

- País e competição obrigatórios; **clube obrigatório em Resultado por Time**. Nos demais recortes o clube pode ser omitido. Para os mercados direcionais, o clube selecionado é considerado mandante.
- Os filtros dependentes são alimentados pelo histórico da competição: clube, adversário e temporada inicial (padrão todas).
- **Resultado dos últimos anos**: padrão 3 anos-calendário; a tabela anual é calculada independentemente da temporada inicial usada nos cards.
- Cards exibem acertos, amostra, taxa observada e preço de equilíbrio. Para Back, é a **odd mínima** e, para Lay, a **odd máxima**.
- Uma goleada é uma **vitória com 4+ gols feitos**, independentemente da diferença no placar. Ex.: 8 × 7 é goleada do mandante.
- Com adversário informado, os resultados do confronto direto aparecem em um bloco adicional sem substituir o resumo original.
- Correct Score usa placares frequentes, quantidade, proporção e barra percentual.
- O L/P anual, mensal e em stakes é calculado apenas para mercados com a cotação efetivamente cadastrada.

## Cotações disponíveis e faltantes

A tabela `odds_jogos` fornece **Back Casa, Empate, Back Fora e Over 2,5**. Como não há odds Lay, não calculamos lucro Lay a partir de odds Back. Os filtros de Over 1,5 e Ambos Marcam só selecionarão jogos quando as respectivas cotações forem incluídas na base; até lá, frequência histórica sem filtro de preço é apresentada normalmente.

**Stake padrão: R$ 100,00 por entrada.** Uma stake positiva equivale a R$ 100,00 líquidos de resultado. Sem simulações de preços, comissões ou responsabilidades Lay.

O banco `historico_jogos` permanece exclusivamente **somente leitura**. A conciliação usa a nova tabela `backtest_apostas.clubes_conciliacao` no banco principal; as tabelas originais não são modificadas.

## Atualização no Windows

Salve o ZIP com o nome **download.zip** na pasta `C:\Users\stefa\Desktop\Portfólio 2026\backtest_apostas` e execute:

```powershell
cd "C:\Users\stefa\Desktop\Portfólio 2026\backtest_apostas"
powershell -ExecutionPolicy Bypass -File ".\atualizar_projeto.ps1"
powershell -ExecutionPolicy Bypass -File ".\iniciar.ps1"
```

O atualizador preserva o `.env` e não volta a solicitar senhas.

## Testes

```powershell
cd backend
.\.venv\Scripts\python.exe tests_backtesting.py
```

O teste usa dados simulados **somente para validar cálculos**, sem criar apostas nem modificar os bancos. Execute o build real com `npm run build` dentro de `frontend`.

### Backtesting — resultado financeiro por mercado (atualização)
- Colunas anuais: MO Casa, MO Fora, Lay Casa, Lay Fora, Over 1,5, Over 2,5 e Ambos Marcam.
- A linha TOTAL soma as stakes de cada mercado apenas para os anos-calendário mostrados; o último campo é a soma monetária dos mercados cotados.
- Cotações Lay não estão no esquema atual; sem uma odd Lay real o retorno permanece `—`, nunca zero artificial nem cotação Back interpretada como Lay.

### Conciliação automática de `public.historico_odds` (novo)

- `Backtesting` consulta a nova tabela na base principal; caso ela exista somente na base histórica, faz a leitura lá (sem gravar na base histórica).
- Concilia **país, campeonato, temporada, data, mandante e visitante** com `historico_jogos`. Normaliza acentos e temporadas (`2025/26` = `2025/2026`); utiliza aliases oficiais de clubes quando disponíveis.
- O placar vem **apenas** de `historico_jogos`. As odds vêm de `historico_odds`, com fallback para `odds_jogos` quando necessário. Nenhum placar é gravado nas tabelas.
- Mostra contagem de jogos conciliados, não conciliados e ambíguos, além de tabela para conferir Green/Red e L/P por mercado. Odds diferentes duplicadas para o mesmo jogo são rejeitadas sem escolher uma aleatoriamente.
- Os cards e L/P em Backtesting passam a usar as odds de MO, Over 0,5, Over 1,5, Over 2,5, Under 3,5 e Ambos Marcam Sim. Na conferência detalhada são suportadas todas as colunas de odds recebidas, incluindo Under e BTTS Não.
- O cálculo continua com stake fictícia de R$ 100. Não converte odds Back em Lay. A conciliação é atualizada em cache de 5 minutos ou na reinicialização do backend.

## Correção: cards em todas as abas

- As oito abas de Backtesting exibem os mesmos 12 cards, em ordem fixa.
- A aba selecionada apenas destaca seu mercado.
- Correct Score mostra também os cards, além da distribuição de placares.
- O confronto direto mantém os 12 cards em todas as abas.

## Backtesting: correção dos totais e conferência por aba

- Corrigida a soma monetária no TOTAL: o L/P anual já está em reais e **não** deve ser multiplicado por 100 novamente. As colunas por mercado permanecem em stakes de R$ 100,00.
- Adicionadas as colunas **Lay Goleada Casa** e **Lay Goleada Fora** na tabela anual e mensal. Onde não há cotação Lay real, apresentam **Win Rate** (percentual de entradas em que a goleada não ocorreu), e não um L/P inventado. O total de Win Rate é ponderado pela quantidade de jogos, não é soma ou média simples de porcentagens. Win Rate não entra em `L/P somado`.
- No painel **Conferência de Greens e Reds**, cada aba de mercado restringe automaticamente as partidas ao seu mercado. Os filtros de país, campeonato, temporada inicial, clube, adversário e odds são respeitados. **Resultado por Time** preserva a escolha de mercado para conferência, sempre filtrando jogos elegíveis ao clube.
- Em mercados Lay sem preço cadastrado, a conferência informa **Acerto/Erro (sem odd)**, com odd e L/P indisponíveis. Isto representa resultado histórico e **não** apostas reais executadas. Com preço Lay válido em coluna opcional, o L/P usa responsabilidade fixa de R$ 100,00 por aposta sem comissão.
- Colunas opcionais reconhecidas em `historico_odds`, se adicionadas futuramente: `lay_casa`, `lay_fora`, `lay_goleada_casa`, `lay_goleada_fora`. Elas **não** são preenchidas artificialmente a partir de odds Back.

### Validação (sem dados reais)

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests_backtesting.py tests_historico_odds.py
```


## Filtros de divisão e formato no Backtesting

- As colunas opcionais `divisao` e `formato` são lidas de `historico_odds` quando presentes, ou de `historico_jogos` se existirem lá.
- Disponíveis como filtros em todas as 8 abas de Backtesting, inclusive Correct Score e confronto direto.
- Valores de `formato` dependem da divisão selecionada, com `Todas` como padrão.
- A amostra dos cards, placares, L/P anual e mensal, e conferência por jogo respeita os dois filtros. A janela anual continua independente da temporada inicial, mas respeita divisão e formato.
- Na conferência individual são exibidas as colunas Divisão e Formato. Jogos sem metadados ficam fora somente quando o filtro da respectiva coluna está ativo.
- Os dois campos são opcionais no esquema: tabelas antigas não causam erro. Resultados atualizam quando o cache de 5 minutos expirar ou o backend reiniciar.

## Conciliação manual e persistente dos nomes de clubes (nova)

Na página **Backtesting**, ao selecionar país e competição, o sistema compara
`historico_jogos` com `historico_odds`. Se encontrar grafias divergentes para o
mesmo confronto, exibe a fila **Conciliação de nomes de clubes**.

- Para cada divergência, escolha o nome presente em `historico_jogos`, o de
  `historico_odds`, ou escreva um nome personalizado que será exibido nas oito abas
  de Backtesting (inclusive na seleção dos clubes e na conferência por jogo).
- O registro fica salvo na tabela `backtest_apostas.clubes_conciliacao`, com
  identificador do campeonato, nomes originais/normalizados, nome padrão e
  timestamps. Uma decisão aprovada é reaplicada automaticamente nos próximos
  carregamentos sem repetir a pergunta.
- Se os dois clubes mudaram de nome e há vários confrontos na data, o painel
  **Confrontos que precisam de identificação manual** permite escolher qual
  cotação corresponde ao jogo. É exigida confirmação antes de salvar.
  Os nomes restantes continuam pendentes até receberem aprovação.
- Caso nenhum confronto candidato exista na data/temporada, o jogo permanece sem
  associação; nunca se gera preço ou L/P artificial.
- Todas as gravações são feitas no banco **principal**, via API FastAPI, e
  as tabelas `public.historico_jogos` e `public.historico_odds` permanecem intactas.
- A aplicação invalida imediatamente o cache após aprovar qualquer nome; novas
  cargas de dados entram no cache de até 5 minutos.

O script `atualizar_projeto.ps1` executa `backend/scripts/init_db.py`, criando a
nova tabela automaticamente com `CREATE TABLE IF NOT EXISTS`. Não é necessário
executar SQL manualmente. O script também valida o banco histórico.

Após aplicar o ZIP e inicializar o aplicativo, selecione um campeonato com odds
históricas para visualizar as conciliações disponíveis.

**Validação automática realizada no pacote:** testes de backend para nomes
idênticos, nomes divergentes, grafias distintas, duplicidade de preços,
identificação manual de partidas ambíguas, filtros e resultados financeiros.

## Sugestão de faixas de odds antes da conferência de jogos

- Nova seção **Faixas de odds para testar estratégias** fica imediatamente acima da tabela **Conferência de Greens e Reds**. Nas abas MO/Lay apresenta somente o mercado da aba; em **Resultado por Time** pode alternar entre todos os 12 mercados.
- Usa o mesmo conjunto de país, competição, divisão, formato, clube, adversário, temporada inicial e filtros de odds aplicados à conferência. A tabela anual continua independente da temporada inicial.
- Intervalos são formados a partir de grupos de preços predefinidos e reunidos em até 5 grupos consecutivos. Não são ajustados arbitrariamente após observar cada resultado individual.
- Nos mercados **com odds reais**, exibe apenas faixas com pelo menos **20 apostas liquidadas** (14 no período inicial e 6 no posterior) e **ROI positivo nos dois períodos cronológicos**, apresentando Greens/Reds, Win Rate, ROI inicial, ROI posterior, ROI total e lucro histórico para R$ 100 por entrada. Se nenhuma faixa cumprir as regras, a interface informa que não há recomendação fundamentada naquele recorte.
- Em **Lay sem odds reais**, utiliza a odd **Back somente para selecionar e agrupar jogos**; mostra Win Rate, comparação posterior e odd Lay de equilíbrio histórica (quando calculável). **Não fabrica ROI nem lucro**. O equilíbrio histórico não é sugestão de cotação negociável e não inclui margem nem comissão.
- O botão **Aplicar faixa** atualiza o intervalo do mercado nos filtros do site e refaz o Backtesting, incluindo os mesmos critérios na conferência de jogos logo abaixo.
- Foram incluídos os campos de odds para **Over 0,5** e **Under 3,5** entre os filtros que também podem ser preenchidos pelo botão.
- A análise é exploratória: escolher o melhor resultado entre muitas faixas tende a inflar o desempenho histórico. A comparação cronológica não equivale a uma validação prospectiva; **não há garantia de lucro**.

Para executar os testes, com as configurações de ambiente disponíveis:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests_backtesting.py tests_historico_odds.py tests_suggestions.py
```

## Filtro de países apenas com partidas (nova atualização)

- Nas páginas **Backtesting**, **Clubes**, **Rankings** e **ELO**, o filtro País
  oferece apenas países com pelo menos uma partida em `public.historico_jogos`
  (ou a tabela configurada em `HISTORY_SCHEMA`/`HISTORY_TABLE`).
- **Histórico de Jogos** continua obtendo os nomes dos países diretamente das
  partidas que satisfazem os filtros aplicados.
- No módulo **Cadastros**, o filtro da grade de clubes também usa apenas países
  com jogos. Os formulários de criação, edição e importação mantêm o catálogo
  completo para não impedir cadastrar o primeiro jogo de um novo país.
- O backend ignora diferenças de maiúsculas/minúsculas, espaços e acentos na
  comparação dos nomes entre os dois bancos. O resultado é guardado em cache
  por até 60 segundos; recarregue a página depois desse intervalo para ver
  países adicionados ou retirados recentemente.
- Não são feitas alterações nem exclusões de países ou jogos no banco.

Validação local: `python -m pytest -q tests_country_filters.py tests_backtesting.py tests_historico_odds.py tests_suggestions.py`.


## Backtesting — nova aba Liga (2026-10-11)

- Selecione **Liga** no menu de abas do Backtesting.
- Informe **País**, **Competição** e **Temporada** (obrigatórios). A lista de países inclui somente países com jogos cadastrados; temporadas vêm do histórico do campeonato.
- A temporada da aba Liga representa a temporada **exata**; as demais abas mantêm o comportamento original de "Temporada inicial".
- A análise agrega todos os jogos finalizados da competição nessa temporada, independentemente de clube, adversário, divisão e formato que estejam selecionados em outras abas.
- Exibe resumo (jogos, gols, média, vitórias casa/empate/fora, Over 2,5, Ambos Marcam), os 12 cards de mercados, placares exatos, rentabilidade anual *dentro da temporada*, sugestões de faixas de odds e conferência de Green/Red.
- Odds ausentes continuam com lucro/ROI indisponível; não são gerados preços sintéticos. Na tabela de conciliação da aba Liga, os totais se referem exclusivamente à temporada selecionada.
- Não são necessárias migrações adicionais no banco para esta atualização.

## Backtesting: seletor ON/OFF — Com odds / Sem odds (outubro/2026)

A alternância foi disponibilizada em **todas as nove abas do Backtesting**, inclusive na aba **Liga** e nos confrontos diretos.

- **ON · Com odds**: analisa apenas jogos conciliados com `historico_odds`, considerando exclusivamente cotações reais dessa tabela. `historico_jogos` fornece o placar final para determinar Green/Red. Em mercados com odds próprias válidas, apresenta lucro, ROI e unidades conforme as regras Back/Lay do projeto; mercados sem odds próprias não recebem lucro simulado. Faixas de odds e conciliação permanecem disponíveis.
- **OFF · Sem odds**: utiliza **todos os resultados válidos de `historico_jogos`**, mesmo sem correspondência em `historico_odds`. Mantém os 12 cards, tabela anual e mensal, distribuição de placares, conferência de partidas e confronto direto. Substitui unidades e lucro por **Win Rate (acertos / jogos elegíveis)**. Nenhuma odd, stake, unidade monetária ou ROI é calculada.
- A seção de estratégias sem odds exibe **taxas de acerto por mercado**, com divisão cronológica dos dados entre 70% inicial e 30% posterior; não apresenta faixas de preços sem fonte numérica. Na tabela de partidas, o Win Rate acumulado usa **todas as partidas anteriores dentro dos filtros**, mesmo exibindo apenas as 40 mais recentes.
- Uma partida pode aparecer em vários mercados; por isso, o WR combinado por ano é a taxa calculada sobre ocorrências de mercados (não representa o retorno de uma única aposta).
- Os nomes reconciliados são preservados apenas para apresentação. A alternância não edita `historico_jogos` nem `historico_odds` e não exige novas tabelas.

## Backtesting — otimização dos filtros dependentes (2026-10-11)

- Países com jogos e catálogo de competições são carregados **em paralelo** ao abrir a página. Ao escolher outro país, a lista de campeonatos é filtrada localmente: não há nova chamada à API somente por essa mudança.
- Países e campeonatos distinguem **carregando** de **nenhuma opção cadastrada**; se não existir campeonato no catálogo para o país, a interface informa isso explicitamente.
- O endpoint `/api/backtesting/options?competition_id=...&use_odds=true|false` agora usa uma agregação SQL restrita ao país e campeonato sobre `historico_jogos`, sem executar a conciliação inteira nem transferir placares para preencher temporadas e clubes.
- No modo **Com odds**, somente os **pares distintos** divisão/formato são consultados na tabela `historico_odds`, sem buscar cotações. No modo **Sem odds**, a consulta de filtros nem acessa `historico_odds`.
- A conciliação detalhada passa a ocorrer depois que os filtros estiverem prontos, sem bloquear a seleção da temporada.
- A alternância ON/OFF preserva os filtros selecionados que permanecem válidos; ao mudar de competição, os filtros dependentes são zerados para evitar seleções incompatíveis. Requisições antigas não substituem opções da competição atual.
- Resultados dos seletores ficam em cache no backend por até 120 segundos; o cache é invalidado ao salvar novas conciliações. Se o catálogo ainda não tiver um campeonato associado ao país, é necessário cadastrá-lo; o filtro não cria novos registros automaticamente.
- Nenhum dado é gravado ou removido em `historico_jogos` e `historico_odds`.

**Validação local:** 54 testes de backend, incluindo quatro testes novos de cascata de filtros e leitura leve. Sintaxe TSX verificada com TypeScript `transpileModule`; o build Vite completo não pôde ser concluído porque a instalação das dependências do frontend expirou neste ambiente. O atualizador executa `npm run build` no PC.

## Otimização da aba Liga — comparativo geral (2026-10-11)

Corrige a demora ao clicar **Aplicar filtros** com **Todos os países / Todos os campeonatos**.

- **Sem odds**: uma consulta SQL agrupada em `historico_jogos` por liga, temporada, mês e placar substitui o carregamento individual de todas as partidas de cada campeonato. Contagens, Green/Red, Win Rate, resumos, placares e gráfico comparativo usam a quantidade real de partidas em cada grupo (não o número de grupos).
- **Com odds**: leitura em lote das duas fontes e conciliação de nomes já aprovados, sem consultar `historico_odds` separadamente a cada campeonato. Não utiliza cotações antigas (`odds_jogos`) nem preenche odds ausentes.
- **Filtros de Liga**: uma consulta DISTINCT de temporadas/divisão/formato em `historico_jogos`, e uma consulta DISTINCT adicional a `historico_odds` somente no modo Com odds. Cache curto de 180 segundos.
- A auditoria sem odds do **comparativo geral** consulta somente partidas recentes para mostrar nomes e resultados, mantendo o Win Rate acumulado calculado sobre o universo histórico completo.
- Exibir todas as ligas no painel de barras é possível no botão **Exibir todas as ligas por mercado**. A visualização inicial mostra até 24 por mercado para não criar milhares de barras no navegador.
- O botão **Aplicar filtros** tem limite de espera de 45 segundos no navegador e informa quando o tempo é excedido. O cancelamento da espera na interface não garante o cancelamento imediato de uma consulta já em andamento no PostgreSQL.
- Não há migração de banco. As consultas continuam somente leitura e não há dados fictícios de odds/ROI.
- A otimização ainda precisa ser medida no banco real, que não está acessível neste ambiente. Testes unitários executados sem banco real: **62 aprovados**. O build completo do frontend não foi executado neste ambiente; a sintaxe TSX foi verificada com TypeScript.

## Atualização — Aba Liga: intervalo por ano-calendário (11/10/2026)

- A tabela anual/mensal de Win Rate e resultados financeiros foi removida **somente da aba Liga**. As demais abas mantêm as suas tabelas.
- A Liga passa a ter os filtros opcionais **Ano — de** e **Ano — até**, ambos baseados no **ano da data do jogo**, não no rótulo da temporada. Ambos os limites são inclusivos. Com os dois campos vazios, analisa todo o histórico.
- Exemplo: 2023 a 2025 considera partidas de 01/01/2023 a 31/12/2025, sejam elas de temporada 2023, 2023/24, 2024/25 etc. Assim as ligas são comparadas em datas equivalentes, independentemente de calendários europeu ou sul-americano.
- O recorte vale para gráficos de comparação, cards, distribuição de placares, análise de odds e conferência de jogos. Limite inferior maior que o superior gera erro explicativo.
- O caminho geral Sem odds usa agregação SQL em `historico_jogos`, restringindo o intervalo na cláusula WHERE; no caminho Com odds em lote, tanto jogos quanto odds são filtrados pelo mesmo intervalo antes da conciliação.
- Nos mercados com cotações, os filtros de odds continuam disponíveis na aba Liga. Nenhum dado do banco é modificado.

Validação local: `APP_DATABASE_URL=sqlite:// HISTORY_DATABASE_URL=sqlite:// pytest -q backend/tests_*.py` → 68 testes aprovados. Foi verificada a sintaxe TypeScript/JSX; o build completo do frontend depende das dependências de npm do computador de destino.

### Correção de campeonatos do Backtesting — aba Liga (11/10/2026)

- Novo endpoint `GET /api/backtesting/league-catalog` obtém países e campeonatos diretamente de `historico_jogos` (distinct por país/campeonato), com cache curto de 3 minutos.
- Os seletores da aba Liga não dependem mais dos cadastros auxiliares da área ELO. Outras abas permanecem com seus cadastros habituais.
- A análise de todas as ligas, de uma liga ou de um país utiliza a mesma lista baseada em `historico_jogos`, mesmo sem cadastro em `campeonatos`.
- Em `Com odds`, nomes de clubes conciliados continuam associados apenas a IDs reais do catálogo auxiliar, evitando misturar associações quando há campeonatos sem cadastro; confrontos não conciliados não geram lucros fictícios.
- Modo `Sem odds` permanece uma agregação SQL única dos jogos concluídos e modo `Com odds` mantém conciliação por competição em lote.
- Os campeonatos surgem dinamicamente da fonte; os 18 nomes do banco não estão escritos em nenhuma lista fixa no código.

**Validação local:** 72 testes unitários de backend passaram, incluindo um cenário de catálogo auxiliar com apenas 9 das 18 competições; sintaxe TypeScript/TSX analisada. Build completo do frontend não disponível no ambiente de empacotamento.

### Aba Liga — gráficos e detalhamento de 10 anos (11/10/2026)

- A aba **Liga** exibe os 12 gráficos comparativos e, **depois de todos eles**, a tabela de **Placar exato**.
- As tabelas "Win Rate por mercado — comparação histórica" e "Conferência de Acertos e Erros" continuam disponíveis nas outras abas, mas não são mais mostradas na aba Liga.
- Clique no nome ou na barra de qualquer campeonato em qualquer mercado: abre um gráfico secundário com os **10 últimos anos-calendário**, incluindo o ano atual (parcial).
- O detalhe é consultado **apenas após o clique**, sempre para o campeonato e mercado selecionados, respeitando divisão, formato, estado Com odds / Sem odds e faixas de odds aplicadas.
- O intervalo "Ano — de / Ano — até" continua definindo a comparação principal; o detalhamento é sempre dos últimos 10 anos, independentemente desse intervalo.
- O modo Sem odds lê `historico_jogos` e não calcula lucro; o modo Com odds usa somente cotações conciliadas de `historico_odds`. Mercados Lay sem cotação Lay não recebem retorno financeiro fictício.
- Nova rota: `POST /api/backtesting/league-market-history`.

## 11/10/2026 — Estatísticas por Clube

- Backtesting abre por padrão em **Estatísticas por Campeonato** (antiga aba Liga).
- A segunda aba, **Estatísticas por Clube**, oferece 12 subabas independentes: MO Casa/Fora, Empate, Lay Casa/Fora, Lay Goleada Casa/Fora, Over 0,5/1,5/2,5, Under 3,5 e Ambas Marcam.
- País, campeonato e clube são opcionais. Os seletores usam o catálogo de competições oriundo de `historico_jogos`; clubes podem ser procurados pelo nome.
- Para aparecer nos gráficos, o clube precisa ter **mais de 500 jogos concluídos no histórico** ou **pelo menos 100 jogos concluídos nos 3 anos anteriores à data atual**. A elegibilidade é verificada na base completa, antes dos filtros do usuário, por identificação de clube e país/região do registro. Não conta partidas sem placar.
- Os gráficos são classificados por Win Rate, com quantidade de jogos. O clique abre o histórico daquele mercado nos **últimos 10 anos-calendário**, sob demanda; anos sem partidas aparecem sem resultados.
- No modo ON, a seleção é limitada a jogos conciliados com `historico_odds`, utilizando o mecanismo de conciliação existente. L/P e ROI só podem existir quando a odd real do próprio mercado estiver presente; Lay sem cotação mantém apenas Win Rate. OFF lê exclusivamente `historico_jogos`.
- A coluna `pais` do histórico geralmente identifica o **país da competição** e não necessariamente a nacionalidade do clube (ex.: Libertadores). O sistema exibe o país cadastrado para o clube quando o nome tem uma única associação de país no catálogo; senão identifica explicitamente o país/região do campeonato.
- Alterar ON/OFF **não executa filtros automaticamente**: é preciso clicar em **Aplicar filtros**. Mudar a subaba de mercado reaproveita as estatísticas já consultadas.
- Sem alteração nas tabelas do PostgreSQL. A elegibilidade é armazenada somente em cache de curta duração para evitar recomputações desnecessárias.

## Correção e diagnóstico do erro 500 na aba Estatísticas por Campeonato

- No comparativo geral sem odds, o backend não calcula mais a tabela histórica de 70%/30% nem faz a segunda consulta de partidas recentes que não são exibidas na aba. O histórico de 10 anos por clique continua disponível pelo endpoint específico.
- Ao clicar em **Aplicar filtros**, a interface limpa o aviso de fonte pendente.
- Qualquer exceção em `POST /api/backtesting/evaluate`, incluindo erro durante a serialização da resposta, gera um **ID de diagnóstico**; o traceback é salvo localmente em `backend/logs/backtesting_errors.log`. Esse arquivo não é enviado para o navegador.
- Sem acesso ao log e ao banco real, a causa exata do 500 reportado ainda não pode ser assegurada. Depois de atualizar, repita a análise e, caso ela falhe, execute:

```powershell
cd "C:\Users\stefa\Desktop\Portfólio 2026\backtest_apostas"
Get-Content ".\backend\logs\backtesting_errors.log" -Tail 90
```

Copie o resultado (apague senhas e outros segredos, caso apareçam) para identificação definitiva. O erro de `M_ID` em um script separado de extensão/navegador não comprova que esse script originou o 500 da API.

## Subabas — Estatísticas por Campeonato (atualização)

- A página Backtesting continua abrindo em **Estatísticas por Campeonato**, inicialmente na subaba **Geral**.
- **Geral** apresenta exclusivamente os cards de resumo e os 12 cards dos mercados. Os gráficos e a tabela de placares ficam fora dessa subaba.
- Cada um dos 12 mercados tem sua própria subaba (MO Casa, MO Fora, Empate, Lay Casa/Fora, Lay Goleada Casa/Fora, Over 0,5/1,5/2,5, Under 3,5 e Ambas Marcam). Cada uma apresenta **somente o gráfico de comparação do mercado**.
- A subaba **Placar exato** preserva a distribuição de placares, sem misturá-la com as métricas gerais.
- Ao clicar no campeonato do gráfico, o usuário consulta os **10 últimos anos-calendário** desse mercado, com jogos, Green, Red e Win Rate; o ROI aparece somente com cotação real.
- Os filtros de País, Competição, Ano De/Até, Divisão, Formato e fonte ON/OFF continuam os mesmos. A subaba muda apenas a visualização dos resultados já carregados, sem disparar `POST /api/backtesting/evaluate`.
- A mudança está limitada à apresentação em `frontend/src/pages/Backtesting.tsx` e `frontend/src/styles.css`. O banco e os endpoints não são alterados.

## Atualização Scanner — filtros encadeados (13/10/2026)

- `Continente`, `País`, `Campeonato`, `Divisão`, `Formato`, `Ano — de` e `Ano — até` são opcionais no Scanner.
- Os cinco primeiros são listas suspensas alimentadas por `GET /api/analysis-v3/scanner/filter-options`, com valores distintos encontrados em `public.odds` e cache de cinco minutos.
- As listas são encadeadas em memória na ordem Continente → País → Campeonato → Divisão → Formato, sem requisição adicional a cada seleção.
- Se a tabela `odds` não tiver coluna `continente`, o país é mapeado para o continente conhecido, com valores desconhecidos classificados como `Não informado`. Nenhuma alteração no banco é necessária.
- `POST /api/analysis-v3/scanner/analyze` aplica todos os filtros ao SQL antes de consultar as odds e calcular Green/Red, ROI, faixas candidatas e sequências.
- Trocar qualquer filtro não calcula automaticamente: clique em `Analisar mercados`.
- Os modos e grupos de mercado anteriores foram preservados.

## Atualização — Mercados do EV e precisão das odds (13/10/2026)
- Backtesting de confrontos: seleção de 49 mercados em 11 grupos (Match Odds FT/HT, Over/Under HT/FT, Ambas Marcam, Dupla Chance, Placar Exato, Goleadas e Lay).
- Estimativas FT com ponderação temporal e probabilidades complementares (Under/Over, Dupla Chance, BTTS Não). Placares exatos combinam dados históricos e prior de Poisson.
- Mercados HT só exibem probabilidade quando pelo menos 12 partidas com gols por minuto válidos cobrem pelo menos 60% da amostra com mando; sem isso, permanecem indisponíveis, sem inventar o resultado do intervalo.
- EV Back: 100 × (probabilidade × odd − 1). EV Lay: responsabilidade de R$100; EV (%) = 100 × [P(green) / (odd − 1) − P(red)]. A odd de equilíbrio Lay é máxima, e não mínima.
- Campo Odd disponível padronizado para pt-BR com duas casas decimais após edição. Odd justa, odd Lay máxima e odds do Scanner são exibidas sempre com duas casas decimais.
- Não foram alteradas tabelas do banco. Para validar a instalação: atualizar_projeto.ps1 e iniciar.ps1.
