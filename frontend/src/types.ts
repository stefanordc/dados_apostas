export type Option = { id?: number; nome: string; [key: string]: unknown }
export type HistoryOptions = { countries:string[];seasons:string[];competitions:string[];rounds:string[];clubs:string[];home_teams:string[];away_teams:string[];winners:string[] }
export type HistoryStats = { total_jogos:number;vitorias_casa:number;vitorias_fora:number;empates?:number;percentual_vitorias_casa:number;percentual_empates?:number;percentual_vitorias_fora:number;gols_casa:number;gols_fora:number;total_gols:number;media_gols_casa:number;media_gols_fora:number;media_geral_gols:number }
