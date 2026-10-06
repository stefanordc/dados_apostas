import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Cadastros from './pages/Cadastros'
import Historico from './pages/Historico'
import ELOClubes from './pages/ELOClubes'
import Clubes from './pages/Clubes'
import Backtest from './pages/Backtest'
import Rankings from './pages/Rankings'
export default function App(){return <Routes><Route element={<Layout/>}><Route path="/" element={<Navigate to="/elo" replace/>}/><Route path="/elo" element={<ELOClubes/>}/><Route path="/backtest" element={<Backtest/>}/><Route path="/rankings" element={<Rankings/>}/><Route path="/clubes" element={<Clubes/>}/><Route path="/historico" element={<Historico/>}/><Route path="/cadastros" element={<Cadastros/>}/></Route></Routes>}
