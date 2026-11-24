import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from database.conexion import cerrar_conexion
from database.migraciones import inicializar_base_datos
from modules import ajustes, respaldos
from ui.comun import activar_mayusculas_en_entradas
from ui.estilos import HOJA_ESTILOS, aplicar_tamano_texto_listas, aplicar_tema_claro


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("POS")

    # Letra cómoda para leer en la caja + tema claro forzado (evita cuadros negros si Windows está en modo oscuro)
    aplicar_tema_claro(app)
    fuente = QFont(app.font())
    fuente.setPointSize(11)
    app.setFont(fuente)
    app.setStyleSheet(HOJA_ESTILOS)
    activar_mayusculas_en_entradas(app)

    # 1. Base de datos: crear/actualizar tablas
    try:
        inicializar_base_datos()
    except Exception as e:  # noqa: BLE001 - mostramos cualquier error al usuario
        QMessageBox.critical(None, "Error", f"No se pudo abrir la base de datos:\n\n{e}")
        return 1

    # Aplicar tamaño de texto de listas configurado por el usuario
    try:
        aplicar_tamano_texto_listas(ajustes.obtener_entero("tamano_texto_listas"))
    except Exception:  # noqa: BLE001
        pass

    # 2. Respaldo opcional al abrir el programa (Fase 8)
    respaldos.respaldar_si_corresponde_al_abrir()

    # Importamos las pantallas después de preparar la base de datos
    from ui.login import DialogoLogin
    from ui.ventana_principal import VentanaPrincipal

    # 3. Login (o creación de contraseña en la primera ejecución)
    login = DialogoLogin()
    if login.exec() != QDialog.Accepted:
        cerrar_conexion()
        return 0

    # 4. Ventana principal
    ventana = VentanaPrincipal()
    ventana.showMaximized()

    codigo = app.exec()

    # 5. Si por alguna razón no se ejecutó en closeEvent, respaldamos antes de cerrar conexión
    if not getattr(ventana, "_respaldo_cierre_realizado", False):
        respaldos.respaldar_si_corresponde_al_cerrar()

    cerrar_conexion()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
