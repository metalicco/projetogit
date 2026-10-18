"""Edição do arquivo monitores.json (usado pelo formulário do GitHub Actions)."""

import json
from datetime import date, datetime
from pathlib import Path


def ler_data(texto: str) -> date:
    texto = texto.strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            pass
    raise ValueError(f"Data inválida: {texto!r}. Use DD/MM/AAAA, por exemplo 20/12/2026.")


def _ler(caminho: Path) -> list[dict]:
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else []


def _gravar(caminho: Path, rotas: list[dict]) -> None:
    caminho.write_text(json.dumps(rotas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validar_aeroporto(codigo: str) -> str:
    codigo = codigo.strip().upper()
    if len(codigo) != 3 or not codigo.isalpha():
        raise ValueError(f"Aeroporto inválido: {codigo!r}. Use o código de 3 letras, por exemplo VCP.")
    return codigo


def adicionar_rota(
    caminho: Path,
    origem: str,
    destino: str,
    data_inicio: str,
    data_fim: str = "",
    max_pontos: str = "",
    desconto_minimo_pct: str = "",
    somente_diretos: bool = False,
    hoje: date | None = None,
) -> dict:
    """Adiciona (ou atualiza, se já existir a mesma rota e período) uma rota no arquivo."""
    origem, destino = _validar_aeroporto(origem), _validar_aeroporto(destino)
    if origem == destino:
        raise ValueError("Origem e destino devem ser diferentes.")
    inicio = ler_data(data_inicio)
    fim = ler_data(data_fim) if data_fim.strip() else inicio
    if fim < inicio:
        raise ValueError("A data final deve ser igual ou posterior à inicial.")
    if fim < (hoje or date.today()):
        raise ValueError("O período escolhido já passou.")
    rota = {
        "origem": origem,
        "destino": destino,
        "data_inicio": inicio.isoformat(),
        "data_fim": fim.isoformat(),
        "max_pontos": int(max_pontos.replace(".", "").strip()) if max_pontos.strip() else None,
        "desconto_minimo_pct": float(desconto_minimo_pct) if desconto_minimo_pct.strip() else 20,
        "somente_diretos": somente_diretos,
    }
    rotas = [r for r in _ler(caminho) if not _mesma(r, rota)]
    rotas.append(rota)
    _gravar(caminho, rotas)
    return rota


def remover_rota(caminho: Path, origem: str, destino: str, data_inicio: str = "") -> int:
    """Remove as rotas de origem→destino (só as do período que começa em `data_inicio`, se informado)."""
    origem, destino = _validar_aeroporto(origem), _validar_aeroporto(destino)
    inicio = ler_data(data_inicio).isoformat() if data_inicio.strip() else None
    rotas = _ler(caminho)
    restantes = [
        r for r in rotas
        if not (r["origem"] == origem and r["destino"] == destino
                and (inicio is None or r["data_inicio"] == inicio))
    ]
    _gravar(caminho, restantes)
    return len(rotas) - len(restantes)


def _mesma(a: dict, b: dict) -> bool:
    return all(a[k] == b[k] for k in ("origem", "destino", "data_inicio", "data_fim"))
