"""
Módulo de Respaldos y Restauración de la base de datos (Fase 8).

Características:
  * Usa la función nativa `backup()` de SQLite para que la copia sea íntegra
    incluso con la base de datos abierta.
  * Nombres con fecha y hora: `respaldo_pos_AAAA-MM-DD_HH-MM-SS.db`.
  * Rotación automática: conserva solo los últimos N respaldos en la carpeta.
  * Si la carpeta configurada (por ejemplo una memoria USB desconectada) no está
    accesible al hacer un respaldo automático, guarda el respaldo en la carpeta
    local por defecto (`pos/datos/respaldos`) para no quedarse sin copia.
  * Restauración segura:
      1. Verifica que el archivo de respaldo sea una BD SQLite íntegra y del POS.
      2. Crea una copia de seguridad previa de la base actual.
      3. Reemplaza la base de datos, reconecta y aplica migraciones si hacen falta.
"""

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from database import conexion
from database.migraciones import inicializar_base_datos
from modules import ajustes
from utils.rutas import carpeta_datos

PREFIJO_RESPALDO = "respaldo_pos_"

# Marca de tiempo de modificación de pos.db al hacer el último respaldo por cierre de caja
# (evita crear un respaldo duplicado segundos después al cerrar la app si no hubo cambios)
_ultimo_respaldo_cierre_caja_mtime: float | None = None


def _es_respaldo_conservable_del_dia(stem: str) -> bool:
    """Manuales y copias previas a restauración nunca se eliminan al consolidar el día."""
    return (
        stem.endswith("_manual")
        or "_manual_" in stem
        or "_previo_restauracion" in stem
    )


class ErrorRespaldo(Exception):
    """Error al crear o restaurar un respaldo."""


def carpeta_respaldos_por_defecto() -> Path:
    ruta = carpeta_datos() / "respaldos"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def obtener_carpeta_configurada() -> Path:
    """Devuelve la carpeta configurada por el usuario o la carpeta por defecto."""
    texto = (ajustes.obtener("respaldo_carpeta") or "").strip()
    if texto:
        return Path(texto)
    return carpeta_respaldos_por_defecto()


def _asegurar_carpeta_destino(usar_alternativa_local: bool = True) -> tuple[Path, bool]:
    """
    Intenta usar la carpeta configurada. Si falla (ej. USB desconectada) y
    `usar_alternativa_local=True`, usa la carpeta local por defecto.
    Devuelve (ruta_carpeta, uso_carpeta_alternativa).
    """
    destino = obtener_carpeta_configurada()
    try:
        destino.mkdir(parents=True, exist_ok=True)
        return destino, False
    except OSError as e:
        if not usar_alternativa_local:
            raise ErrorRespaldo(f"No se pudo acceder a la carpeta de respaldos:\n{destino}\n\n{e}")
        return carpeta_respaldos_por_defecto(), True


def crear_respaldo(etiqueta: str = "", usar_alternativa_local: bool = True) -> dict:
    """
    Crea un respaldo completo de la base de datos actual y rota los antiguos.
    Devuelve:
      {'ruta': Path, 'usando_alternativa': bool, 'eliminados': int}
    """
    carpeta, alternativa = _asegurar_carpeta_destino(usar_alternativa_local=usar_alternativa_local)
    marca_tiempo = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    sufijo = f"_{etiqueta}" if etiqueta else ""
    nombre = f"{PREFIJO_RESPALDO}{marca_tiempo}{sufijo}.db"
    ruta_destino = carpeta / nombre

    # Si ya existe un archivo en el mismo segundo, agregamos un contador
    contador = 2
    while ruta_destino.exists():
        ruta_destino = carpeta / f"{PREFIJO_RESPALDO}{marca_tiempo}{sufijo}_{contador}.db"
        contador += 1

    con_origen = conexion.obtener_conexion()
    try:
        con_dest = sqlite3.connect(str(ruta_destino))
        try:
            con_origen.backup(con_dest)
        finally:
            con_dest.close()
    except Exception as e:  # noqa: BLE001
        raise ErrorRespaldo(f"No se pudo crear el archivo de respaldo:\n{e}")

    eliminados = rotar_respaldos(carpeta)
    return {
        "ruta": ruta_destino,
        "usando_alternativa": alternativa,
        "eliminados": eliminados,
    }


