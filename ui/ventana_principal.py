"""
Ventana principal del POS.

Contiene una pestaña por módulo, indicador global de alerta de stock bajo
y ejecuta el respaldo automático al cerrar la ventana (Fase 8).

Atajos de teclado:
    F1  Ventas        F6  Inventario    F7  Devoluciones
    F9  Caja          F10 Reportes      F11 Ajustes
(F2, F3, F4, F5, F8 y F12 se usan dentro de la pantalla de ventas.)
"""

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame, QInputDialog, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QTabWidget,
)

from modules import ajustes, auth, caja, inventario, respaldos
from ui.estilos import aplicar_tamano_texto_listas
from ui.pantalla_ajustes import PantallaAjustes
from ui.pantalla_caja import PantallaCaja
from ui.pantalla_devoluciones import PantallaDevoluciones
from ui.pantalla_inventario import PantallaInventario
from ui.pantalla_precios import PantallaPrecios
from ui.pantalla_reportes import PantallaReportes
from ui.pantalla_ventas import PantallaVentas


class VentanaPrincipal(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(640, 480)
        self.resize(1200, 720)
        self._respaldo_cierre_realizado = False
        self._maximizacion_inicial_aplicada = False
        self._indice_pestana_anterior = 0
        self._verificando_acceso_precios = False

        self.pestanas = QTabWidget()
        self.setCentralWidget(self.pestanas)

        self.pantalla_ventas = PantallaVentas()
        self.pantalla_inventario = PantallaInventario()
        self.pantalla_precios = PantallaPrecios()
        self.pantalla_devoluciones = PantallaDevoluciones()
        self.pantalla_caja = PantallaCaja()
        self.pantalla_reportes = PantallaReportes()
        self.pantalla_ajustes = PantallaAjustes()

        self.pantalla_ajustes.nombre_tienda_cambiado.connect(self._actualizar_titulo)
        self.pantalla_ajustes.base_datos_restaurada.connect(self._al_restaurar_base_datos)
        self.pantalla_inventario.inventario_actualizado.connect(self.actualizar_indicadores_globales)
        self.pantalla_ventas.venta_registrada.connect(self.actualizar_indicadores_globales)
        self.pantalla_devoluciones.devolucion_registrada.connect(self.actualizar_indicadores_globales)
        self.pantalla_caja.turno_cambiado.connect(self.pantalla_devoluciones.recargar_todo)
        self.pantalla_caja.turno_cambiado.connect(self.pantalla_reportes.recargar)
        self.pantalla_caja.turno_cambiado.connect(self.pantalla_ajustes.recargar_lista_respaldos)

        modulos = [
            ("Ventas", self.pantalla_ventas, "F1"),
            ("Inventario", self.pantalla_inventario, "F6"),
            ("Precios", self.pantalla_precios, None),
            ("Devoluciones", self.pantalla_devoluciones, "F7"),
            ("Caja", self.pantalla_caja, "F9"),
            ("Reportes", self.pantalla_reportes, "F10"),
            ("Ajustes", self.pantalla_ajustes, "F11"),
        ]

        for indice, (texto, widget, atajo) in enumerate(modulos):
            etiqueta = f"{texto} ({atajo})" if atajo else texto
            area = QScrollArea()
            area.setWidget(widget)
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.NoFrame)
            self.pestanas.addTab(area, etiqueta)
            if atajo:
                sc = QShortcut(QKeySequence(atajo), self)
                sc.setContext(Qt.ApplicationShortcut)
                sc.activated.connect(lambda i=indice: self.pestanas.setCurrentIndex(i))

        # Botón de alerta rápida de stock bajo en la esquina superior derecha de las pestañas
        self.btn_alerta_global = QPushButton()
        self.btn_alerta_global.setCursor(Qt.PointingHandCursor)
        self.btn_alerta_global.setStyleSheet(
            "QPushButton { background-color: #f59e0b; color: #ffffff; font-weight: bold; "
            "border: none; border-radius: 5px; padding: 5px 12px; margin: 3px 6px; }"
            "QPushButton:hover { background-color: #d97706; }"
        )
        self.btn_alerta_global.clicked.connect(self._ir_a_stock_bajo)
        self.pestanas.setCornerWidget(self.btn_alerta_global, Qt.TopRightCorner)

        self.pestanas.currentChanged.connect(self._al_cambiar_pestana)

        # Abrimos en Ventas (F1)
        self.pestanas.setCurrentIndex(0)

        self._actualizar_titulo(ajustes.obtener("nombre_tienda"))
        self.actualizar_indicadores_globales()
        aplicar_tamano_texto_listas(ajustes.obtener_entero("tamano_texto_listas"))

    def _actualizar_titulo(self, nombre: str) -> None:
        self.setWindowTitle(f"POS - {nombre}")

    def _al_cambiar_pestana(self, indice: int) -> None:
        self.actualizar_indicadores_globales()
        if self._verificando_acceso_precios:
            return
        if indice == 2 and ajustes.obtener_booleano("proteger_precios"):
            self._verificando_acceso_precios = True
            self.pantalla_precios.setVisible(False)
            try:
                clave, ok = QInputDialog.getText(
                    self,
                    "Acceso protegido",
                    "Ingrese la contraseña del sistema para abrir Precios:",
                    QLineEdit.Password,
                )
                if ok and auth.verificar_clave(clave):
                    self.pantalla_precios.setVisible(True)
                    self._indice_pestana_anterior = indice
                else:
                    if ok:
                        QMessageBox.warning(self, "Acceso denegado", "Contraseña incorrecta.")
                    self.pestanas.blockSignals(True)
                    self.pestanas.setCurrentIndex(self._indice_pestana_anterior)
                    self.pestanas.blockSignals(False)
                    self.pantalla_precios.setVisible(True)
            finally:
                self._verificando_acceso_precios = False
            return
        self._indice_pestana_anterior = indice

    def actualizar_indicadores_globales(self) -> None:
        """Actualiza el contador de stock bajo en la pestaña Inventario y en el botón de alerta."""
        bajos = inventario.contar_stock_bajo()
        if bajos > 0:
            self.pestanas.setTabText(1, f"Inventario (F6) ⚠ {bajos}")
            plural = "producto con stock bajo" if bajos == 1 else "productos con stock bajo"
            self.btn_alerta_global.setText(f"⚠ {bajos} {plural} (ver)")
            self.btn_alerta_global.setVisible(True)
        else:
            self.pestanas.setTabText(1, "Inventario (F6)")
            self.btn_alerta_global.setVisible(False)

    def _ir_a_stock_bajo(self) -> None:
        self.pantalla_inventario.chk_stock_bajo.setChecked(True)
        self.pestanas.setCurrentIndex(1)

    def _al_restaurar_base_datos(self) -> None:
        """Refresca todas las pantallas después de restaurar un respaldo."""
        self.pantalla_inventario.recargar()
        self.pantalla_precios.cargar_configuracion_redondeo()
        self.pantalla_precios.recargar()
        self.pantalla_devoluciones.recargar_todo()
        self.pantalla_caja.recargar()
        self.pantalla_reportes.recargar()
        self.actualizar_indicadores_globales()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._maximizacion_inicial_aplicada:
            self._maximizacion_inicial_aplicada = True
            QTimer.singleShot(0, self.showMaximized)

    def closeEvent(self, event) -> None:
        """Consulta si desea hacer cierre de caja antes de salir y ejecuta el respaldo automático."""
        turno_abierto = caja.obtener_turno_abierto()
        if turno_abierto is not None:
            cuadro = QMessageBox(self)
            cuadro.setIcon(QMessageBox.Question)
            cuadro.setWindowTitle("Cierre de caja pendiente")
            cuadro.setText(
                f"El Turno #{turno_abierto['id']} de caja todavía está abierto.\n\n"
                "¿Desea realizar el cierre de caja antes de cerrar la aplicación?"
            )
            btn_ir_cierre = cuadro.addButton("Sí, ir a cerrar caja", QMessageBox.AcceptRole)
            btn_salir = cuadro.addButton("Salir sin cerrar caja", QMessageBox.DestructiveRole)
            cuadro.addButton("Cancelar", QMessageBox.RejectRole)
            cuadro.setDefaultButton(btn_ir_cierre)
            cuadro.exec()

            elegido = cuadro.clickedButton()
            if elegido == btn_ir_cierre:
                event.ignore()
                self.pestanas.setCurrentIndex(4)
                self.pantalla_caja.enfocar_cierre()
                return
            if elegido != btn_salir:
                event.ignore()
                return

        if not self._respaldo_cierre_realizado:
            respaldos.respaldar_si_corresponde_al_cerrar()
            self._respaldo_cierre_realizado = True
        super().closeEvent(event)
