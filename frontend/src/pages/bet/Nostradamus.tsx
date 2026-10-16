import { useMemo, useState } from 'react'
import { api } from '../../api'
import { Catalog, LineChart, Method, Modal, Stat, brl, dateBr, num, odd, plClass } from './shared'

type Run={jogos:number;lucro:number;inicio:string|null;fim:string|null}
type Row={id:string;data:string;jogo:string;pais:string;campeonato:string;final:string;entrada_minuto:number;entrada_placar:string;
 entrada_odd:number;odd_origem:string;saida:{minute:number;score:string;odd:number}|null;stake:number;exposicao:number;lucro:number;
 resultado:string;odd_casa:number|null;odd_empate:number|null;odd_fora:number|null}
type Summary={jogos:number;greens?:number;reds?:number;win_rate?:number;lucro?:number;roi_exposicao?:number|null;lucro_por_jogo?:number;
 odd_media?:number;good_run?:Run;bad_run?:Run;saidas_antecipadas?:number;entradas_estimadas?:number;drawdown_max?:number;exposicao_total?:number}
type Suggestion={tipo:string;titulo:string;descricao:string;jogos:number;lucro:number;lucro_por_jogo:number;estavel:boolean|null;
 condicao:{field:string|null;op:string;value:number}|null}
type Result={metodo:string;definicao:any;resumo:Summary;descartes:Record<string,number>;avisos:string[];curva:{data:string;acumulado:number}[];
 por_ano:(Summary&{ano:string})[];sugestoes:{aviso:string;itens:Suggestion[]};jogos:Row[]}

type ProphecyClub={time:string;pais:string|null;jogos:number;proximidade:number;vitorias_pct:number;derrotas_pct:number;
 over_0_5:number;over_1_5:number;over_2_5:number;ambos_marcam:number;goleadas_aplicadas:number;goleadas_sofridas:number;
 placares_mais_frequentes:{placar:string;jogos:number}[]}
type ProphecyResult={aviso:string;janela:number;mandante:ProphecyClub[];visitante:ProphecyClub[]}

const DISCARD:Record<string,string>={sem_entrada:'sem entrada na janela/placar',sem_linha_do_tempo:'sem minutos dos gols',sem_preco:'sem preço'}
const clone=<T,>(v:T):T=>JSON.parse(JSON.stringify(v))
const pct=(v?:number|null)=>v==null?'—':`${num(v,1)}%`

const SAMPLE=`20	Jogos	20
8 - 4 - 8	V - E - D	12 - 6 - 2
1,80	Gols marcados / jogo	2,20
1,70	Gols sofridos / jogo	0,95
90,0%	Over 0,5	95,0%
85,0%	Over 1,5	80,0%
70,0%	Over 2,5	50,0%
50,0%	Under 3,5	60,0%
80,0%	Ambos marcam	55,0%
15,0%	Sem sofrer gol	35,0%
15,0%	Sem marcar gol	15,0%
4 / 0	Goleadas a favor / contra	4 / 0
52,5%	Gols no 1º tempo	42,9%
43,8%	Abriu o placar	64,7%
42,9%	Venceu após abrir o placar	72,7%`

export default function Nostradamus({methods}:{catalog:Catalog;methods:Method[]}) {
 const [tab,setTab]=useState<'avaliacao'|'profecia'>('avaliacao')
 return <section className="bf-main full">
  <h2 className="bf-h2">Nostradamus</h2>
  <div className="bf-seg" role="tablist" aria-label="Abas do Nostradamus" style={{maxWidth:420,marginBottom:14}}>
   <button type="button" role="tab" aria-selected={tab==='avaliacao'} className={tab==='avaliacao'?'on':''} onClick={()=>setTab('avaliacao')}>Avaliação do Método</button>
   <button type="button" role="tab" aria-selected={tab==='profecia'} className={tab==='profecia'?'on':''} onClick={()=>setTab('profecia')}>Profecia</button>
  </div>
  {tab==='avaliacao'?<Avaliacao methods={methods}/>:<Profecia/>}
 </section>
}

