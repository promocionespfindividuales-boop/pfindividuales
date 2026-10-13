"""Persistencia en SQLite (stdlib, sin ORM)."""
import sqlite3
from contextlib import contextmanager

from . import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ligas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    token            TEXT UNIQUE NOT NULL,
    nombre           TEXT NOT NULL,
    num_empleado     TEXT,
    empresa          TEXT,
    telefono         TEXT,
    correo           TEXT,
    monto_descuento  REAL,
    periodicidad     TEXT,
    creada_en        TEXT NOT NULL,
    expira_en        TEXT NOT NULL,
    estado           TEXT NOT NULL DEFAULT 'pendiente'  -- pendiente | completada | revocada
);

CREATE TABLE IF NOT EXISTS domiciliaciones (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    liga_id            INTEGER UNIQUE NOT NULL REFERENCES ligas(id),
    titular            TEXT NOT NULL,
    clabe_cifrada      TEXT NOT NULL,
    clabe_ultimos4     TEXT NOT NULL,
    banco              TEXT NOT NULL,
    procesador         TEXT NOT NULL,
    tarjeta_token      TEXT NOT NULL,
    tarjeta_ultimos4   TEXT NOT NULL,
    tarjeta_marca      TEXT,
    device_session_id  TEXT,
    acepto_terminos    INTEGER NOT NULL,
    texto_autorizacion TEXT NOT NULL,
    ip                 TEXT,
    user_agent         TEXT,
    registrada_en      TEXT NOT NULL
);
"""


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def inicializar():
    with conectar() as con:
        con.executescript(ESQUEMA)


@contextmanager
def tx():
    con = conectar()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
