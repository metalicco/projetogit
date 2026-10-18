from ..config import Config
from .base import ErroProvedor, Oferta, Provedor


def criar_provedor(config: Config) -> Provedor:
    if config.provedor == "simulado":
        from .simulado import ProvedorSimulado

        return ProvedorSimulado()
    if config.provedor == "azul":
        from .azul import ProvedorAzul

        return ProvedorAzul(headless=config.headless, debug_dir=config.debug_dir)
    raise ValueError(f"Provedor desconhecido: {config.provedor!r} (use 'azul' ou 'simulado')")


__all__ = ["ErroProvedor", "Oferta", "Provedor", "criar_provedor"]
