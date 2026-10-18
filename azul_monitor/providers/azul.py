"""Busca de passagens com pontos no site da Azul (voeazul.com.br).

A Azul não oferece API pública para resgate com pontos. Este provedor abre a
página de seleção de voos num navegador real (Playwright/Chromium), com a busca
em pontos, e lê as respostas JSON que o próprio site recebe do servidor.

O formato dessas respostas não é documentado e pode mudar sem aviso. Por isso o
parser abaixo é tolerante: percorre o JSON procurando valores em pontos e o
contexto do voo ao redor (número, horários, segmentos). Se a busca parar de
retornar ofertas, defina AZUL_DEBUG_DIR para salvar as respostas brutas e
ajustar `extrair_ofertas`.
"""

import json
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .base import ErroProvedor, Oferta

URL_BUSCA = (
    "https://www.voeazul.com.br/br/pt/home/selecao-voo"
    "?c[0].ds={origem}&c[0].std={data}&c[0].as={destino}"
    "&p[0].t=ADT&p[0].c=1&p[0].cp=false&f.dl=3&f.dr=3&cc=PTS"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# Respostas do site que podem conter a disponibilidade de voos.
PADRAO_URL_DISPONIBILIDADE = re.compile(r"availab|disponib|journey|search", re.I)

CHAVES_PONTOS = re.compile(r"^(points?|pontos|totalPoints|pointsAmount|loyaltyPoints|miles)$", re.I)
CHAVES_TAXAS = re.compile(r"^(taxes|tax|taxas|boardingTax|totalTaxes)$", re.I)
CHAVES_VOO = re.compile(r"^(flightNumber|numeroVoo|number)$", re.I)
CHAVES_PARTIDA = re.compile(r"^(std|departure|departureDate|departureTime|partida)$", re.I)
CHAVES_CHEGADA = re.compile(r"^(sta|arrival|arrivalDate|arrivalTime|chegada)$", re.I)
CHAVES_SEGMENTOS = re.compile(r"^(segments|segmentos|legs)$", re.I)


def _numero(valor: Any) -> float | None:
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str):
        limpo = valor.replace(".", "").replace(",", ".").strip()
        try:
            return float(limpo)
        except ValueError:
            return None
    if isinstance(valor, dict):
        for chave in ("amount", "value", "total", "valor"):
            if chave in valor:
                return _numero(valor[chave])
    return None


def _hora(valor: Any) -> str | None:
    if not isinstance(valor, str):
        return None
    m = re.search(r"(\d{2}):(\d{2})", valor)
    return f"{m.group(1)}:{m.group(2)}" if m else None


def _procurar(obj: Any, padrao: re.Pattern, profundidade: int = 3) -> Any:
    """Primeiro valor cuja chave casa com `padrao`, em busca rasa."""
    if profundidade < 0:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if padrao.match(k) and not isinstance(v, (dict, list)):
                return v
        for v in obj.values():
            achado = _procurar(v, padrao, profundidade - 1)
            if achado is not None:
                return achado
    elif isinstance(obj, list):
        for v in obj[:5]:
            achado = _procurar(v, padrao, profundidade - 1)
            if achado is not None:
                return achado
    return None


