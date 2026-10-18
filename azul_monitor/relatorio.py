"""Relatório em Markdown dos monitores, para ver os preços no GitHub."""

from datetime import date, datetime

from .db import Database


def _pts(v) -> str:
    return f"{v:,}".replace(",", ".") if v is not None else "—"


def _data(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def gerar_relatorio(db: Database) -> str:
    linhas = [
        "# Passagens Azul com pontos",
        "",
        f"Atualizado em {datetime.now():%d/%m/%Y %H:%M} (horário do servidor).",
    ]
    monitores = db.listar_monitores(somente_ativos=True)
    if not monitores:
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
