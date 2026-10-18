from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass
class Oferta:
    """Uma opção de voo encontrada para uma data, com o preço em pontos."""

    data: date
    origem: str
    destino: str
    voo: str  # ex.: "AD4050" ou "AD4050+AD2701" em conexões
    pontos: int
    partida: str | None = None  # "HH:MM"
    chegada: str | None = None
    paradas: int = 0
    taxas: float | None = None  # taxas de embarque em R$


class ErroProvedor(Exception):
    pass


class Provedor(Protocol):
    def buscar(self, origem: str, destino: str, data: date) -> list[Oferta]: ...

    def fechar(self) -> None: ...
