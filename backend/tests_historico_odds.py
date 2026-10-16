"""Regressões: conciliação sem banco ativo."""
import types,sys
sys.modules['app.db']=types.SimpleNamespace(app_engine=None, history_connection=lambda:None)
from app.services.historico_odds_service import (reconcile,season_code,odd_value,date_code,pending_name_pairs,canonical_name,unresolved_fixture_matches)
from app.services import backtesting_service as b


def fixture(date='2026-03-02', home='Bayern de Munique', away='Hamburgo', season='2025/2026', gh=2,ga=1):
    return {'date':date, 'season':season, 'home':home, 'away':away, 'gh':gh, 'ga':ga, 'year':int(date[:4])}


def quote(date='02/03/2026', home='Bayern de Munique',away='Hamburgo',season='2025/26', **kwargs):
    return {'pais':'Alemanha','campeonato':'Alemão','data':date,'temporada':season,'casa':home,'fora':away,
            'odd_casa':'1,50','odd_empate':'4,00','odd_fora':'7,00',
            'over_1_5':'1,23','under_3_5':'1,55', 'ambos_marcam_sim':'1,88', **kwargs}


def test_normalization():
    assert season_code('2025/26') == season_code('2025/2026')
    assert season_code('2026') == '2026'
    assert date_code('02/03/2026') == '2026-03-02'
    assert odd_value('1,67') == 1.67
    assert odd_value('0,95') is None


def test_link_green_red():
    games=[fixture()]
    result=reconcile(games,[quote()])
    assert result['matched_games']==1
    g=games[0]
    assert g['over15_odd']==1.23 and g['btts_odd']==1.88
    assert b._market_evaluation(g,'back_home','Bayern de Munique','any') == (True,True,1.5)
    assert b._market_evaluation(g,'over15','Bayern de Munique','any') == (True,True,1.23)
    assert b._market_evaluation(g,'btts','Bayern de Munique','any') == (True,True,1.88)
    assert b._market_evaluation(g,'under35','Bayern de Munique','any') == (True,True,1.55)
    empty={k:(None,None) for k in ('mo','over15','over25','btts')}
    s=b._summary(games,'over15','Bayern de Munique','any',empty)
    assert s['profit']==23 and s['settled']==1


def test_unresolved_multiple_fixtures_prompt_manual():
    games=[fixture(home='Bayern Munich',away='HSV'),fixture(home='Dortmund SC',away='Werder')]
    odds=[quote(home='Bayern de Munique',away='Hamburgo'),quote(home='BVB',away='Werder Bremen')]
    assert reconcile(games,odds)['matched_games']==0
    assert pending_name_pairs(games,odds)==[]
    unresolved=unresolved_fixture_matches(games,odds)
    assert len(unresolved)==2
    assert len(unresolved[0]['candidatos'])==2
    assert unresolved[0]['jogos_casa']=='Bayern Munich'


def test_unresolved_becomes_normal_pending_after_first_manual_alias():
    games=[fixture(home='Bayern Munich',away='HSV'),fixture(home='Dortmund SC',away='Werder')]
    odds=[quote(home='Bayern de Munique',away='Hamburgo'),quote(home='BVB',away='Werder Bremen')]
    decisions={'bayernmunich':'FC Bayern', 'bayerndemunique':'FC Bayern', 'fcbayern':'FC Bayern'}
    pending=pending_name_pairs(games,odds,decisions)
    assert len(pending)==1
    assert pending[0]['historico_jogos']=='HSV'
    assert pending[0]['historico_odds']=='Hamburgo'


def test_wrong_visitor_cannot_match():
    games=[fixture(away='FC Köln')]
    assert reconcile(games,[quote()])['matched_games']==0
    assert 'home_odd' not in games[0]


def test_alias_with_ids_requires_manual_confirmation():
    games=[fixture(home='FC Bayern',away='Hamburger SV')]
    names={'fcbayern':27,'bayerndemunique':27,'hamburgersv':22,'hamburgo':22}
    assert reconcile(games,[quote()],names)['matched_games']==0
    pending=pending_name_pairs(games,[quote()],{},names)
    assert len(pending)==2
    decisions={'fcbayern':'Bayern de Munique','bayerndemunique':'Bayern de Munique',
               'hamburgersv':'Hamburgo','hamburgo':'Hamburgo'}
    assert reconcile(games,[quote()],names,decisions)['matched_games']==1


def test_case_only_difference_requires_standard_name():
    games=[fixture(home='BAYERN DE MUNIQUE')]
    assert reconcile(games,[quote()])['matched_games']==0
    pairs=pending_name_pairs(games,[quote()])
    assert len(pairs)==1 and pairs[0]['historico_odds']=='Bayern de Munique'
    decisions={'bayerndemunique':'Bayern de Munique'}
    assert reconcile(games,[quote()],decisions=decisions)['matched_games']==1
    assert canonical_name('BAYERN DE MUNIQUE',decisions)=='Bayern de Munique'


def test_diff_name_custom_choice():
    games=[fixture(home='Bayern Munich')]
    assert reconcile(games,[quote()])['matched_games']==0
    pairs=pending_name_pairs(games,[quote()]); assert len(pairs)==1
    decisions={'bayernmunich':'FC Bayern München', 'bayerndemunique':'FC Bayern München',
               'fcbayernmunchen':'FC Bayern München'}
    assert reconcile(games,[quote()],decisions=decisions)['matched_games']==1
    assert canonical_name('Bayern Munich',decisions)=='FC Bayern München'


def test_different_fixtures_same_day_not_guessed():
    games=[fixture(home='Bayern Munich',away='Berlin'), fixture(home='Bayer 04',away='Hamburgo')]
    odds=[quote(home='Borussia',away='Hannover'),quote(home='Stuttgart',away='Dortmund')]
    assert reconcile(games,odds)['matched_games']==0
    assert pending_name_pairs(games,odds)==[]


def test_duplicates_rejected_safely():
    games=[fixture()]
    old=quote()
    updated={**old,'odd_casa':'2,20'}
    result=reconcile(games,[old,updated])
    assert result['ambiguous_games']==1
    assert games[0]['odds_source']=='ambiguous'


def test_identical_duplicate_allowed():
    games=[fixture()]
    row=quote()
    assert reconcile(games,[row,row])['matched_games']==1


if __name__=='__main__':
 for name,fn in sorted(globals().items()):
  if name.startswith('test_') and callable(fn):
   fn();print('PASS',name)


def test_reconcile_adds_optional_metadata_without_touching_score():
    games=[fixture()]
    q=quote(divisao='Primeira',formato='Liga')
    assert reconcile(games,[q])['matched_games']==1
    assert games[0]['divisao']=='Primeira' and games[0]['formato']=='Liga'
    assert games[0]['gh']==2 and games[0]['ga']==1


def test_distinct_metadata_for_same_fixture_is_ambiguous():
    games=[fixture()]
    q1=quote(divisao='Primeira',formato='Liga')
    q2=quote(divisao='Segunda',formato='Liga')
    assert reconcile(games,[q1,q2])['ambiguous_games']==1
    assert games[0].get('divisao') is None
