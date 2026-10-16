from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from .config import settings
from .routers.catalog import router as catalog_router
from .routers.history import router as history_router
from .routers.management import router as management_router
from .routers.elo import router as elo_router
from .routers.clubs import router as clubs_router
from .routers.rankings import router as rankings_router
from .routers.scanner import router as scanner_router
from .routers.players import router as players_router
from .routers.backtesting import router as backtesting_router
from .routers.analysis_v3 import router as analysis_v3_router
from .routers.bet import router as bet_router

app=FastAPI(title='ELO Scout API',version='2.1.0')
app.add_middleware(GZipMiddleware, minimum_size=800)
app.add_middleware(CORSMiddleware,allow_origins=[settings.frontend_origin,'http://127.0.0.1:5173'],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
@app.get('/api/health')
def health():return {'status':'ok'}
app.include_router(catalog_router);app.include_router(history_router);app.include_router(elo_router);app.include_router(clubs_router);app.include_router(rankings_router);app.include_router(scanner_router);app.include_router(players_router)

app.include_router(management_router)

app.include_router(backtesting_router)

app.include_router(analysis_v3_router)

app.include_router(bet_router)
