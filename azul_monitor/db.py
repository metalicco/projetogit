"""Persistência em SQLite: monitores, histórico de preços e alertas."""

import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS monitores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origem TEXT NOT NULL,
    destino TEXT NOT NULL,
    data_inicio TEXT NOT NULL,
    data_fim TEXT NOT NULL,
    max_pontos INTEGER,
    desconto_minimo_pct REAL NOT NULL DEFAULT 20,
    somente_diretos INTEGER NOT NULL DEFAULT 0,
    intervalo_minutos INTEGER NOT NULL DEFAULT 180,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL,
    ultima_verificacao TEXT,
    ultimo_erro TEXT
);

CREATE TABLE IF NOT EXISTS precos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id INTEGER NOT NULL REFERENCES monitores(id) ON DELETE CASCADE,
    data_voo TEXT NOT NULL,
    voo TEXT NOT NULL,
    partida TEXT,
    chegada TEXT,
    paradas INTEGER NOT NULL DEFAULT 0,
    pontos INTEGER NOT NULL,
    taxas REAL,
    coletado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_precos_monitor ON precos(monitor_id, data_voo);

CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    monitor_id INTEGER NOT NULL REFERENCES monitores(id) ON DELETE CASCADE,
    data_voo TEXT NOT NULL,
    voo TEXT NOT NULL,
    pontos INTEGER NOT NULL,
    motivo TEXT NOT NULL,
    criado_em TEXT NOT NULL
);
"""


@dataclass
class Monitor:
    id: int
    origem: str
    destino: str
    data_inicio: date
    data_fim: date
    max_pontos: int | None
    desconto_minimo_pct: float
    somente_diretos: bool
    intervalo_minutos: int
    ativo: bool
    criado_em: datetime
    ultima_verificacao: datetime | None
    ultimo_erro: str | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Monitor":
        return cls(
            id=r["id"],
            origem=r["origem"],
            destino=r["destino"],
            data_inicio=date.fromisoformat(r["data_inicio"]),
            data_fim=date.fromisoformat(r["data_fim"]),
            max_pontos=r["max_pontos"],
            desconto_minimo_pct=r["desconto_minimo_pct"],
            somente_diretos=bool(r["somente_diretos"]),
            intervalo_minutos=r["intervalo_minutos"],
            ativo=bool(r["ativo"]),
            criado_em=datetime.fromisoformat(r["criado_em"]),
            ultima_verificacao=(
                datetime.fromisoformat(r["ultima_verificacao"]) if r["ultima_verificacao"] else None
            ),
            ultimo_erro=r["ultimo_erro"],
        )

    @property
    def rota(self) -> str:
        return f"{self.origem} → {self.destino}"


class Database:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def _exec(self, sql: str, params=()) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, params)

    def _all(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # --- monitores ---

    def criar_monitor(
        self,
        origem: str,
        destino: str,
        data_inicio: date,
        data_fim: date,
        max_pontos: int | None = None,
        desconto_minimo_pct: float = 20,
        somente_diretos: bool = False,
        intervalo_minutos: int = 180,
    ) -> int:
        if data_fim < data_inicio:
            raise ValueError("A data final deve ser igual ou posterior à data inicial.")
        cur = self._exec(
            """INSERT INTO monitores (origem, destino, data_inicio, data_fim, max_pontos,
               desconto_minimo_pct, somente_diretos, intervalo_minutos, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                origem.upper().strip(),
                destino.upper().strip(),
                data_inicio.isoformat(),
                data_fim.isoformat(),
                max_pontos,
                desconto_minimo_pct,
                int(somente_diretos),
                intervalo_minutos,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        return cur.lastrowid

    def sincronizar_monitores(self, definicoes: list[dict]) -> list[Monitor]:
        """Deixa ativos exatamente os monitores descritos em `definicoes`.

        Um monitor é identificado por rota e período; os demais campos são atualizados.
        Monitores fora da lista são pausados (não excluídos) para preservar o histórico.
        """
        ids = []
        for d in definicoes:
            origem, destino = d["origem"].upper().strip(), d["destino"].upper().strip()
            inicio, fim = date.fromisoformat(d["data_inicio"]), date.fromisoformat(d["data_fim"])
            regras = (
                d.get("max_pontos"),
                d.get("desconto_minimo_pct", 20),
                int(d.get("somente_diretos", False)),
            )
            rows = self._all(
                """SELECT id FROM monitores WHERE origem = ? AND destino = ?
                   AND data_inicio = ? AND data_fim = ?""",
                (origem, destino, inicio.isoformat(), fim.isoformat()),
            )
            if rows:
                monitor_id = rows[0]["id"]
                self._exec(
                    """UPDATE monitores SET max_pontos = ?, desconto_minimo_pct = ?,
                       somente_diretos = ?, ativo = 1 WHERE id = ?""",
                    (*regras, monitor_id),
                )
            else:
                monitor_id = self.criar_monitor(
                    origem, destino, inicio, fim, max_pontos=regras[0],
                    desconto_minimo_pct=regras[1], somente_diretos=bool(regras[2]),
                )
            ids.append(monitor_id)
        marcadores = ",".join("?" * len(ids))
        self._exec(f"UPDATE monitores SET ativo = 0 WHERE id NOT IN ({marcadores})", ids)
        return [self.obter_monitor(i) for i in ids]

    def listar_monitores(self, somente_ativos: bool = False) -> list[Monitor]:
        sql = "SELECT * FROM monitores"
        if somente_ativos:
            sql += " WHERE ativo = 1"
        return [Monitor.from_row(r) for r in self._all(sql + " ORDER BY id")]

    def obter_monitor(self, monitor_id: int) -> Monitor | None:
        rows = self._all("SELECT * FROM monitores WHERE id = ?", (monitor_id,))
        return Monitor.from_row(rows[0]) if rows else None

    def alternar_monitor(self, monitor_id: int) -> None:
        self._exec("UPDATE monitores SET ativo = 1 - ativo WHERE id = ?", (monitor_id,))

    def excluir_monitor(self, monitor_id: int) -> None:
        self._exec("DELETE FROM monitores WHERE id = ?", (monitor_id,))

    def registrar_verificacao(self, monitor_id: int, erro: str | None = None) -> None:
        self._exec(
            "UPDATE monitores SET ultima_verificacao = ?, ultimo_erro = ? WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), erro, monitor_id),
        )

    # --- preços ---

    def salvar_preco(self, monitor_id: int, oferta, coletado_em: datetime) -> None:
        self._exec(
            """INSERT INTO precos (monitor_id, data_voo, voo, partida, chegada, paradas,
               pontos, taxas, coletado_em) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                monitor_id,
                oferta.data.isoformat(),
                oferta.voo,
                oferta.partida,
                oferta.chegada,
                oferta.paradas,
                oferta.pontos,
                oferta.taxas,
                coletado_em.isoformat(timespec="seconds"),
            ),
        )

    def media_historica(self, monitor_id: int, antes_de: datetime) -> float | None:
        """Média do menor preço por (data, coleta) registrado antes de `antes_de`."""
        rows = self._all(
            """SELECT AVG(minimo) AS media FROM (
                 SELECT MIN(pontos) AS minimo FROM precos
                 WHERE monitor_id = ? AND coletado_em < ?
                 GROUP BY data_voo, coletado_em)""",
            (monitor_id, antes_de.isoformat(timespec="seconds")),
        )
        return rows[0]["media"] if rows else None

    def melhores_por_data(self, monitor_id: int) -> list[sqlite3.Row]:
        """Menor preço por data na coleta mais recente, junto do menor já visto."""
        return self._all(
            """WITH ultima AS (
                 SELECT data_voo, MAX(coletado_em) AS coletado_em FROM precos
                 WHERE monitor_id = ? GROUP BY data_voo)
               SELECT p.data_voo, p.voo, p.partida, p.chegada, p.paradas, p.pontos, p.taxas,
                      p.coletado_em,
                      (SELECT MIN(pontos) FROM precos h
                       WHERE h.monitor_id = p.monitor_id AND h.data_voo = p.data_voo) AS minimo_historico
               FROM precos p JOIN ultima u
                 ON p.data_voo = u.data_voo AND p.coletado_em = u.coletado_em
               WHERE p.monitor_id = ?
                 AND p.pontos = (SELECT MIN(pontos) FROM precos q
                                 WHERE q.monitor_id = p.monitor_id AND q.data_voo = p.data_voo
                                   AND q.coletado_em = p.coletado_em)
               GROUP BY p.data_voo
               ORDER BY p.data_voo""",
            (monitor_id, monitor_id),
        )

    def historico_minimos(self, monitor_id: int) -> list[sqlite3.Row]:
        """Menor preço (entre todas as datas) em cada coleta, para o gráfico."""
        return self._all(
            """SELECT coletado_em, MIN(pontos) AS pontos FROM precos
               WHERE monitor_id = ? GROUP BY coletado_em ORDER BY coletado_em""",
            (monitor_id,),
        )

    # --- alertas ---

    def ultimo_alerta(self, monitor_id: int, data_voo: date) -> sqlite3.Row | None:
        rows = self._all(
            """SELECT * FROM alertas WHERE monitor_id = ? AND data_voo = ?
               ORDER BY id DESC LIMIT 1""",
            (monitor_id, data_voo.isoformat()),
        )
        return rows[0] if rows else None

    def salvar_alerta(self, monitor_id: int, oferta, motivo: str) -> None:
        self._exec(
            """INSERT INTO alertas (monitor_id, data_voo, voo, pontos, motivo, criado_em)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                monitor_id,
                oferta.data.isoformat(),
                oferta.voo,
                oferta.pontos,
                motivo,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )

    def listar_alertas(self, monitor_id: int | None = None, limite: int = 50) -> list[sqlite3.Row]:
        sql = """SELECT a.*, m.origem, m.destino FROM alertas a
                 JOIN monitores m ON m.id = a.monitor_id"""
        params: tuple = ()
        if monitor_id is not None:
            sql += " WHERE a.monitor_id = ?"
            params = (monitor_id,)
        return self._all(sql + " ORDER BY a.id DESC LIMIT ?", params + (limite,))
