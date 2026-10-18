from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from azul_monitor.config import Config
from azul_monitor.db import Database
from azul_monitor.monitor import Verificador, avaliar, datas_do_monitor
from azul_monitor.providers.azul import extrair_ofertas
from azul_monitor.providers.base import Oferta
from azul_monitor.web import criar_app

HOJE = date.today()


def config(tmp_path, **extra) -> Config:
    base = dict(
        db_path=str(tmp_path / "t.db"), provedor="simulado", headless=True, debug_dir=None,
        pausa_entre_buscas=0, telegram_token=None, telegram_chat_id=None, smtp_host=None,
        smtp_port=587, smtp_user=None, smtp_password=None, email_destino=None, ntfy_topic=None,
    )
    base.update(extra)
    return Config(**base)


class ProvedorFixo:
    def __init__(self, precos: dict[date, list[int]]):
        self.precos = precos

    def buscar(self, origem, destino, data):
        return [
            Oferta(data, origem, destino, f"AD{1000 + i}", p, "08:00", "10:00", paradas=i % 2)
            for i, p in enumerate(self.precos.get(data, []))
        ]

    def fechar(self):
        pass


class NotificadorFalso:
    def __init__(self):
        self.enviados = []

    def enviar(self, titulo, mensagem):
        self.enviados.append((titulo, mensagem))

    def canais(self):
        return ["console"]


@pytest.fixture
def db(tmp_path):
    return Database(str(tmp_path / "t.db"))


def novo_monitor(db, **kw):
    params = dict(origem="vcp", destino="rec", data_inicio=HOJE, data_fim=HOJE + timedelta(days=1))
    params.update(kw)
    return db.obter_monitor(db.criar_monitor(**params))


def test_avaliar_limite_de_pontos(db):
    m = novo_monitor(db, max_pontos=15000, desconto_minimo_pct=0)
    of = Oferta(HOJE, "VCP", "REC", "AD1", 14000)
    assert avaliar(of, m, None, None).alertar
    assert not avaliar(Oferta(HOJE, "VCP", "REC", "AD1", 16000), m, None, None).alertar
    # Não repete alerta para o mesmo preço; repete se cair mais.
    assert not avaliar(of, m, None, 14000).alertar
    assert avaliar(Oferta(HOJE, "VCP", "REC", "AD1", 12000), m, None, 14000).alertar


def test_avaliar_desconto_sobre_media(db):
    m = novo_monitor(db, desconto_minimo_pct=20)
    assert avaliar(Oferta(HOJE, "VCP", "REC", "AD1", 7900), m, 10000, None).alertar
    assert not avaliar(Oferta(HOJE, "VCP", "REC", "AD1", 8500), m, 10000, None).alertar
    assert not avaliar(Oferta(HOJE, "VCP", "REC", "AD1", 5000), m, None, None).alertar


def test_datas_ignoram_passado_e_limitam_quantidade(db):
    m = novo_monitor(db, data_inicio=HOJE - timedelta(days=5), data_fim=HOJE + timedelta(days=200))
    datas = datas_do_monitor(m)
    assert datas[0] == HOJE and len(datas) == 60


def test_verificador_salva_precos_e_alerta(tmp_path, db):
    d1, d2 = HOJE, HOJE + timedelta(days=1)
    m = novo_monitor(db, max_pontos=10000)
    notif = NotificadorFalso()
    v = Verificador(db, ProvedorFixo({d1: [12000, 9000], d2: [20000]}), notif, config(tmp_path))

    assert v.verificar(m) == 1
    assert "9.000 pontos" in notif.enviados[0][0]
    melhores = db.melhores_por_data(m.id)
    assert [(r["data_voo"], r["pontos"]) for r in melhores] == [(d1.isoformat(), 9000), (d2.isoformat(), 20000)]

    # Mesma coleta de novo: sem alerta repetido.
    assert v.verificar(m) == 0
    assert db.obter_monitor(m.id).ultima_verificacao is not None


def test_somente_diretos(tmp_path, db):
    m = novo_monitor(db, max_pontos=10000, somente_diretos=True)
    # O segundo voo (paradas=1) é o mais barato, mas deve ser ignorado.
    v = Verificador(db, ProvedorFixo({HOJE: [11000, 5000]}), NotificadorFalso(), config(tmp_path))
    assert v.verificar(m) == 0
    assert db.melhores_por_data(m.id)[0]["pontos"] == 11000


def test_media_historica(db):
    m = novo_monitor(db)
    t1, t2 = datetime(2026, 1, 1, 10), datetime(2026, 1, 1, 13)
    db.salvar_preco(m.id, Oferta(HOJE, "VCP", "REC", "AD1", 10000), t1)
    db.salvar_preco(m.id, Oferta(HOJE, "VCP", "REC", "AD2", 30000), t1)
    db.salvar_preco(m.id, Oferta(HOJE, "VCP", "REC", "AD1", 20000), t2)
    assert db.media_historica(m.id, t2) == 10000
    assert db.media_historica(m.id, datetime(2026, 1, 2)) == 15000


def test_extrair_ofertas_formato_generico():
    resposta = {
        "data": {
            "trips": [{
                "journeys": [
                    {
                        "identifier": {"std": "2026-12-20T06:10:00", "sta": "2026-12-20T09:05:00"},
                        "segments": [{"identifier": {"carrierCode": "AD", "flightNumber": "4050"}}],
                        "fares": [{"paxPoints": [{"points": {"amount": 18500}, "taxes": 42.5}]},
                                  {"paxPoints": [{"points": {"amount": 25000}}]}],
                    },
                    {
                        "identifier": {"std": "2026-12-20T13:00:00", "sta": "2026-12-20T19:40:00"},
                        "segments": [
                            {"identifier": {"flightNumber": "2701"}},
                            {"identifier": {"flightNumber": "4422"}},
                        ],
                        "fares": [{"points": "12.300"}],
                    },
                ]
            }]
        }
    }
    ofertas = extrair_ofertas(resposta, "VCP", "REC", date(2026, 12, 20))
    assert [(o.voo, o.pontos, o.paradas, o.partida, o.chegada) for o in ofertas] == [
        ("AD2701+AD4422", 12300, 1, "13:00", "19:40"),
        ("AD4050", 18500, 0, "06:10", "09:05"),
    ]
    assert ofertas[1].taxas == 42.5


def test_extrair_ofertas_sem_dados():
    assert extrair_ofertas({"erro": "x"}, "VCP", "REC", HOJE) == []


def test_web_fluxo_completo(tmp_path):
    app = criar_app(config(tmp_path), iniciar_agendador=False)
    with TestClient(app) as cliente:
        assert cliente.get("/").status_code == 200
        r = cliente.post("/monitores", data={
            "origem": "vcp", "destino": "rec", "data_inicio": HOJE.isoformat(),
            "data_fim": (HOJE + timedelta(days=2)).isoformat(), "max_pontos": "20.000",
        }, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/monitores/1"
        m = app.state.db.obter_monitor(1)
        assert m.max_pontos == 20000 and m.origem == "VCP"
        app.state.verificador.verificar(m)
        pagina = cliente.get("/monitores/1")
        assert pagina.status_code == 200 and "VCP → REC" in pagina.text

        r = cliente.post("/monitores", data={
            "origem": "VCP", "destino": "VCP", "data_inicio": HOJE.isoformat(),
            "data_fim": HOJE.isoformat(),
        }, follow_redirects=False)
        assert "erro=" in r.headers["location"]

        cliente.post("/monitores/1/excluir")
        assert app.state.db.obter_monitor(1) is None