def listar_respaldos(carpeta: Path | None = None) -> list[dict]:
    """
    Lista los archivos `.db` de respaldo en la carpeta indicada (del más reciente al más antiguo).
    """
    if carpeta is None:
        carpeta = obtener_carpeta_configurada()
    if not carpeta.exists():
        return []

    archivos = []
    for p in carpeta.glob("*.db"):
        if not p.is_file():
            continue
        try:
            stat = p.stat()
        except OSError:
            continue
        archivos.append({
            "nombre": p.name,
            "ruta": p,
            "tamano_bytes": stat.st_size,
            "fecha_modificacion": datetime.fromtimestamp(stat.st_mtime).strftime("%d-%m-%Y %H:%M:%S"),
            "mtime": stat.st_mtime,
        })

    archivos.sort(key=lambda x: (x["mtime"], x["nombre"]), reverse=True)
    return archivos


def rotar_respaldos(carpeta: Path | None = None, max_archivos: int | None = None) -> int:
    """
    Conserva únicamente los últimos `max_archivos` respaldos con prefijo `respaldo_pos_`
    y elimina los más viejos. Devuelve cuántos archivos se eliminaron.
    """
    if carpeta is None:
        carpeta = obtener_carpeta_configurada()
    if max_archivos is None:
        try:
            max_archivos = max(1, ajustes.obtener_entero("respaldo_max_archivos"))
        except Exception:  # noqa: BLE001
            max_archivos = 30

    if not carpeta.exists():
        return 0

    propios = [
        item for item in listar_respaldos(carpeta)
        if item["nombre"].startswith(PREFIJO_RESPALDO)
    ]
    sobrantes = propios[max_archivos:]
    eliminados = 0
    for item in sobrantes:
        try:
            item["ruta"].unlink()
            eliminados += 1
        except OSError:
            pass
    return eliminados


