"""
Ajustes del sistema, guardados en la tabla `ajustes` (clave / valor).

Cada fase irá agregando sus propios ajustes a VALORES_POR_DEFECTO.
Si un ajuste no está guardado en la base, se usa su valor por defecto.
"""

from database.conexion import obtener_conexion, transaccion

VALORES_POR_DEFECTO: dict[str, str] = {
    "nombre_tienda": "Mi Tienda",
    # Fase 3: redondeo de precios calculados
    # multiplo: "1" = sin redondear (valor tal cual al peso), "50", "100", "500", "1000"
    "redondeo_multiplo": "1",
    # modo: "cercano" | "arriba" | "abajo"
    "redondeo_modo": "arriba",
    # Fase 4: qué hacer cuando el stock no alcanza ("avisar" = avisa y permite, "bloquear" = no deja)
    "politica_stock": "avisar",
    # Tamaño de letra en tablas y listas (en puntos, ej. 11 a 20)
    "tamano_texto_listas": "12",
    # Protección con contraseña para la pestaña Precios (activa por defecto)
    "proteger_precios": "1",
    # Fase 8: respaldos automáticos y carpeta destino (vacío = pos/datos/respaldos)
    "respaldo_carpeta": "",
    "respaldo_al_cerrar": "1",
    "respaldo_al_abrir": "0",
    "respaldo_max_archivos": "30",
    # Fase 9: cajón monedero conectado por RJ11 a convertidor USB / Serial (COM)
    "cajon_activo": "0",
    "cajon_modo": "serial",                  # 'serial' | 'archivo'
    "cajon_puerto": "COM3",                  # ej. 'COM3' en Windows o '/dev/ttyUSB0' en Linux
    "cajon_baudios": "9600",
    "cajon_comando": "escpos_pin2",          # 'escpos_pin2' | 'escpos_pin5' | 'pulso_usb' | 'personalizado'
    "cajon_hex_personalizado": "1B 70 00 19 FA",
    "cajon_abrir_otros_medios": "0",         # Opción A: 0 = solo efectivo; 1 = todos los medios
}


def obtener(clave: str) -> str:
    """Devuelve el valor de un ajuste como texto."""
    fila = obtener_conexion().execute(
        "SELECT valor FROM ajustes WHERE clave = ?", (clave,)
    ).fetchone()
    if fila is not None and fila["valor"] is not None:
        return fila["valor"]
    if clave in VALORES_POR_DEFECTO:
        return VALORES_POR_DEFECTO[clave]
    raise KeyError(f"Ajuste desconocido: {clave}")


def obtener_entero(clave: str) -> int:
    return int(obtener(clave))


def obtener_booleano(clave: str) -> bool:
    return obtener(clave).strip().lower() in ("1", "true", "si", "sí")


def guardar(clave: str, valor) -> None:
    """Guarda un ajuste (convierte booleanos a "1"/"0")."""
    if isinstance(valor, bool):
        valor = "1" if valor else "0"
    with transaccion() as con:
        con.execute(
            "INSERT INTO ajustes (clave, valor) VALUES (?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (clave, str(valor)),
        )


def guardar_varios(valores: dict) -> None:
    """Guarda varios ajustes en una sola transacción."""
    with transaccion() as con:
        for clave, valor in valores.items():
            if isinstance(valor, bool):
                valor = "1" if valor else "0"
            con.execute(
                "INSERT INTO ajustes (clave, valor) VALUES (?, ?) "
                "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
                (clave, str(valor)),
            )
