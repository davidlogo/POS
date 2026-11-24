"""
Acceso con contraseña única.

La contraseña NUNCA se guarda en texto plano. Se guarda:
  - una "sal" aleatoria (para que dos claves iguales den hash distinto),
  - el hash PBKDF2-HMAC-SHA256 con muchas iteraciones (lento a propósito
    para dificultar ataques de adivinación).
"""

import hashlib
import hmac
import secrets

from database.conexion import ahora, obtener_conexion, transaccion

ITERACIONES = 600_000
LONGITUD_MINIMA = 4


def _calcular_hash(clave: str, sal: bytes, iteraciones: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), sal, iteraciones).hex()


def existe_clave() -> bool:
    """¿Ya se creó la contraseña? (False en la primera ejecución)."""
    fila = obtener_conexion().execute("SELECT 1 FROM usuario WHERE id = 1").fetchone()
    return fila is not None


def validar_clave_nueva(clave: str, confirmacion: str) -> str | None:
    """Devuelve un mensaje de error, o None si la clave es aceptable."""
    if len(clave) < LONGITUD_MINIMA:
        return f"La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres."
    if clave != confirmacion:
        return "Las contraseñas no coinciden."
    return None


def establecer_clave(clave: str) -> None:
    """Crea o reemplaza la contraseña."""
    if len(clave) < LONGITUD_MINIMA:
        raise ValueError(f"La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres.")
    sal = secrets.token_bytes(16)
    hash_hex = _calcular_hash(clave, sal, ITERACIONES)
    with transaccion() as con:
        con.execute(
            """
            INSERT INTO usuario (id, hash_clave, sal, iteraciones, actualizado_en)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                hash_clave = excluded.hash_clave,
                sal = excluded.sal,
                iteraciones = excluded.iteraciones,
                actualizado_en = excluded.actualizado_en
            """,
            (hash_hex, sal.hex(), ITERACIONES, ahora()),
        )


def verificar_clave(clave: str) -> bool:
    """True si la contraseña es correcta."""
    fila = obtener_conexion().execute(
        "SELECT hash_clave, sal, iteraciones FROM usuario WHERE id = 1"
    ).fetchone()
    if fila is None:
        return False
    calculado = _calcular_hash(clave, bytes.fromhex(fila["sal"]), fila["iteraciones"])
    # compare_digest compara en tiempo constante (buena práctica de seguridad)
    return hmac.compare_digest(calculado, fila["hash_clave"])


def cambiar_clave(actual: str, nueva: str, confirmacion: str) -> str | None:
    """
    Cambia la contraseña desde Ajustes.
    Devuelve un mensaje de error, o None si se cambió correctamente.
    """
    if not verificar_clave(actual):
        return "La contraseña actual no es correcta."
    error = validar_clave_nueva(nueva, confirmacion)
    if error:
        return error
    establecer_clave(nueva)
    return None