function Avaliacao({methods}:{methods:Method[]}) {
 const [methodId,setMethodId]=useState<number|''>('')
 const [stake,setStake]=useState('100')
 const [mode,setMode]=useState<'liability'|'stake'>('liability')
 const [commission,setCommission]=useState('0')
 const [formato,setFormato]=useState('')
 const [from,setFrom]=useState('')
 const [to,setTo]=useState('')
 const [loading,setLoading]=useState(false)
 const [error,setError]=useState('')
 const [result,setResult]=useState<Result|null>(null)
 const [showGames,setShowGames]=useState(false)
 const [extra,setExtra]=useState<Suggestion|null>(null)
 const method=methods.find(m=>m.id===methodId)
 const run=async(suggestion:Suggestion|null=null)=>{
  if(!method){setError('Selecione um método.');return}
  const value=Number(stake.replace(',','.'))
  if(!(value>0)){setError('Informe um valor por jogo maior que zero.');return}
  setLoading(true);setError('');setExtra(suggestion)
  const definicao=clone(method.definicao)
  if(suggestion?.condicao?.field)definicao.conditions.push({field:suggestion.condicao.field,op:suggestion.condicao.op,value:suggestion.condicao.value})
  try{
   setResult(await api<Result>('/api/bet/nostradamus',{method:'POST',body:JSON.stringify({definicao,stake:value,stake_mode:mode,
    comissao:(Number(commission.replace(',','.'))||0)/100,formato:formato||null,data_inicio:from||null,data_fim:to||null})}))
  }catch(e:any){setError(e.message);setResult(null)}finally{setLoading(false)}
 }
 const r=result?.resumo
 return <>
  <p className="bf-hint">Teste histórico do método sobre a base de jogos.</p>
  <div className="bf-form inline">
   <label>Método<select value={methodId} onChange={e=>{setMethodId(e.target.value?Number(e.target.value):'');setResult(null)}}>
    <option value="">Selecione...</option>{methods.map(m=><option key={m.id} value={m.id}>{m.nome}</option>)}</select></label>
   <label>Valor por jogo (R$)<input inputMode="decimal" value={stake} onChange={e=>setStake(e.target.value)}/></label>
   <label>Como aplicar o valor<select value={mode} onChange={e=>setMode(e.target.value as 'liability'|'stake')}>
    <option value="liability">Responsabilidade fixa (Lay arrisca o valor)</option><option value="stake">Stake fixa (padrão Betfair)</option></select></label>
   <label>Comissão (%)<input inputMode="decimal" value={commission} onChange={e=>setCommission(e.target.value)}/></label>
   <label>Formato<select value={formato} onChange={e=>setFormato(e.target.value)}><option value="">Conforme o método</option><option>Liga</option><option>Copa</option></select></label>
   <label>De<input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></label>
   <label>Até<input type="date" value={to} onChange={e=>setTo(e.target.value)}/></label>
   <button type="button" className="bf-btn primary" disabled={loading} onClick={()=>run(null)}>{loading?'Calculando...':'Executar teste'}</button>
  </div>
  {error&&<p className="bf-alert err" role="alert">{error}</p>}
  {result&&r&&<>
   {extra&&<p className="bf-alert info">Teste com a condição extra: <strong>{extra.titulo}</strong> (não salva no método).</p>}
   {r.jogos===0?<p className="bf-alert info">Nenhum jogo se encaixa no padrão.</p>:<>
    <div className="bf-stats">
     <Stat label="Jogos no padrão" value={r.jogos}/>
     <Stat label="Win rate" value={`${num(r.win_rate)}%`} hint="Jogos com lucro maior que zero sobre o total"/>
     <Stat label="Profit / Loss" value={brl(r.lucro)} tone={plClass(r.lucro)}/>
     <Stat label="ROI sobre a exposição" value={r.roi_exposicao==null?'—':`${num(r.roi_exposicao)}%`} tone={plClass(r.roi_exposicao)}/>
     <Stat label="Lucro por jogo" value={brl(r.lucro_por_jogo)} tone={plClass(r.lucro_por_jogo)}/>
     <Stat label="Odd média de entrada" value={odd(r.odd_media)}/>
     <Stat label="Maior queda (drawdown)" value={brl(r.drawdown_max)} tone="bf-neg"/>
     <Stat label="Saídas antecipadas" value={r.saidas_antecipadas??0}/>
     {r.good_run&&<Stat label="Maior Good Run" tone="bf-pos" value={`${r.good_run.jogos} greens`} hint={`${brl(r.good_run.lucro)} · ${dateBr(r.good_run.inicio)} a ${dateBr(r.good_run.fim)}`}/>}
     {r.bad_run&&<Stat label="Maior Bad Run" tone="bf-neg" value={`${r.bad_run.jogos} reds`} hint={`${brl(r.bad_run.lucro)} · ${dateBr(r.bad_run.inicio)} a ${dateBr(r.bad_run.fim)}`}/>}
    </div>
    <p className="bf-muted">{r.good_run&&r.bad_run&&<>Good Run: {r.good_run.jogos} greens seguidos ({brl(r.good_run.lucro)}, {dateBr(r.good_run.inicio)} a {dateBr(r.good_run.fim)}) · Bad Run: {r.bad_run.jogos} reds seguidos ({brl(r.bad_run.lucro)}, {dateBr(r.bad_run.inicio)} a {dateBr(r.bad_run.fim)}) · </>}Green {r.greens} · Red {r.reds} · Exposição somada {brl(r.exposicao_total)} · Descartados: {Object.entries(result.descartes).filter(([k])=>DISCARD[k]).map(([k,v])=>`${v} ${DISCARD[k]}`).join(', ')||'nenhum'} · {result.descartes.fora_das_condicoes??0} jogos fora das condições</p>
    {result.avisos.map((a,i)=><p key={i} className="bf-alert warn">⚠ {a}</p>)}
    <div className="bf-actions"><button type="button" className="bf-btn" onClick={()=>setShowGames(true)}>Visualizar os {r.jogos} jogos</button></div>
    <h3 className="bf-h3">Evolução do lucro acumulado</h3>
    <LineChart points={result.curva.map(p=>({label:dateBr(p.data),value:p.acumulado}))} baseline={0}/>
    <h3 className="bf-h3">Resultado por ano</h3>
    <div className="bf-tablewrap"><table className="bf-table"><thead><tr><th>Ano</th><th>Jogos</th><th>Win rate</th><th>Profit / Loss</th><th>ROI</th></tr></thead><tbody>
     {result.por_ano.map(y=><tr key={y.ano}><td>{y.ano}</td><td>{y.jogos}</td><td>{num(y.win_rate)}%</td><td className={plClass(y.lucro)}>{brl(y.lucro)}</td><td className={plClass(y.roi_exposicao)}>{y.roi_exposicao==null?'—':`${num(y.roi_exposicao)}%`}</td></tr>)}</tbody></table></div>
    <h3 className="bf-h3">Sugestões para lapidar os jogos</h3>
    <p className="bf-hint">{result.sugestoes.aviso}</p>
    {result.sugestoes.itens.length===0?<p className="bf-muted">Nenhuma sugestão relevante encontrada.</p>:<ul className="bf-suggest">
     {result.sugestoes.itens.map((s,i)=><li key={i}>
      <div><strong>{s.titulo}</strong>{s.estavel===true&&<span className="bf-tag ok">estável</span>}{s.estavel===false&&<span className="bf-tag warn">instável</span>}
       <p>{s.descricao}</p></div>
      {s.condicao?.field&&<button type="button" className="bf-btn small" disabled={loading} onClick={()=>run(s)}>Testar com este filtro</button>}</li>)}</ul>}
   </>}
   {showGames&&<GamesModal rows={result.jogos} name={result.metodo} onClose={()=>setShowGames(false)}/>}
  </>}
 </>
}

