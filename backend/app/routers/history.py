from fastapi import APIRouter, Query
from ..repositories import history_repository as repo
router=APIRouter(prefix='/api/history',tags=['histórico'])

def build_filters(country=None,season=None,competition=None,round=None,club=None,home=None,away=None,home_goals_min=None,home_goals_max=None,away_goals_min=None,away_goals_max=None,goal_diff_min=None,goal_diff_max=None,winner=None,home_win=None,away_win=None):return locals()

@router.get('/options')
def history_options(country:str|None=None,season:str|None=None,competition:str|None=None,round:str|None=None,club:str|None=None,home:str|None=None,away:str|None=None,winner:str|None=None,home_win:str|None=None,away_win:str|None=None):
    return repo.options(build_filters(country,season,competition,round,club,home,away,winner=winner,home_win=home_win,away_win=away_win))

@router.get('/games')
def history_games(country:str|None=None,season:str|None=None,competition:str|None=None,round:str|None=None,club:str|None=None,home:str|None=None,away:str|None=None,home_goals_min:int|None=Query(default=None,ge=0),home_goals_max:int|None=Query(default=None,ge=0),away_goals_min:int|None=Query(default=None,ge=0),away_goals_max:int|None=Query(default=None,ge=0),goal_diff_min:int|None=Query(default=None,ge=0),goal_diff_max:int|None=Query(default=None,ge=0),winner:str|None=None,home_win:str|None=None,away_win:str|None=None,page:int=Query(default=1,ge=1),page_size:int=Query(default=50,ge=10,le=200)):
    return repo.search(build_filters(country,season,competition,round,club,home,away,home_goals_min,home_goals_max,away_goals_min,away_goals_max,goal_diff_min,goal_diff_max,winner,home_win,away_win),page,page_size)
