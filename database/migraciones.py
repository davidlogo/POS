"""
Creación y actualización del esquema de la base de datos.

Cada vez que en una fase futura haya que cambiar tablas, se agrega una
nueva función de migración a la lista MIGRACIONES. Así la base de datos
de la tienda se actualiza sola sin perder información.
"""

from database.conexion import obtener_conexion, transaccion
from utils.rutas import carpeta_recursos


def _migracion_1(con) -> None:
    """Versión 1: crea todas las tablas iniciales."""
    sql = (carpeta_recursos() / "database" / "esquema.sql").read_text(encoding="utf-8")
    # Ejecutamos sentencia por sentencia para mantenernos dentro de la transacción
    for sentencia in sql.split(";"):
        # Quitamos líneas de comentario para ver si queda algo que ejecutar
        lineas = [l for l in sentencia.splitlines() if not l.strip().startswith("--")]
        if "".join(lineas).strip():
            con.execute(sentencia)


def _migracion_2(con) -> None:
    """Versión 2: normaliza a MAYÚSCULAS los textos ya suministrados en la base de datos."""
    con.execute("UPDATE categorias SET nombre = UPPER(nombre)")
    con.execute("UPDATE productos SET nombre = UPPER(nombre), codigo_barras = UPPER(codigo_barras)")
    con.execute("UPDATE venta_items SET nombre = UPPER(nombre), codigo_barras = UPPER(codigo_barras)")
    con.execute("UPDATE movimientos_stock SET motivo = UPPER(motivo) WHERE motivo IS NOT NULL")
    con.execute("UPDATE movimientos_caja SET motivo = UPPER(motivo)")
    con.execute("UPDATE devoluciones SET motivo = UPPER(motivo)")
    con.execute("UPDATE turnos SET notas = UPPER(notas) WHERE notas IS NOT NULL")


def _migracion_3(con) -> None:
    """Versión 3: redondeo individual por producto (múltiplo 1/50/100 y modo arriba/abajo)."""
    cols = {f[1] for f in con.execute("PRAGMA table_info(productos)").fetchall()}
    if "redondeo_multiplo" not in cols:
        con.execute("ALTER TABLE productos ADD COLUMN redondeo_multiplo INTEGER NOT NULL DEFAULT 1")
    if "redondeo_modo" not in cols:
        con.execute("ALTER TABLE productos ADD COLUMN redondeo_modo TEXT NOT NULL DEFAULT 'arriba'")


# Lista ordenada de migraciones: la posición + 1 es el número de versión
MIGRACIONES = [
    _migracion_1,
    _migracion_2,
    _migracion_3,
]


def version_actual(con) -> int:
    """Lee la versión del esquema guardada en el archivo SQLite."""
    return con.execute("PRAGMA user_version").fetchone()[0]


def inicializar_base_datos() -> None:
    """Crea la base si no existe y aplica las migraciones pendientes."""
    con = obtener_conexion()
    version = version_actual(con)
    for numero, migracion in enumerate(MIGRACIONES, start=1):
        if numero > version:
            with transaccion() as c:
                migracion(c)
                c.execute(f"PRAGMA user_version = {numero}")
