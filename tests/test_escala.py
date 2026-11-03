import json
from datetime import date

from azul_monitor.escala import (
    atualizar_monitores,
    calcular_viagens,
    plantoes_do_ics,
    rotas_das_viagens,
    viagens_dos_plantoes,
)

HOJE = date(2026, 11, 3)
ESCALA = {
    "origem": "rec",
    "destino": "jdo",
    "ciclo": {"primeiro_plantao": "2026-11-05", "dias_plantao": 5, "repetir_a_cada_dias": 10},
    "viagens_a_frente": 3,
}


def d(dia, mes=11):
    return date(2026, mes, dia)


def test_ida_um_dia_antes_e_volta_um_dia_depois():
    viagens = viagens_dos_plantoes({d(5), d(6), d(7), d(8), d(9), d(15), d(16)})
    assert [(v.ida, v.volta) for v in viagens] == [(d(4), d(10)), (d(14), d(17))]


def test_ciclo_de_10_dias():
    viagens = calcular_viagens(ESCALA, hoje=HOJE)
    assert [(v.ida, v.volta) for v in viagens] == [(d(4), d(10)), (d(14), d(20)), (d(24), d(30))]


def test_rotas_ida_e_volta():
    viagens = calcular_viagens(ESCALA, hoje=HOJE)[:1]
    rotas = rotas_das_viagens(ESCALA, viagens, hoje=HOJE)
    assert [(r["origem"], r["destino"], r["data_inicio"]) for r in rotas] == [
        ("REC", "JDO", "2026-11-04"),
        ("JDO", "REC", "2026-11-10"),
    ]
    assert all(r["escala"] and r["data_fim"] == r["data_inicio"] for r in rotas)


def test_durante_o_plantao_so_monitora_a_volta():
    viagens = calcular_viagens(ESCALA, hoje=d(7))
    rotas = rotas_das_viagens(ESCALA, viagens[:1], hoje=d(7))
    assert [(r["origem"], r["data_inicio"]) for r in rotas] == [("JDO", "2026-11-10")]


def test_atualizar_monitores_mantem_rotas_manuais(tmp_path):
    arquivo = tmp_path / "monitores.json"
    manual = {"origem": "VCP", "destino": "REC", "data_inicio": "2026-12-15", "data_fim": "2026-12-22"}
    antiga = {"origem": "REC", "destino": "JDO", "data_inicio": "2026-10-25", "data_fim": "2026-10-25",
              "escala": True}
    arquivo.write_text(json.dumps([manual, antiga]))
    nova = {"origem": "REC", "destino": "JDO", "data_inicio": "2026-11-04", "data_fim": "2026-11-04",
            "escala": True}
    atualizar_monitores(arquivo, [nova])
    assert json.loads(arquivo.read_text()) == [manual, nova]


ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261105
DTEND;VALUE=DATE:20261110
SUMMARY:Plantao Juazeiro
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261112
DTEND;VALUE=DATE:20261113
SUMMARY:Aniversário
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/Fortaleza:20261115T070000
DTEND;TZID=America/Fortaleza:20261116T070000
RRULE:FREQ=DAILY;COUNT=5
SUMMARY:PLANTÃO
 UTI
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261125
DTEND;VALUE=DATE:20261130
SUMMARY:Plantão
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""


def test_plantoes_do_calendario():
    dias = plantoes_do_ics(ICS, "plantão", hoje=HOJE)
    assert dias == {d(5), d(6), d(7), d(8), d(9), d(15), d(16), d(17), d(18), d(19)}


def test_calendario_substitui_o_ciclo():
    ics = ICS.replace("20261115T070000", "20261116T070000").replace("20261116T070000\nRRULE", "20261117T070000\nRRULE")
    viagens = calcular_viagens(ESCALA, ics=ics, hoje=HOJE)
    assert [(v.ida, v.volta) for v in viagens] == [(d(4), d(10)), (d(15), d(21))]


def test_recorrencia_a_cada_10_dias_com_excecao():
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261105
DTEND;VALUE=DATE:20261110
RRULE:FREQ=DAILY;INTERVAL=10
EXDATE;VALUE=DATE:20261115
SUMMARY:plantão
END:VEVENT
END:VCALENDAR"""
    viagens = viagens_dos_plantoes(plantoes_do_ics(ics, hoje=HOJE, horizonte_dias=30))
    assert [(v.ida, v.volta) for v in viagens] == [(d(4), d(10)), (d(24), d(30))]
