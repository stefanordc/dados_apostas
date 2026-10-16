import { Component, ReactNode, useEffect, useState } from 'react'
import { api } from '../api'
import './bet/bet.css'
import { Catalog, Method, Modal, brl } from './bet/shared'
import Metodos from './bet/Metodos'
import Nostradamus from './bet/Nostradamus'
import CasaApostas from './bet/CasaApostas'
import Relatorio from './bet/Relatorio'
import Conciliacao from './bet/Conciliacao'

type Config = {banca_inicial:number;banca_atual:number;stake_fixa:number|null;stake_travada:boolean;data_limite:string|null}
const TABS=[{id:'metodos',label:'Métodos'},{id:'nostradamus',label:'Nostradamus'},{id:'casa',label:'Casa de Apostas'},{id:'conciliacao',label:'Conciliação'},{id:'relatorio',label:'Relatório'}] as const
type TabId=typeof TABS[number]['id']

class Boundary extends Component<{children:ReactNode;resetKey:string},{error:Error|null}> {
 state={error:null as Error|null}
 static getDerivedStateFromError(error:Error){return {error}}
 componentDidUpdate(prev:{resetKey:string}){if(prev.resetKey!==this.props.resetKey&&this.state.error)this.setState({error:null})}
 render(){
  if(this.state.error)return <div className="bf-alert err" role="alert" style={{margin:16}}>Ocorreu um erro nesta aba: {this.state.error.message}. <button type="button" className="bf-btn small" onClick={()=>this.setState({error:null})}>Tentar de novo</button></div>
  return this.props.children
 }
}

export default function BetTeste(){
 const [tab,setTab]=useState<TabId>('casa')
 const [catalog,setCatalog]=useState<Catalog|null>(null)
 const [methods,setMethods]=useState<Method[]>([])
 const [config,setConfig]=useState<Config|null>(null)
 const [error,setError]=useState('')
 const [resetOpen,setResetOpen]=useState(false)
 const [password,setPassword]=useState('')
 const [resetError,setResetError]=useState('')
 const [resetting,setResetting]=useState(false)
 const [version,setVersion]=useState(0)
 const loadMethods=()=>api<Method[]>('/api/bet/metodos').then(setMethods).catch((e:Error)=>setError(e.message))
 const loadConfig=()=>api<Config>('/api/bet/config').then(setConfig).catch((e:Error)=>setError(e.message))
 useEffect(()=>{
  api<Catalog>('/api/bet/catalogo').then(setCatalog).catch((e:Error)=>setError(e.message))
  loadMethods();loadConfig()
 },[])
const resetBank=async()=>{
  setResetting(true);setResetError('')
  try{
   await api('/api/bet/banca/redefinir',{method:'POST',body:JSON.stringify({senha:password})})
   setResetOpen(false);setPassword('');setVersion(v=>v+1);await loadConfig()
  }catch(e:any){setResetError(e.message)}finally{setResetting(false)}
 }
 return <div className="bf-page">
  <header className="bf-topbar">
   <div className="bf-logo"><span>BET</span> Teste<small>Exchange simulada</small></div>
   <nav className="bf-nav" aria-label="Seções do BET Teste">{TABS.map(t=><button key={t.id} type="button" className={tab===t.id?'on':''} onClick={()=>setTab(t.id)}>{t.label}</button>)}</nav>
   <div className="bf-balance-wrap"><div className="bf-balance" aria-live="polite"><span>Banca</span><strong>{brl(config?.banca_atual)}</strong></div>
    <button type="button" className="bf-btn small reset" onClick={()=>{setResetOpen(true);setResetError('');setPassword('')}}>Redefinir banca</button></div>
  </header>
  {error&&<p className="bf-alert err" role="alert">{error}</p>}
  <div className="bf-body">
   <Boundary resetKey={tab}>
   {!catalog?<p className="bf-muted pad">Carregando dados da tabela de odds (a primeira carga pode levar cerca de 1 minuto)...</p>:<>
    {tab==='metodos'&&<Metodos catalog={catalog} methods={methods} reload={loadMethods}/>}
    {tab==='nostradamus'&&<Nostradamus catalog={catalog} methods={methods}/>}
    {tab==='casa'&&config&&<CasaApostas key={version} config={config} reloadConfig={loadConfig} coverage={catalog.cobertura}/>}
    {tab==='conciliacao'&&<Conciliacao/>}
    {tab==='relatorio'&&<Relatorio key={version} onChange={loadConfig}/>}
   </>}
   </Boundary>
  </div>
  {resetOpen&&<Modal title="Redefinir banca" onClose={()=>setResetOpen(false)}>
   <form onSubmit={e=>{e.preventDefault();resetBank()}} className="bf-form">
    <p className="wide">Todas as apostas serão apagadas e a banca voltará para <strong>R$ 1.000,00</strong>. Esta ação não pode ser desfeita.</p>
    <label className="wide">Senha<input type="password" autoFocus autoComplete="off" value={password} onChange={e=>setPassword(e.target.value)}/></label>
    {resetError&&<p className="bf-alert err wide" role="alert">{resetError}</p>}
    <div className="bf-actions wide"><button type="submit" className="bf-btn danger" disabled={resetting||!password}>{resetting?'Redefinindo...':'Confirmar e redefinir'}</button>
     <button type="button" className="bf-btn" onClick={()=>setResetOpen(false)}>Cancelar</button></div>
   </form></Modal>}
 </div>
}
