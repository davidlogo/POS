"""
Script de recuperación de contraseña.

Se ejecuta manualmente en el computador de la tienda si el dueño olvida la clave.
NO toca ningún dato (productos, ventas, ajustes, cierres): solo borra la contraseña
guardada para que al abrir el POS pida crear una nueva, o permite definir una aquí mismo.

Cómo ejecutarlo en Windows (PowerShell dentro de la carpeta pos):
    .\.venv\Scripts\python.exe scripts\restablecer_clave.py
"""

import getpass
import sys
from pathlib import Path

# Agregamos la carpeta raíz del proyecto al path
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from database.conexion import cerrar_conexion, obtener_conexion, transaccion  # noqa: E402
from database.migraciones import inicializar_base_datos  # noqa: E402
from modules import auth  # noqa: E402


def main() -> int:
    inicializar_base_datos()
    print("=" * 60)
    print("  RECUPERACIÓN DE CONTRASEÑA DEL POS")
    print("  (Los productos, ventas y ajustes NO se modifican)")
    print("=" * 60)

    confirmacion = input("\nEscriba RESTABLECER (en mayúsculas) para continuar: ").strip()
    if confirmacion != "RESTABLECER":
        print("Operación cancelada.")
        cerrar_conexion()
        return 0

    print("\nOpciones:")
    print("  1. Borrar la contraseña actual (al abrir el POS le pedirá crear una nueva)")
    print("  2. Escribir la nueva contraseña ahora mismo")
    opcion = input("\nElija 1 o 2 [1]: ").strip() or "1"

    if opcion == "2":
        nueva = getpass.getpass("Nueva contraseña: ")
        repetir = getpass.getpass("Confirmar nueva contraseña: ")
        error = auth.validar_clave_nueva(nueva, repetir)
        if error:
            print(f"\nError: {error}")
            cerrar_conexion()
            return 1
        auth.establecer_clave(nueva)
        print("\nListo: la contraseña ha sido actualizada.")
    else:
        with transaccion() as con:
            con.execute("DELETE FROM usuario WHERE id = 1")
        print("\nListo: contraseña borrada. Abra el POS para crear una nueva.")

    cerrar_conexion()
    return 0


if __name__ == "__main__":
    sys.exit(main())
