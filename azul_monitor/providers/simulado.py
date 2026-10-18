"""Provedor de dados fictícios, para testar a aplicação sem acessar o site da Azul."""

import hashlib
import random
from datetime import date, datetime

from .base import Oferta


class ProvedorSimulado:
    def __init__(self, semente: int | None = None):
        self._semente = semente

    def buscar(self, origem: str, destino: str, data: date) -> list[Oferta]:
        chave = f"{origem}{destino}{data.isoformat()}"
        base = 8000 + int(hashlib.md5(chave.encode()).hexdigest(), 16) % 30000
        # Varia a cada hora para simular oscilação de preço entre as coletas.
        semente = self._semente if self._semente is not None else datetime.now().strftime("%Y%m%d%H")
        rng = random.Random(f"{chave}{semente}")
        ofertas = []
        for i in range(rng.randint(2, 6)):
            paradas = rng.choice([0, 0, 1])
            hora = 6 + i * 3
            ofertas.append(
                Oferta(
                    data=data,
                    origem=origem,
                    destino=destino,
                    voo=f"AD{rng.randint(2000, 9999)}",
                    pontos=int(base * rng.uniform(0.5, 1.6)) // 100 * 100,
                    partida=f"{hora:02d}:{rng.choice(['00', '15', '30', '45'])}",
                    chegada=f"{(hora + 2 + paradas * 2) % 24:02d}:{rng.choice(['05', '20', '40'])}",
                    paradas=paradas,
                    taxas=round(rng.uniform(30, 80), 2),
                )
            )
        return ofertas

    def fechar(self) -> None:
        pass
