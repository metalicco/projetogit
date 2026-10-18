"""Linha de comando.

    python -m azul_monitor servir            # interface web + verificações automáticas
    python -m azul_monitor buscar VCP REC 2026-12-20
    python -m azul_monitor verificar         # verifica todos os monitores ativos uma vez
"""

import argparse
import logging
from datetime import date

from .alertas import Notificador
from .config import carregar_config
from .db import Database
from .monitor import Verificador
from .providers import criar_provedor


def main() -> None:
    parser = argparse.ArgumentParser(prog="azul_monitor", description="Monitor de passagens Azul com pontos")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_servir = sub.add_parser("servir", help="Inicia a interface web e o agendador")
    p_servir.add_argument("--host", default="127.0.0.1")
    p_servir.add_argument("--porta", type=int, default=8000)

    p_buscar = sub.add_parser("buscar", help="Busca os preços de uma data")
    p_buscar.add_argument("origem")
    p_buscar.add_argument("destino")
    p_buscar.add_argument("data", type=date.fromisoformat, help="AAAA-MM-DD")

    sub.add_parser("verificar", help="Verifica todos os monitores ativos agora")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = carregar_config()

    if args.comando == "servir":
        import uvicorn

        from .web import criar_app

        uvicorn.run(criar_app(config), host=args.host, port=args.porta)
    elif args.comando == "buscar":
        provedor = criar_provedor(config)
        try:
            ofertas = provedor.buscar(args.origem.upper(), args.destino.upper(), args.data)
        finally:
            provedor.fechar()
        if not ofertas:
            print("Nenhuma oferta em pontos encontrada.")
        for o in ofertas:
            taxas = f" + R$ {o.taxas:.2f}" if o.taxas else ""
            print(f"{o.voo:<16} {o.partida or '--:--'}→{o.chegada or '--:--'} "
                  f"paradas={o.paradas}  {o.pontos:>8,} pontos{taxas}".replace(",", "."))
    elif args.comando == "verificar":
        db = Database(config.db_path)
        provedor = criar_provedor(config)
        try:
            verificador = Verificador(db, provedor, Notificador(config), config)
            for monitor in db.listar_monitores(somente_ativos=True):
                verificador.verificar(monitor)
        finally:
            provedor.fechar()


if __name__ == "__main__":
    main()