def validar_archivo_respaldo(ruta_archivo) -> None:
    """
    Comprueba que `ruta_archivo` exista, pase `PRAGMA integrity_check` y
    contenga las tablas principales del POS. Lanza ErrorRespaldo si no es válido.
    """
    ruta = Path(ruta_archivo)
    if not ruta.exists() or not ruta.is_file():
        raise ErrorRespaldo("El archivo de respaldo seleccionado no existe.")
    if ruta.stat().st_size < 4096:
        raise ErrorRespaldo("El archivo seleccionado no parece una base de datos válida.")

    try:
        con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
        try:
            integ = con.execute("PRAGMA integrity_check").fetchone()
            if not integ or integ[0] != "ok":
                raise ErrorRespaldo("El archivo de respaldo está dañado (falló integrity_check).")
            tablas = {
                f[0]
                for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        finally:
            con.close()
    except ErrorRespaldo:
        raise
    except Exception as e:  # noqa: BLE001
        raise ErrorRespaldo(f"El archivo no es una base de datos SQLite válida:\n{e}")

    requeridas = {"ajustes", "usuario", "productos", "ventas", "venta_items"}
    if not requeridas.issubset(tablas):
        raise ErrorRespaldo(
            "El archivo seleccionado no corresponde a una base de datos de este sistema POS."
        )


def restaurar_respaldo(ruta_archivo) -> Path:
    """
    Restaura la base de datos desde `ruta_archivo`:
      1. Valida el archivo de respaldo.
      2. Guarda una copia de seguridad previa de la base actual.
      3. Cierra la conexión, reemplaza el archivo de la BD activa, reconecta y
         conserva la configuración actual de respaldos.
    Devuelve la ruta de la copia de seguridad previa creada.
    """
    ruta_origen = Path(ruta_archivo).resolve()
    validar_archivo_respaldo(ruta_origen)

    # Guardamos los ajustes de respaldo actuales para que restaurar un respaldo antiguo
    # no cambie la carpeta de respaldos que el usuario tiene configurada hoy
    ajustes_respaldo_actuales = {
        "respaldo_carpeta": ajustes.obtener("respaldo_carpeta"),
        "respaldo_al_cerrar": ajustes.obtener("respaldo_al_cerrar"),
        "respaldo_al_abrir": ajustes.obtener("respaldo_al_abrir"),
        "respaldo_max_archivos": ajustes.obtener("respaldo_max_archivos"),
    }

    # 1. Crear copia de seguridad previa de la base actual
    copia_previa = crear_respaldo(etiqueta="previo_restauracion", usar_alternativa_local=True)["ruta"]

    # Determinamos la ruta de la BD activa actual
    ruta_bd_activa = conexion._ruta_actual or conexion.ruta_base_datos()
    if ruta_origen == Path(ruta_bd_activa).resolve():
        raise ErrorRespaldo("No puede restaurar el mismo archivo de base de datos que está en uso.")

    # 2. Cerrar conexión activa y reemplazar archivo
    conexion.cerrar_conexion()
    try:
        shutil.copy2(ruta_origen, ruta_bd_activa)
    except Exception as e:  # noqa: BLE001
        # Si algo fallara al copiar, reabrimos la copia previa
        shutil.copy2(copia_previa, ruta_bd_activa)
        conexion.obtener_conexion(ruta_bd_activa)
        raise ErrorRespaldo(f"No se pudo copiar el respaldo:\n{e}")

    # 3. Reconectar, asegurar migraciones y preservar configuración de respaldos
    conexion.obtener_conexion(ruta_bd_activa)
    inicializar_base_datos()
    ajustes.guardar_varios(ajustes_respaldo_actuales)

    return copia_previa


def eliminar_respaldo(ruta_archivo) -> None:
    """Elimina un archivo de respaldo de la carpeta (sin permitir borrar la BD activa)."""
    ruta = Path(ruta_archivo).resolve()
    ruta_bd_activa = Path(conexion._ruta_actual or conexion.ruta_base_datos()).resolve()
    if ruta == ruta_bd_activa:
        raise ErrorRespaldo("No se puede eliminar la base de datos activa del sistema.")
    if not ruta.exists() or not ruta.is_file():
        raise ErrorRespaldo("El archivo de respaldo ya no existe.")
    try:
        ruta.unlink()
    except OSError as e:
        raise ErrorRespaldo(f"No se pudo eliminar el archivo de respaldo:\n{e}")


def respaldar_si_corresponde_al_abrir() -> dict | None:
    """Si está activo 'respaldo_al_abrir', crea un respaldo silencioso."""
    if not ajustes.obtener_booleano("respaldo_al_abrir"):
        return None
    try:
        return crear_respaldo(etiqueta="apertura", usar_alternativa_local=True)
    except Exception:  # noqa: BLE001
        return None


def respaldar_si_corresponde_al_cerrar() -> dict | None:
    """Si está activo 'respaldo_al_cerrar', crea un respaldo al salir del POS (evita duplicar tras cierre de caja)."""
    if not ajustes.obtener_booleano("respaldo_al_cerrar"):
        return None
    if _ultimo_respaldo_cierre_caja_mtime is not None:
        ruta_bd = Path(conexion._ruta_actual or conexion.ruta_base_datos())
        try:
            if ruta_bd.exists() and abs(ruta_bd.stat().st_mtime - _ultimo_respaldo_cierre_caja_mtime) < 1.0:
                return None
        except OSError:
            pass
    try:
        return crear_respaldo(etiqueta="cierre", usar_alternativa_local=True)
    except Exception:  # noqa: BLE001
        return None


def respaldar_por_cierre_caja() -> dict:
    """
    Crea y valida el respaldo definitivo al realizar el cierre de caja y elimina
    los respaldos automáticos anteriores del mismo día (conservando los manuales
    y los previos a restauración).
    """
    global _ultimo_respaldo_cierre_caja_mtime

    info = crear_respaldo(etiqueta="cierre_caja", usar_alternativa_local=True)
    ruta_nueva = Path(info["ruta"]).resolve()

    # Solo depuramos copias previas del día si la copia final quedó íntegra
    validar_archivo_respaldo(ruta_nueva)

    prefijo_hoy = f"{PREFIJO_RESPALDO}{datetime.now().strftime('%Y-%m-%d')}_"
    eliminados_dia = 0
    for p in ruta_nueva.parent.glob("*.db"):
        if not p.is_file():
            continue
        try:
            if p.resolve() == ruta_nueva:
                continue
        except OSError:
            continue
        if not p.name.startswith(prefijo_hoy):
            continue
        if _es_respaldo_conservable_del_dia(p.stem):
            continue
        try:
            p.unlink()
            eliminados_dia += 1
        except OSError:
            pass

    ruta_bd = Path(conexion._ruta_actual or conexion.ruta_base_datos())
    try:
        if ruta_bd.exists():
            _ultimo_respaldo_cierre_caja_mtime = ruta_bd.stat().st_mtime
    except OSError:
        _ultimo_respaldo_cierre_caja_mtime = None

    return {**info, "eliminados_dia": eliminados_dia}
