"""Escala de plantões → viagens a monitorar.

Os dias de plantão vêm do calendário (link iCal/ICS), de uma lista fixa ou de um ciclo
(ex.: 5 dias de plantão a cada 10 dias). Dias seguidos formam um bloco; para cada bloco a
viagem de ida é no dia anterior ao primeiro plantão e a volta no dia seguinte ao último.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

FUSO_PADRAO = "America/Sao_Paulo"
# Evento com horário que termina antes disso no dia seguinte não conta esse dia como plantão
# (ex.: plantão de 24 h das 7h às 7h).
HORA_CORTE_FIM = 12


@dataclass
class Viagem:
    ida: date  # dia anterior ao primeiro plantão
    volta: date  # dia seguinte ao último plantão
    plantao_inicio: date
    plantao_fim: date


# --- dias de plantão ---


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


def _desdobrar(texto: str) -> list[str]:
    """Junta as linhas dobradas do formato iCal (continuação começa com espaço ou tab)."""
    linhas: list[str] = []
    for linha in texto.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if linha[:1] in (" ", "\t") and linhas:
            linhas[-1] += linha[1:]
        elif linha:
            linhas.append(linha)
    return linhas


def _propriedade(linha: str) -> tuple[str, dict[str, str], str]:
    cabecalho, _, valor = linha.partition(":")
    nome, *params = cabecalho.split(";")
    parametros = {}
    for p in params:
        k, _, v = p.partition("=")
        parametros[k.upper()] = v.strip('"')
    return nome.upper(), parametros, valor


def _ler_data_ics(valor: str, params: dict[str, str], fuso: ZoneInfo) -> date | datetime:
    valor = valor.strip()
    if params.get("VALUE") == "DATE" or len(valor) == 8:
        return datetime.strptime(valor[:8], "%Y%m%d").date()
    if valor.endswith("Z"):
        return datetime.strptime(valor, "%Y%m%dT%H%M%SZ").replace(tzinfo=ZoneInfo("UTC")).astimezone(fuso)
    dt = datetime.strptime(valor[:15], "%Y%m%dT%H%M%S")
    try:
        origem = ZoneInfo(params["TZID"]) if "TZID" in params else fuso
    except Exception:
        origem = fuso
    return dt.replace(tzinfo=origem).astimezone(fuso)


def _dias_do_evento(inicio: date | datetime, fim: date | datetime | None) -> list[date]:
    if isinstance(inicio, datetime):
        primeiro = inicio.date()
        if fim is None:
            return [primeiro]
        assert isinstance(fim, datetime)
        ultimo = fim.date()
        if ultimo > primeiro and fim.hour < HORA_CORTE_FIM:
            ultimo -= timedelta(days=1)
    else:
        primeiro = inicio
        # Em eventos de dia inteiro o fim é exclusivo.
        ultimo = (fim - timedelta(days=1)) if isinstance(fim, date) and fim > inicio else inicio
    return [primeiro + timedelta(days=i) for i in range((ultimo - primeiro).days + 1)]


def _ocorrencias(inicio, regra: str, excecoes: set[date], ate: date) -> list:
    """Expande uma RRULE simples (DAILY/WEEKLY/MONTHLY com INTERVAL, COUNT, UNTIL e BYDAY semanal)."""
    partes = dict(p.split("=", 1) for p in regra.split(";") if "=" in p)
    freq = partes.get("FREQ", "").upper()
    intervalo = int(partes.get("INTERVAL", 1))
    contagem = int(partes["COUNT"]) if "COUNT" in partes else None
    limite = ate
    if "UNTIL" in partes:
        limite = min(limite, datetime.strptime(partes["UNTIL"][:8], "%Y%m%d").date())
    dia_base = inicio.date() if isinstance(inicio, datetime) else inicio
    dias_semana = None
    if freq == "WEEKLY" and "BYDAY" in partes:
        nomes = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
        dias_semana = {nomes.index(d[-2:]) for d in partes["BYDAY"].split(",") if d[-2:] in nomes}

    datas: list[date] = []
    if freq == "DAILY":
        d = dia_base
        while d <= limite and (contagem is None or len(datas) < contagem):
            datas.append(d)
            d += timedelta(days=intervalo)
    elif freq == "WEEKLY":
        semana = dia_base - timedelta(days=dia_base.weekday())
        while semana <= limite and (contagem is None or len(datas) < contagem):
            for i in sorted(dias_semana or {dia_base.weekday()}):
                d = semana + timedelta(days=i)
                if dia_base <= d <= limite and (contagem is None or len(datas) < contagem):
                    datas.append(d)
            semana += timedelta(weeks=intervalo)
    elif freq == "MONTHLY":
        n = 0
        while contagem is None or len(datas) < contagem:
            mes = dia_base.month - 1 + n * intervalo
            ano, mes = dia_base.year + mes // 12, mes % 12 + 1
            n += 1
            try:
                d = dia_base.replace(year=ano, month=mes)
            except ValueError:
                continue
            if d > limite:
                break
            datas.append(d)
    else:
        return [inicio]

    deslocamento = [d - dia_base for d in datas if d not in excecoes]
    return [inicio + delta for delta in deslocamento]


def plantoes_do_ics(
    texto: str,
    palavra_chave: str = "plantão",
    hoje: date | None = None,
    horizonte_dias: int = 120,
    fuso: str = FUSO_PADRAO,
) -> set[date]:
    """Dias de plantão marcados no calendário (eventos cujo título contém `palavra_chave`)."""
    tz = ZoneInfo(fuso)
    hoje = hoje or date.today()
    ate = hoje + timedelta(days=horizonte_dias)
    chave = _sem_acento(palavra_chave)
    dias: set[date] = set()
    evento: dict | None = None
    for linha in _desdobrar(texto):
        if linha.upper() == "BEGIN:VEVENT":
            evento = {"excecoes": set()}
            continue
        if evento is None:
            continue
        if linha.upper() == "END:VEVENT":
            titulo = evento.get("titulo", "")
            if "inicio" in evento and chave in _sem_acento(titulo) and evento.get("status") != "CANCELLED":
                inicio, fim = evento["inicio"], evento.get("fim")
                duracao = (fim - inicio) if fim is not None else None
                ocorrencias = (
                    _ocorrencias(inicio, evento["regra"], evento["excecoes"], ate)
                    if "regra" in evento else [inicio]
                )
                for oc in ocorrencias:
                    dias.update(_dias_do_evento(oc, oc + duracao if duracao is not None else None))
            evento = None
            continue
        nome, params, valor = _propriedade(linha)
        if nome == "SUMMARY":
            evento["titulo"] = valor.replace("\\,", ",").replace("\\;", ";")
        elif nome == "DTSTART":
            evento["inicio"] = _ler_data_ics(valor, params, tz)
        elif nome == "DTEND":
            evento["fim"] = _ler_data_ics(valor, params, tz)
        elif nome == "RRULE":
            evento["regra"] = valor
        elif nome == "EXDATE":
            for v in valor.split(","):
                d = _ler_data_ics(v, params, tz)
                evento["excecoes"].add(d.date() if isinstance(d, datetime) else d)
        elif nome == "STATUS":
            evento["status"] = valor.strip().upper()
    return {d for d in dias if hoje - timedelta(days=30) <= d <= ate}


def baixar_ics(url: str) -> str:
    import httpx

    url = re.sub(r"^webcal://", "https://", url.strip(), flags=re.I)
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def plantoes_do_ciclo(primeiro_plantao: date, dias_plantao: int, repetir_a_cada_dias: int, ate: date) -> set[date]:
    dias: set[date] = set()
    inicio = primeiro_plantao
    while inicio <= ate:
        dias.update(inicio + timedelta(days=i) for i in range(dias_plantao))
        inicio += timedelta(days=repetir_a_cada_dias)
    return dias


# --- viagens ---


def viagens_dos_plantoes(dias: set[date]) -> list[Viagem]:
    """Agrupa os dias de plantão em blocos seguidos e calcula a ida e a volta de cada um."""
    viagens: list[Viagem] = []
    for d in sorted(dias):
        if viagens and d == viagens[-1].plantao_fim + timedelta(days=1):
            v = viagens[-1]
            v.plantao_fim, v.volta = d, d + timedelta(days=1)
        else:
            viagens.append(Viagem(d - timedelta(days=1), d + timedelta(days=1), d, d))
    return viagens


def ler_escala(caminho: Path) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8"))


def calcular_viagens(escala: dict, ics: str | None = None, hoje: date | None = None) -> list[Viagem]:
    """Próximas viagens (volta a partir de hoje), até `viagens_a_frente` ou `horizonte_dias`."""
    hoje = hoje or date.today()
    horizonte = int(escala.get("horizonte_dias", 60))
    ate = hoje + timedelta(days=horizonte)
    dias: set[date] = set()
    if ics:
        dias |= plantoes_do_ics(ics, escala.get("palavra_chave", "plantão"), hoje, horizonte + 30)
    for bloco in escala.get("plantoes", []):
        inicio = date.fromisoformat(bloco["inicio"])
        fim = date.fromisoformat(bloco.get("fim", bloco["inicio"]))
        dias.update(inicio + timedelta(days=i) for i in range((fim - inicio).days + 1))
    ciclo = escala.get("ciclo")
    if ciclo and not ics:
        dias |= plantoes_do_ciclo(
            date.fromisoformat(ciclo["primeiro_plantao"]),
            int(ciclo.get("dias_plantao", 5)),
            int(ciclo.get("repetir_a_cada_dias", 10)),
            ate,
        )
    viagens = [v for v in viagens_dos_plantoes(dias) if v.volta >= hoje and v.ida <= ate]
    return viagens[: int(escala.get("viagens_a_frente", 4))]


def rotas_das_viagens(escala: dict, viagens: list[Viagem], hoje: date | None = None) -> list[dict]:
    """Rotas no formato de monitores.json: ida casa→trabalho e volta trabalho→casa."""
    hoje = hoje or date.today()
    casa, trabalho = escala["origem"].upper(), escala["destino"].upper()
    regras = {
        "max_pontos": escala.get("max_pontos"),
        "desconto_minimo_pct": escala.get("desconto_minimo_pct", 20),
        "somente_diretos": bool(escala.get("somente_diretos", False)),
        "escala": True,
    }
    rotas = []
    for v in viagens:
        for origem, destino, dia in ((casa, trabalho, v.ida), (trabalho, casa, v.volta)):
            if dia >= hoje:
                rotas.append({"origem": origem, "destino": destino, "data_inicio": dia.isoformat(),
                              "data_fim": dia.isoformat(), **regras})
    return rotas


def atualizar_monitores(caminho_monitores: Path, rotas_escala: list[dict]) -> list[dict]:
    """Troca as rotas geradas pela escala em monitores.json, mantendo as rotas cadastradas à mão."""
    atuais = json.loads(caminho_monitores.read_text(encoding="utf-8")) if caminho_monitores.exists() else []
    manuais = [r for r in atuais if not r.get("escala")]
    todas = manuais + rotas_escala
    caminho_monitores.write_text(json.dumps(todas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return todas
