"""
Conexión a la base de datos SQLite.

Uso típico:

    from database.conexion import obtener_conexion, transaccion

    con = obtener_conexion()
    filas = con.execute("SELECT * FROM productos").fetchall()

    # Operaciones que deben ser "todo o nada":
    with transaccion() as con:
        con.execute("INSERT ...")
        con.execute("UPDATE ...")
    # Si ocurre un error dentro del bloque, NADA se guarda.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from utils.rutas import ruta_base_datos

_conexion: sqlite3.Connection | None = None
_ruta_actual: Path | None = None


def ahora() -> str:
    """Fecha y hora local en el formato que usamos en la base de datos."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def obtener_conexion(ruta: Path | None = None) -> sqlite3.Connection:
    """
    Devuelve la conexión única del programa (la crea la primera vez).
    `ruta` solo se usa en pruebas o al restaurar respaldos.
    """
    global _conexion, _ruta_actual
    if _conexion is None:
        _ruta_actual = Path(ruta) if ruta else ruta_base_datos()
        # isolation_level=None: nosotros controlamos las transacciones con BEGIN/COMMIT
        _conexion = sqlite3.connect(str(_ruta_actual), isolation_level=None)
        _conexion.row_factory = sqlite3.Row          # filas accesibles por nombre: fila["nombre"]
        _conexion.execute("PRAGMA foreign_keys = ON")  # respetar relaciones entre tablas
    return _conexion


def cerrar_conexion() -> None:
    """Cierra la conexión (al salir del programa o antes de restaurar un respaldo)."""
    global _conexion
    if _conexion is not None:
        _conexion.close()
        _conexion = None


@contextmanager
def transaccion():
    """
    Bloque "todo o nada".
    BEGIN IMMEDIATE bloquea la base para escribir desde el inicio,
    así ningún otro proceso puede meterse a mitad de la operación.
    """
    con = obtener_conexion()
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