function Profecia() {
 const [text,setText]=useState('')
 const [loading,setLoading]=useState(false)
 const [error,setError]=useState('')
 const [result,setResult]=useState<ProphecyResult|null>(null)
 const run=async()=>{
  if(text.trim().length<10){setError('Cole a tabela de estatísticas (mandante | indicador | visitante).');return}
  setLoading(true);setError('')
  try{setResult(await api<ProphecyResult>('/api/bet/profecia',{method:'POST',body:JSON.stringify({texto:text,top:12})}))}
  catch(e:any){setError(e.message);setResult(null)}finally{setLoading(false)}
 }
 return <>
  <p className="bf-hint">Cole o resumo no formato da Casa de Apostas (coluna esquerda = mandante, direita = visitante). Buscamos clubes com perfil parecido nos últimos 20 jogos, sem considerar mando de campo.</p>
  <div className="bf-form" style={{gridTemplateColumns:'1fr'}}>
   <label className="wide">Estatísticas coladas
    <textarea rows={14} value={text} onChange={e=>setText(e.target.value)} placeholder={SAMPLE} style={{fontFamily:'Consolas,monospace',fontSize:12,resize:'vertical'}}/>
   </label>
  </div>
  <div className="bf-actions">
   <button type="button" className="bf-btn primary" disabled={loading} onClick={run}>{loading?'Buscando clubes...':'Consultar profecia'}</button>
   <button type="button" className="bf-btn small" onClick={()=>setText(SAMPLE)}>Usar exemplo</button>
   {text&&<button type="button" className="bf-btn small" onClick={()=>{setText('');setResult(null)}}>Limpar</button>}
  </div>
  {error&&<p className="bf-alert err" role="alert">{error}</p>}
  {result&&<>
   <p className="bf-alert info">{result.aviso}</p>
   <div className="bf-two">
    <ClubMatches title="Parecidos com o mandante (coluna esquerda)" clubs={result.mandante}/>
    <ClubMatches title="Parecidos com o visitante (coluna direita)" clubs={result.visitante}/>
   </div>
  </>}
 </>
}

