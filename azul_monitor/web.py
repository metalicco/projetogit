"""Interface web (FastAPI) e agendador das verificações."""

import logging
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .alertas import Notificador
from .config import Config, carregar_config
from .db import Database
from .monitor import MAX_DIAS_POR_MONITOR, Verificador
from .providers import criar_provedor

log = logging.getLogger(__name__)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters["pts"] = lambda v: f"{v:,}".replace(",", ".") if v is not None else "—"
templates.env.filters["br"] = lambda d: d.strftime("%d/%m/%Y") if d else "—"


def _data_hora(valor) -> str:
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m %H:%M")
    if isinstance(valor, str) and len(valor) >= 16:
        return f"{valor[8:10]}/{valor[5:7]} {valor[11:16]}"
    return valor or "—"


templates.env.filters["brdt"] = _data_hora


def criar_app(config: Config | None = None, iniciar_agendador: bool = True) -> FastAPI:
    config = config or carregar_config()
    db = Database(config.db_path)
    notificador = Notificador(config)
    verificador = Verificador(db, criar_provedor(config), notificador, config)
    agendador = BackgroundScheduler()

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        if iniciar_agendador:
            agendador.add_job(
                verificador.verificar_pendentes, "interval", minutes=1, max_instances=1, coalesce=True
            )
            agendador.start()
        yield
        if agendador.running:
            agendador.shutdown(wait=False)
        verificador.provedor.fechar()

    app = FastAPI(title="Monitor de passagens Azul com pontos", lifespan=ciclo_de_vida)
    app.state.db = db
    app.state.verificador = verificador

    @app.get("/", response_class=HTMLResponse)
    def inicio(request: Request, erro: str | None = None):
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "monitores": db.listar_monitores(),
                "alertas": db.listar_alertas(limite=20),
                "canais": notificador.canais(),
                "provedor": config.provedor,
                "hoje": date.today().isoformat(),
                "erro": erro,
                "max_dias": MAX_DIAS_POR_MONITOR,
            },
        )

    @app.post("/monitores")
    def criar(
        origem: str = Form(...),
        destino: str = Form(...),
        data_inicio: date = Form(...),
        data_fim: date = Form(...),
        max_pontos: str = Form(""),
        desconto_minimo_pct: float = Form(20),
        somente_diretos: bool = Form(False),
        intervalo_minutos: int = Form(180),
    ):
        origem, destino = origem.strip().upper(), destino.strip().upper()
        problema = None
        if len(origem) != 3 or len(destino) != 3 or not (origem + destino).isalpha():
            problema = "Use códigos de aeroporto com 3 letras (ex.: VCP, REC)."
        elif origem == destino:
            problema = "Origem e destino devem ser diferentes."
        elif data_fim < data_inicio:
            problema = "A data final deve ser igual ou posterior à inicial."
        elif data_fim < date.today():
            problema = "O período escolhido já passou."
        elif (data_fim - max(data_inicio, date.today())).days + 1 > MAX_DIAS_POR_MONITOR:
            problema = f"Escolha no máximo {MAX_DIAS_POR_MONITOR} dias por monitor."
        elif intervalo_minutos < 30:
            problema = "O intervalo mínimo entre verificações é de 30 minutos."
        if problema:
            return RedirectResponse(f"/?erro={quote(problema)}", status_code=303)
        monitor_id = db.criar_monitor(
            origem,
            destino,
            data_inicio,
            data_fim,
            max_pontos=int(max_pontos.replace(".", "")) if max_pontos.strip() else None,
            desconto_minimo_pct=desconto_minimo_pct,
            somente_diretos=somente_diretos,
            intervalo_minutos=intervalo_minutos,
        )
        _verificar_em_segundo_plano(monitor_id)
        return RedirectResponse(f"/monitores/{monitor_id}", status_code=303)

    @app.get("/monitores/{monitor_id}", response_class=HTMLResponse)
    def detalhe(request: Request, monitor_id: int):
        monitor = db.obter_monitor(monitor_id)
        if not monitor:
            raise HTTPException(404, "Monitor não encontrado")
        return templates.TemplateResponse(
            request,
            "monitor.html",
            {
                "m": monitor,
                "melhores": db.melhores_por_data(monitor_id),
                "historico": db.historico_minimos(monitor_id),
                "alertas": db.listar_alertas(monitor_id),
            },
        )

    @app.post("/monitores/{monitor_id}/verificar")
    def verificar_agora(monitor_id: int):
        _verificar_em_segundo_plano(monitor_id)
        return RedirectResponse(f"/monitores/{monitor_id}", status_code=303)

    @app.post("/monitores/{monitor_id}/alternar")
    def alternar(monitor_id: int):
        db.alternar_monitor(monitor_id)
        return RedirectResponse("/", status_code=303)

    @app.post("/monitores/{monitor_id}/excluir")
    def excluir(monitor_id: int):
        db.excluir_monitor(monitor_id)
        return RedirectResponse("/", status_code=303)

    @app.post("/testar-alerta")
    def testar_alerta():
        notificador.enviar("Teste do monitor Azul", "Se você recebeu esta mensagem, os alertas funcionam.")
        return RedirectResponse("/", status_code=303)

    def _verificar_em_segundo_plano(monitor_id: int) -> None:
        def tarefa():
            monitor = db.obter_monitor(monitor_id)
            if monitor:
                try:
                    verificador.verificar(monitor)
                except Exception:
                    log.exception("Falha ao verificar monitor %s", monitor_id)

        threading.Thread(target=tarefa, daemon=True).start()

    return app
