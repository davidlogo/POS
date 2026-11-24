"""
Módulo aislado de control del cajón monedero (Fase 9).

Escenario del usuario:
  * NO hay impresora.
  * El cajón se conecta por cable RJ11 a un convertidor a USB.
  * Esos convertidores RJ11→USB funcionan de una de estas formas:
      1. Crean un puerto serial virtual (ej. COM3 en Windows o /dev/ttyUSB0 en Linux)
         y abren el cajón al recibir un comando ESC/POS o un byte por serial, y/o
         al activar un pulso en las líneas DTR / RTS del chip USB-Serial (CH340, PL2303, FTDI).
      2. Se exponen como un archivo de dispositivo directo (ej. /dev/usb/lp0 o LPT1 / COMx).

Regla de oro:
  * `abrir_cajon()` NUNCA lanza excepciones hacia el módulo de ventas.
    Si el cajón no está configurado o falla, devuelve `(False, mensaje_discreto)`
    y la venta se completa igual.
"""

import time

from modules import ajustes

MODOS_CONEXION = (
    ("serial", "Puerto Serial / Convertidor USB a RJ11 (COM en Windows, ttyUSB en Linux)"),
    ("archivo", "Dispositivo directo / Puerto crudo (ej. /dev/usb/lp0, LPT1, COM3)"),
)

VELOCIDADES_BAUDIOS = (9600, 19200, 38400, 57600, 115200)

# Comandos predefinidos en bytes y su descripción sencilla
COMANDOS_CAJON = (
    ("escpos_pin2", "Estándar ESC/POS Pin 2 (1B 70 00 19 FA) + pulso DTR/RTS"),
    ("escpos_pin5", "Estándar ESC/POS Pin 5 (1B 70 01 19 FA) + pulso DTR/RTS"),
    ("pulso_usb", "Disparador USB-RJ11 directo (bytes 00 FF + pulso DTR/RTS)"),
    ("personalizado", "Comando hexadecimal personalizado"),
)

_BYTES_PREDEFINIDOS = {
    "escpos_pin2": bytes.fromhex("1B 70 00 19 FA"),
    "escpos_pin5": bytes.fromhex("1B 70 01 19 FA"),
    "pulso_usb": bytes.fromhex("00 FF 1B 70 00 32 C8"),
}


def parsear_hex(texto_hex: str) -> bytes:
    """
    Convierte una cadena como '1B 70 00 19 FA' o '1b,70,00,19,fa' en bytes.
    Lanza ValueError si algún byte no es hexadecimal válido.
    """
    limpio = (texto_hex or "").replace(",", " ").replace("0x", "").replace("0X", "").strip()
    if not limpio:
        raise ValueError("El comando hexadecimal está vacío.")
    try:
        return bytes.fromhex(limpio)
    except ValueError:
        raise ValueError(
            "Formato hexadecimal no válido. Escriba pares de caracteres separados por espacio "
            "(ejemplo: 1B 70 00 19 FA)."
        )


def obtener_bytes_comando(tipo_comando: str, hex_personalizado: str = "") -> bytes:
    if tipo_comando in _BYTES_PREDEFINIDOS:
        return _BYTES_PREDEFINIDOS[tipo_comando]
    return parsear_hex(hex_personalizado)


def listar_puertos_disponibles() -> list[dict]:
    """
    Detecta los puertos seriales / convertidores USB conectados al equipo.
    Devuelve [{'dispositivo': 'COM3', 'descripcion': 'COM3 — USB-SERIAL CH340'}].
    """
    try:
        from serial.tools import list_ports

        puertos = []
        for p in list_ports.comports():
            desc = p.description or "Puerto serial"
            etiqueta = f"{p.device} — {desc}" if p.device not in desc else desc
            puertos.append({
                "dispositivo": p.device,
                "descripcion": etiqueta,
                "hwid": p.hwid or "",
            })
        return puertos
    except Exception:  # noqa: BLE001
        return []


def _enviar_por_serial(puerto: str, baudios: int, datos: bytes) -> None:
    """
    Abre el puerto serial/USB, activa un pulso en DTR/RTS y envía los bytes del comando.
    Combinar el comando ESC/POS con el pulso DTR/RTS hace que funcione tanto con
    cajones que leen bytes seriales como con convertidores RJ11-USB por relé/transistor.
    """
    import serial

    with serial.Serial(
        port=puerto,
        baudrate=baudios,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=1.0,
        write_timeout=1.0,
    ) as ser:
        # Pulso en líneas de control DTR/RTS (muchos adaptadores RJ11-USB disparan la bobina con esto)
        try:
            ser.dtr = True
            ser.rts = True
        except Exception:  # noqa: BLE001
            pass

        ser.write(datos)
        ser.flush()
        time.sleep(0.12)

        try:
            ser.dtr = False
            ser.rts = False
        except Exception:  # noqa: BLE001
            pass


def _enviar_por_archivo(ruta_dispositivo: str, datos: bytes) -> None:
    """Escribe los bytes directamente en el dispositivo (ej. /dev/usb/lp0 o LPT1)."""
    with open(ruta_dispositivo, "wb") as f:
        f.write(datos)
        f.flush()


def abrir_cajon(config_override: dict | None = None, forzar: bool = False) -> tuple[bool, str]:
    """
    Envía el pulso de apertura al cajón monedero.
    - `config_override`: diccionario opcional para probar valores desde Ajustes o desde
      el script de diagnóstico sin haberlos guardado todavía.
    - `forzar`: si es True (botón "Probar cajón"), intenta abrir aunque la casilla
      `cajon_activo` esté desmarcada.

    Devuelve SIEMPRE `(exito: bool, mensaje: str)` sin lanzar excepciones.
    """
    try:
        cfg = config_override or {
            "activo": ajustes.obtener_booleano("cajon_activo"),
            "modo": ajustes.obtener("cajon_modo"),
            "puerto": ajustes.obtener("cajon_puerto"),
            "baudios": ajustes.obtener_entero("cajon_baudios"),
            "comando": ajustes.obtener("cajon_comando"),
            "hex_personalizado": ajustes.obtener("cajon_hex_personalizado"),
        }

        if not forzar and not cfg.get("activo", False):
            return False, "Cajón desactivado en Ajustes"

        puerto = (cfg.get("puerto") or "").strip()
        if not puerto:
            return False, "No se ha indicado el puerto del cajón en Ajustes"

        datos = obtener_bytes_comando(
            cfg.get("comando", "escpos_pin2"),
            cfg.get("hex_personalizado", "1B 70 00 19 FA"),
        )
        modo = cfg.get("modo", "serial")
        baudios = int(cfg.get("baudios") or 9600)

        if modo == "archivo":
            _enviar_por_archivo(puerto, datos)
        else:
            _enviar_por_serial(puerto, baudios, datos)

        return True, f"Pulso enviado correctamente a {puerto}"
    except Exception as e:  # noqa: BLE001
        return False, f"No se pudo abrir el cajón ({e})"
