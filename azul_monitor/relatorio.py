"""Relatório em Markdown dos monitores, para ver os preços no GitHub."""

import json
from datetime import date, datetime
from pathlib import Path

from .db import Database, Monitor

DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def _pts(v) -> str:
    return f"{v:,}".replace(",", ".") if v is not None else "—"


def _data(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def _dia(d: date) -> str:
    return f"{DIAS_SEMANA[d.weekday()]} {d:%d/%m}"


def _trecho(db: Database, monitores: list[Monitor], origem: str, destino: str, dia: date) -> tuple[str, Monitor | None]:
    m = next((m for m in monitores if m.origem == origem and m.destino == destino
              and m.data_inicio == dia == m.data_fim), None)
    if m is None:
        return ("já passou" if dia < date.today() else "não monitorado"), None
    melhores = db.melhores_por_data(m.id)
    if not melhores:
        return ("⚠️ sem resposta do site" if m.ultimo_erro else "aguardando 1ª busca"), m
    p = melhores[0]
    horario = f" {p['partida']}" if p["partida"] else ""
    return f"**{_pts(p['pontos'])}** pts · {p['voo']}{horario}", m


def _secao_viagens(db: Database, monitores: list[Monitor], viagens: dict) -> tuple[list[str], set[int]]:
    casa, trabalho = viagens["origem"], viagens["destino"]
    linhas = ["", f"## Próximas viagens {casa} ⇄ {trabalho}", "",
              f"Plantões lidos do {viagens.get('fonte', 'escala')}.", "",
              f"| Plantão | Ida {casa}→{trabalho} | Melhor ida | Volta {trabalho}→{casa} | Melhor volta |",
              "|---|---|---|---|---|"]
    usados: set[int] = set()
    erros: list[str] = []
    for v in viagens["viagens"]:
        ida, volta = date.fromisoformat(v["ida"]), date.fromisoformat(v["volta"])
        p_ini, p_fim = date.fromisoformat(v["plantao_inicio"]), date.fromisoformat(v["plantao_fim"])
        preco_ida, m_ida = _trecho(db, monitores, casa, trabalho, ida)
        preco_volta, m_volta = _trecho(db, monitores, trabalho, casa, volta)
        for m in (m_ida, m_volta):
            if m:
                usados.add(m.id)
                if m.ultimo_erro and m.ultimo_erro not in erros:
                    erros.append(m.ultimo_erro)
        linhas.append(f"| {p_ini:%d/%m}–{p_fim:%d/%m} | {_dia(ida)} | {preco_ida} | {_dia(volta)} | {preco_volta} |")
    if not viagens["viagens"]:
        linhas.append("| — | — | — | — | — |")
    if erros:
        linhas += ["", f"> ⚠️ {erros[0]}"]
    return linhas, usados


def gerar_relatorio(db: Database, arquivo_viagens: Path | None = None) -> str:
    linhas = [
        "# Passagens Azul com pontos",
        "",
        f"Atualizado em {datetime.now():%d/%m/%Y %H:%M} (horário do servidor).",
    ]
    monitores = db.listar_monitores(somente_ativos=True)
    if arquivo_viagens and arquivo_viagens.exists():
        secao, usados = _secao_viagens(db, monitores, json.loads(arquivo_viagens.read_text(encoding="utf-8")))
        linhas += secao
        monitores = [m for m in monitores if m.id not in usados]
    elif not monitores:
        linhas += ["", "Nenhum monitor ativo. Cadastre as rotas em `monitores.json`."]
    for m in monitores:
        linhas += ["", f"## {m.origem} → {m.destino}", ""]
        regras = [f"{m.data_inicio:%d/%m/%Y} a {m.data_fim:%d/%m/%Y}"]
        if m.max_pontos:
            regras.append(f"alerta até {_pts(m.max_pontos)} pontos")
        if m.desconto_minimo_pct:
            regras.append(f"ou {m.desconto_minimo_pct:.0f}% abaixo da média")
        if m.somente_diretos:
            regras.append("só diretos")
        linhas.append(" · ".join(regras))
        if m.ultimo_erro:
            linhas += ["", f"> ⚠️ {m.ultimo_erro}"]
        melhores = db.melhores_por_data(m.id)
        if not melhores:
            linhas += ["", "Ainda sem preços."]
            continue
        menor = min(p["pontos"] for p in melhores)
        linhas += [
            "",
            "| Data | Voo | Horário | Paradas | Pontos | Taxas | Menor já visto |",
            "|---|---|---|---|--:|--:|--:|",
        ]
        for p in melhores:
            pontos = f"**{_pts(p['pontos'])}**" + (" 🏆" if p["pontos"] == menor else "")
            taxas = f"R$ {p['taxas']:.2f}" if p["taxas"] else "—"
            paradas = "direto" if p["paradas"] == 0 else p["paradas"]
            linhas.append(
                f"| {_data(p['data_voo'])} | {p['voo']} | {p['partida'] or '—'} → {p['chegada'] or '—'} "
                f"| {paradas} | {pontos} | {taxas} | {_pts(p['minimo_historico'])} |"
            )
    alertas = db.listar_alertas(limite=15)
    if alertas:
        linhas += ["", "## Alertas recentes", "", "| Quando | Rota | Data do voo | Voo | Pontos | Motivo |",
                   "|---|---|---|---|--:|---|"]
        for a in alertas:
            quando = datetime.fromisoformat(a["criado_em"]).strftime("%d/%m %H:%M")
            linhas.append(
                f"| {quando} | {a['origem']} → {a['destino']} | {_data(a['data_voo'])} | {a['voo']} "
                f"| {_pts(a['pontos'])} | {a['motivo']} |"
            )
    return "\n".join(linhas) + "\n"