def _numeros_de_voo(jornada: dict) -> list[str]:
    numeros: list[str] = []

    def visitar(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if CHAVES_VOO.match(k) and isinstance(v, (str, int)) and str(v).strip().isdigit():
                    n = f"AD{str(v).strip()}"
                    if n not in numeros:
                        numeros.append(n)
                else:
                    visitar(v)
        elif isinstance(o, list):
            for v in o:
                visitar(v)

    visitar(jornada)
    return numeros


def _e_jornada(obj: dict) -> bool:
    return any(CHAVES_SEGMENTOS.match(k) for k in obj) or (
        any(CHAVES_PARTIDA.match(k) for k in obj) and any(CHAVES_CHEGADA.match(k) for k in obj)
    )


def extrair_ofertas(dados: Any, origem: str, destino: str, data: date) -> list[Oferta]:
    """Extrai ofertas em pontos de uma resposta JSON do site, sem depender de um esquema fixo."""
    melhores: dict[str, Oferta] = {}

    def visitar(o: Any, jornada: dict | None) -> None:
        if isinstance(o, dict):
            if _e_jornada(o):
                jornada = o
            for k, v in o.items():
                if CHAVES_PONTOS.match(k) and jornada is not None:
                    pontos = _numero(v)
                    if pontos and pontos >= 100:
                        registrar(int(pontos), o, jornada)
                visitar(v, jornada)
        elif isinstance(o, list):
            for v in o:
                visitar(v, jornada)

    def registrar(pontos: int, tarifa: dict, jornada: dict) -> None:
        numeros = _numeros_de_voo(jornada)
        if not numeros:
            return
        segmentos = next((v for k, v in jornada.items() if CHAVES_SEGMENTOS.match(k)), None)
        paradas = max(len(segmentos) - 1, 0) if isinstance(segmentos, list) else len(numeros) - 1
        taxas = _numero(_procurar(tarifa, CHAVES_TAXAS, 1))
        voo = "+".join(numeros)
        oferta = Oferta(
            data=data,
            origem=origem,
            destino=destino,
            voo=voo,
            pontos=pontos,
            partida=_hora(_procurar(jornada, CHAVES_PARTIDA)),
            chegada=_hora(_procurar(jornada, CHAVES_CHEGADA)),
            paradas=paradas,
            taxas=taxas,
        )
        if voo not in melhores or pontos < melhores[voo].pontos:
            melhores[voo] = oferta

    visitar(dados, None)
    return sorted(melhores.values(), key=lambda of: of.pontos)


def _titulo(pagina) -> str:
    try:
        return pagina.title()[:80]
    except Exception:
        return "?"


class ProvedorAzul:
    def __init__(self, headless: bool = True, debug_dir: str | None = None, timeout_s: int = 45):
        self._headless = headless
        self._debug_dir = Path(debug_dir) if debug_dir else None
        self._timeout_ms = timeout_s * 1000
        self._pw = None
        self._browser = None

    def _iniciar(self):
        if self._browser is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as e:
                raise ErroProvedor(
                    "Playwright não instalado. Rode: pip install playwright && playwright install chromium"
                ) from e
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self._headless)
        return self._browser

    def buscar(self, origem: str, destino: str, data: date) -> list[Oferta]:
        browser = self._iniciar()
        contexto = browser.new_context(
            locale="pt-BR", timezone_id="America/Sao_Paulo", user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
        )
        respostas: list[Any] = []
        requisicoes: list[str] = []  # para diagnóstico

        def ao_responder(resp):
            tipo = resp.headers.get("content-type") or ""
            if resp.request.resource_type in ("xhr", "fetch", "document"):
                requisicoes.append(f"{resp.status} {tipo.split(';')[0]} {resp.url[:200]}")
            if "json" not in tipo or not PADRAO_URL_DISPONIBILIDADE.search(resp.url):
                return
            try:
                respostas.append(resp.json())
            except Exception:
                pass

        pagina = None
        try:
            pagina = contexto.new_page()
            pagina.on("response", ao_responder)
            url = URL_BUSCA.format(origem=origem, destino=destino, data=data.strftime("%m/%d/%Y"))
            principal = pagina.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
            status = principal.status if principal else None
            if status and status >= 400:
                raise ErroProvedor(f"O site respondeu HTTP {status} ({_titulo(pagina)}): acesso bloqueado.")
            # Aguarda o carregamento dos voos (ou o tempo limite).
            limite = time.monotonic() + self._timeout_ms / 1000
            ofertas: list[Oferta] = []
            while time.monotonic() < limite:
                pagina.wait_for_timeout(2000)
                ofertas = [o for r in respostas for o in extrair_ofertas(r, origem, destino, data)]
                if ofertas:
                    pagina.wait_for_timeout(2000)  # deixa chegar respostas complementares
                    ofertas = [o for r in respostas for o in extrair_ofertas(r, origem, destino, data)]
                    break
            if not respostas:
                raise ErroProvedor(
                    f"O site não retornou dados de voos (página: {_titulo(pagina)!r}, "
                    f"{len(requisicoes)} requisições). Possível bloqueio anti-robô ou mudança no site."
                )
            return _deduplicar(ofertas)
        finally:
            self._salvar_debug(origem, destino, data, respostas, requisicoes, pagina)
            contexto.close()

    def _salvar_debug(self, origem, destino, data, respostas, requisicoes, pagina) -> None:
        if not self._debug_dir:
            return
        self._debug_dir.mkdir(parents=True, exist_ok=True)
        base = self._debug_dir / f"{origem}-{destino}-{data.isoformat()}-{datetime.now():%Y%m%d%H%M%S}"
        info = {"url_final": None, "titulo": None, "requisicoes": requisicoes, "respostas": respostas}
        if pagina is not None:
            try:
                info["url_final"], info["titulo"] = pagina.url, pagina.title()
                pagina.screenshot(path=f"{base}.png", full_page=False)
                Path(f"{base}.html").write_text(pagina.content()[:500_000], encoding="utf-8")
            except Exception:
                pass
        Path(f"{base}.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    def fechar(self) -> None:
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._pw:
            self._pw.stop()
            self._pw = None


def _deduplicar(ofertas: list[Oferta]) -> list[Oferta]:
    melhores: dict[str, Oferta] = {}
    for o in ofertas:
        if o.voo not in melhores or o.pontos < melhores[o.voo].pontos:
            melhores[o.voo] = o
    return sorted(melhores.values(), key=lambda o: o.pontos)
