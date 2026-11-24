"""
Script independiente de diagnóstico del cajón monedero (Fase 9).

Permite probar el cajón monedero conectado por RJ11 a un convertidor USB
SIN necesidad de abrir todo el POS.

Cómo ejecutarlo en Windows (PowerShell dentro de la carpeta pos):
    .\.venv\Scripts\python.exe scripts\probar_cajon.py
"""

import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from database.conexion import cerrar_conexion  # noqa: E402
from database.migraciones import inicializar_base_datos  # noqa: E402
from hardware import cajon  # noqa: E402
from modules import ajustes  # noqa: E402


def main() -> int:
    inicializar_base_datos()
    print("=" * 68)
    print("  DIAGNÓSTICO DE CAJÓN MONEDERO (RJ11 -> CONVERTIDOR USB)")
    print("=" * 68)

    puertos = cajon.listar_puertos_disponibles()
    if puertos:
        print("\nPuertos seriales / USB detectados en este computador:")
        for i, p in enumerate(puertos, start=1):
            print(f"  {i}. {p['descripcion']}   [{p['hwid']}]")
        sugerido = puertos[0]["dispositivo"]
    else:
        print("\n⚠ No se detectó ningún convertidor USB-Serial conectado en este momento.")
        print("  (Conecte el convertidor USB y vuelva a ejecutar, o escriba el puerto manualmente).")
        sugerido = ajustes.obtener("cajon_puerto") or "COM3"

    puerto = input(f"\nPuerto a probar [{sugerido}]: ").strip() or sugerido

    print("\nModos de prueba:")
    print("  1. Probar automáticamente los 3 pulsos más comunes (ESC/POS Pin 2, Pin 5 y Pulso USB-RJ11)")
    print("  2. Escribir un comando hexadecimal personalizado")
    modo_op = input("\nElija 1 o 2 [1]: ").strip() or "1"

    if modo_op == "2":
        hex_cmd = input("Escriba los bytes en hexadecimal [1B 70 00 19 FA]: ").strip() or "1B 70 00 19 FA"
        baudios = int(input("Velocidad en baudios [9600]: ").strip() or "9600")
        cfg = {
            "activo": True,
            "modo": "serial",
            "puerto": puerto,
            "baudios": baudios,
            "comando": "personalizado",
            "hex_personalizado": hex_cmd,
        }
        ok, msg = cajon.abrir_cajon(config_override=cfg, forzar=True)
        print(f"\nResultado: {'✓ ÉXITO' if ok else '✗ FALLÓ'} — {msg}")
    else:
        pruebas = [
            ("escpos_pin2", 9600, "Pulso 1: Estándar ESC/POS Pin 2 (9600 baudios) + DTR/RTS"),
            ("escpos_pin5", 9600, "Pulso 2: Estándar ESC/POS Pin 5 (9600 baudios) + DTR/RTS"),
            ("pulso_usb", 9600, "Pulso 3: Disparador USB-RJ11 directo (00 FF) + DTR/RTS"),
        ]
        for codigo_cmd, baudios, descripcion in pruebas:
            print(f"\n-> Enviando {descripcion}...")
            cfg = {
                "activo": True,
                "modo": "serial",
                "puerto": puerto,
                "baudios": baudios,
                "comando": codigo_cmd,
                "hex_personalizado": "",
            }
            ok, msg = cajon.abrir_cajon(config_override=cfg, forzar=True)
            print(f"   Resultado: {'✓ Enviado' if ok else '✗ Error'} — {msg}")
            time.sleep(0.8)

    guardar = input("\n¿Desea dejar guardado este puerto en los ajustes del POS? (s/n) [n]: ").strip().lower()
    if guardar in ("s", "si", "sí"):
        ajustes.guardar_varios({"cajon_puerto": puerto, "cajon_activo": True})
        print(f"✓ Puerto {puerto} guardado y cajón activado en el POS.")

    cerrar_conexion()
    return 0


if __name__ == "__main__":
    sys.exit(main())
