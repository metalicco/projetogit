"""Verifica os monitores: busca os preços de cada data, salva o histórico e dispara alertas."""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .alertas import Notificador
from .config import Config
from .db import Database, Monitor
from .providers import ErroProvedor, Oferta, Provedor

log = logging.getLogger(__name__)

MAX_DIAS_POR_MONITOR = 60
# Se as primeiras buscas falharem seguidas, o site provavelmente está bloqueando: desiste cedo.
MAX_FALHAS_SEGUIDAS_INICIAIS = 2


@dataclass
class Avaliacao:
    alertar: bool
    motivo: str = ""


def avaliar(
    oferta: Oferta,
    monitor: Monitor,
    media_historica: float | None,
    ultimo_alerta_pontos: int | None,
) -> Avaliacao:
    """Decide se a melhor oferta de uma data merece alerta.

    É um bom preço quando fica abaixo do limite de pontos definido no monitor, ou
    quando está pelo menos `desconto_minimo_pct` abaixo da média histórica da rota.
    Para não repetir alertas, só avisa de novo se o preço cair abaixo do último alertado.
    """
    motivos = []
    if monitor.max_pontos and oferta.pontos <= monitor.max_pontos:
        motivos.append(f"abaixo do seu limite de {monitor.max_pontos:,} pontos")
    if media_historica and monitor.desconto_minimo_pct > 0:
        corte = media_historica * (1 - monitor.desconto_minimo_pct / 100)
        if oferta.pontos <= corte:
            desconto = (1 - oferta.pontos / media_historica) * 100
            motivos.append(f"{desconto:.0f}% abaixo da média ({media_historica:,.0f} pontos)")
    if not motivos:
        return Avaliacao(False)
    if ultimo_alerta_pontos is not None and oferta.pontos >= ultimo_alerta_pontos:
        return Avaliacao(False)
    return Avaliacao(True, "; ".join(motivos).replace(",", "."))


def datas_do_monitor(monitor: Monitor, hoje: date | None = None) -> list[date]:
    hoje = hoje or date.today()
    inicio = max(monitor.data_inicio, hoje)
    dias = (monitor.data_fim - inicio).days + 1
    return [inicio + timedelta(days=i) for i in range(min(max(dias, 0), MAX_DIAS_POR_MONITOR))]


def formatar_alerta(monitor: Monitor, oferta: Oferta, motivo: str) -> tuple[str, str]:
    pontos = f"{oferta.pontos:,}".replace(",", ".")
    titulo = f"Azul {monitor.origem}→{monitor.destino} em {oferta.data:%d/%m/%Y}: {pontos} pontos"
    linhas = [
        f"Voo {oferta.voo}"
        + (f" ({oferta.partida}–{oferta.chegada})" if oferta.partida else "")
        + (" direto" if oferta.paradas == 0 else f" com {oferta.paradas} parada(s)"),
        f"Preço: {pontos} pontos" + (f" + R$ {oferta.taxas:.2f} de taxas" if oferta.taxas else ""),
        f"Motivo: {motivo}",
        "Reserve em https://www.voeazul.com.br",
    ]
    return titulo, "\n".join(linhas)


class Verificador:
    def __init__(self, db: Database, provedor: Provedor, notificador: Notificador, config: Config):
        self.db = db
        self.provedor = provedor
        self.notificador = notificador
        self.config = config
        # O navegador do Playwright não pode ser usado por duas threads ao mesmo tempo.
        self._lock = threading.Lock()

    def verificar(self, monitor: Monitor) -> int:
        """Verifica um monitor e retorna o número de alertas emitidos."""
        with self._lock:
            return self._verificar(monitor)

    def _verificar(self, monitor: Monitor) -> int:
        coletado_em = datetime.now().replace(microsecond=0)
        media = self.db.media_historica(monitor.id, coletado_em)
        alertas = 0
        erros = []
        sucessos = 0
        datas = datas_do_monitor(monitor)
        for i, dia in enumerate(datas):
            if not sucessos and len(erros) >= MAX_FALHAS_SEGUIDAS_INICIAIS:
                erros.append(f"As primeiras {len(erros)} buscas falharam; as outras datas não foram tentadas.")
                break
            if i and self.config.pausa_entre_buscas:
                time.sleep(self.config.pausa_entre_buscas)
            try:
                ofertas = self.provedor.buscar(monitor.origem, monitor.destino, dia)
            except ErroProvedor as e:
                erros.append(f"{dia:%d/%m}: {e}")
                continue
            except Exception as e:  # erros de rede/navegador não devem parar o monitor
                log.exception("Erro ao buscar %s em %s", monitor.rota, dia)
                erros.append(f"{dia:%d/%m}: {e.__class__.__name__}: {e}")
                continue
            sucessos += 1
            if monitor.somente_diretos:
                ofertas = [o for o in ofertas if o.paradas == 0]
            for oferta in ofertas:
                self.db.salvar_preco(monitor.id, oferta, coletado_em)
            if not ofertas:
                continue
            melhor = min(ofertas, key=lambda o: o.pontos)
            ultimo = self.db.ultimo_alerta(monitor.id, dia)
            avaliacao = avaliar(melhor, monitor, media, ultimo["pontos"] if ultimo else None)
            if avaliacao.alertar:
                self.db.salvar_alerta(monitor.id, melhor, avaliacao.motivo)
                self.notificador.enviar(*formatar_alerta(monitor, melhor, avaliacao.motivo))
                alertas += 1
        erro = "; ".join(erros) if erros else None
        if not datas:
            erro = "Todas as datas do monitor já passaram."
        self.db.registrar_verificacao(monitor.id, erro)
        log.info("%s verificado: %d data(s), %d alerta(s)", monitor.rota, len(datas), alertas)
        return alertas

    def verificar_pendentes(self) -> None:
        """Verifica os monitores ativos cujo intervalo já venceu."""
        agora = datetime.now()
        for monitor in self.db.listar_monitores(somente_ativos=True):
            vence = (monitor.ultima_verificacao or datetime.min) + timedelta(
                minutes=monitor.intervalo_minutos
            )
            if vence <= agora:
                self.verificar(monitor)
