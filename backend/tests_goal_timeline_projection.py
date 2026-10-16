"""Garantias da nova página: gols, placares, período e projeção."""
import sys
import types
from datetime import date, timedelta
import pytest
sys.modules.setdefault('app.db', types.SimpleNamespace(app_engine=None,history_engine=None,history_connection=lambda:None))
from app.services import goal_timeline_service as timeline
from app.services import ml_projection_service as ml
from app.services import sofascore_match_service as sofa


def game(game_id, home='Casa', away='Fora', goals=(2,1)):
    return {'id_jogo':game_id,'data':date.today()-timedelta(days=1),
            'casa':home,'fora':away,'gh':goals[0],'ga':goals[1]}


def event(minute, score, order=1):
    return {'minute':minute,'score':score,'score_home':None,'score_away':None,'order':order}


def test_open_expand_equalize_then_win():
    g=game(1,goals=(3,2))
    events={"1":[event('12','1-0'),event('30','2-0'),event('45+2','2-1'),
                 event('70','2-2'),event('90+3','3-2')]}
    result=timeline._team_metrics([g],'Casa',events)
    assert result['opened']['value']==100
    assert result['extended_after_open']['value']==100
    assert result['equalized_after_open']['value']==100
    assert result['won_after_open']['value']==100
    assert result['lost_after_open']['value']==0
    assert result['first_half']['count']==2
    assert result['second_half']['count']==1
    assert sum(x['count'] for x in result['minute_bands'])==3
    assert next(x for x in result['minute_bands'] if x['label']=='90+')['count']==1
    result_away=timeline._team_metrics([g],'Fora',events)
    assert result_away['opened']['value']==0
    assert result_away['first_half']['count']==1


def test_45_added_time_comes_before_regular_46():
    g=game(1,goals=(1,1))
    # A listagem está fora da ordem, deve reconstruir com 45+4 antes do 46.
    values=[event('46','1-1'),event('45+4','1-0')]
    seq=timeline._sequence(g,values)
    assert seq is not None
    assert seq[0]['band']=='45+'
    assert seq[1]['band']=='46-60'


def test_incomplete_timeline_not_in_denominator():
    complete=game(1,goals=(1,0))
    incomplete=game(2,goals=(2,1))
    report=timeline._team_metrics([complete,incomplete],'Casa',{'1':[event('7','1-0')],'2':[event('22','1-0')]})
    assert report['valid_games']==1
    assert report['requested_games']==2
    assert report['opened']['value']==100


def test_regular_goal_after_equalizer_is_not_expansion():
    g=game(3,goals=(2,1))
    events={'3':[event('10','1-0'),event('30','1-1'),event('75','2-1')]}
    report=timeline._team_metrics([g],'Casa',events)
    assert report['equalized_after_open']['value']==100
    assert report['extended_after_open']['value']==0


def test_no_matches_has_unavailable_percentage():
    result=timeline._team_metrics([], 'Casa',{})
    assert result['opened']['value'] is None
    assert result['first_half']['value'] is None


def test_simulations_are_deterministic_and_consistent():
    a=ml.simulations(1.8,1.2,n=7000)
    b=ml.simulations(1.8,1.2,n=7000)
    assert a==b
    assert a['home_win']+a['draw']+a['away_win']==pytest.approx(100,abs=.02)
    assert a['over_1_5_ft']>=a['over_2_5_ft']


def test_ml_fallback_below_training_minimum():
    assert ml.train_rows([])['status']=='fallback'


def test_score_predictions_have_valid_probabilities():
    distr=sofa._score_distribution(1.5,.8)
    normal={sc:p for sc,p in distr.items() if sc[0]<=4 and sc[1]<=4}
    assert sum(distr.values())==pytest.approx(1.0)
    assert min(normal,key=normal.get)[0]<=4
    assert max(normal,key=normal.get)[1]<=4


def test_general_results_snapshot():
    g1=game(1,goals=(2,0))
    g2=game(2,goals=(1,1))
    g3=game(3,goals=(0,3))
    result=sofa._results_snapshot([g1,g2,g3],'Casa')
    assert result['games']==3
    assert (result['wins'],result['draws'],result['losses'])==(1,1,1)
    assert result['goals_for']==3 and result['goals_against']==4
    assert result['clean_sheets']==1 and result['scored_games']==2