function ClubMatches({title,clubs}:{title:string;clubs:ProphecyClub[]}) {
 return <div>
  <h3 className="bf-h3">{title}</h3>
  {!clubs.length?<p className="bf-muted">Nenhum clube encontrado.</p>:
   <div className="bf-tablewrap"><table className="bf-table dense"><thead><tr>
    <th>Clube</th><th>Prox.</th><th>Vitórias</th><th>Derrotas</th><th>Over 0,5</th><th>Over 1,5</th><th>Over 2,5</th>
    <th>Ambos</th><th>Goleadas +</th><th>Goleadas −</th><th>Placares + freq.</th>
   </tr></thead><tbody>
    {clubs.map(c=><tr key={c.time}>
     <td>{c.time}{c.pais&&<small className="bf-muted"> · {c.pais}</small>}</td>
     <td><strong>{pct(c.proximidade)}</strong></td>
     <td>{pct(c.vitorias_pct)}</td><td>{pct(c.derrotas_pct)}</td>
     <td>{pct(c.over_0_5)}</td><td>{pct(c.over_1_5)}</td><td>{pct(c.over_2_5)}</td>
     <td>{pct(c.ambos_marcam)}</td>
     <td>{c.goleadas_aplicadas}</td><td>{c.goleadas_sofridas}</td>
     <td>{c.placares_mais_frequentes.map(p=>`${p.placar} (${p.jogos}x)`).join(' · ')||'—'}</td>
    </tr>)}
   </tbody></table></div>}
 </div>
}

function GamesModal({rows,name,onClose}:{rows:Row[];name:string;onClose:()=>void}) {
 const [filter,setFilter]=useState('')
 const [limit,setLimit]=useState(200)
 const shown=useMemo(()=>{
  const q=filter.trim().toLocaleLowerCase()
  return q?rows.filter(r=>`${r.jogo} ${r.campeonato} ${r.pais}`.toLocaleLowerCase().includes(q)):rows
 },[rows,filter])
 return <Modal title={`${name} · ${rows.length} jogos`} onClose={onClose} wide>
  <div className="bf-form inline"><label>Filtrar por clube ou campeonato<input value={filter} onChange={e=>{setFilter(e.target.value);setLimit(200)}}/></label></div>
  <div className="bf-tablewrap tall"><table className="bf-table dense"><thead><tr><th>Data</th><th>Jogo</th><th>Campeonato</th><th>Odds iniciais (1 / X / 2)</th><th>Entrada</th><th>Odd</th><th>Saída</th><th>Final</th><th>P/L</th></tr></thead><tbody>
   {shown.slice(0,limit).map((g,i)=><tr key={`${g.id}-${i}`}><td>{dateBr(g.data)}</td><td>{g.jogo}</td><td>{g.pais} · {g.campeonato}</td>
    <td>{odd(g.odd_casa)} / {odd(g.odd_empate)} / {odd(g.odd_fora)}</td><td>{g.entrada_minuto}' · {g.entrada_placar}</td>
    <td>{odd(g.entrada_odd)}{g.odd_origem==='estimada'&&<span className="bf-tag warn" title="Odd estimada pelo modelo">est.</span>}</td>
    <td>{g.saida?`${g.saida.minute}' · ${g.saida.score} @ ${odd(g.saida.odd)}`:'—'}</td><td>{g.final}</td>
    <td className={plClass(g.lucro)}>{brl(g.lucro)}</td></tr>)}</tbody></table></div>
  {shown.length>limit&&<button type="button" className="bf-btn small" onClick={()=>setLimit(l=>l+300)}>Mostrar mais ({shown.length-limit} restantes)</button>}
 </Modal>
}
