"""
Diálogo rápido para abrir turno de caja con fondo inicial.
Se puede invocar tanto desde la pestaña Caja (F9) como al intentar cobrar en Ventas (F1)
sin haber abierto turno.
"""

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout,
)

from modules import caja
from ui.comun import activar_formato_miles
from utils.dinero import parsear_pesos


class DialogoAbrirTurno(QDialog):
    def __init__(self, parent=None, mensaje_extra: str = ""):
        super().__init__(parent)
        self.turno_id: int | None = None
        self.setWindowTitle("Abrir turno de caja")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        if mensaje_extra:
            lbl_extra = QLabel(mensaje_extra)
            lbl_extra.setStyleSheet("color: #1e3a8a; font-weight: bold;")
            lbl_extra.setWordWrap(True)
            layout.addWidget(lbl_extra)

        form = QFormLayout()
        self.txt_fondo = QLineEdit("0")
        self.txt_fondo.setPlaceholderText("Ej: 50.000")
        self.txt_fondo.setStyleSheet("font-size: 14pt; font-weight: bold;")
        activar_formato_miles(self.txt_fondo)
        self.txt_fondo.returnPressed.connect(self._aceptar)
        form.addRow("Base en efectivo ($):", self.txt_fondo)
        layout.addLayout(form)

        ayuda = QLabel("Ingrese la base de efectivo con la que inicia el cajón hoy.")
        ayuda.setStyleSheet("color: #64748b;")
        ayuda.setWordWrap(True)
        layout.addWidget(ayuda)

        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Abrir turno (Enter)")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar (Esc)")
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)

        self.txt_fondo.selectAll()
        self.txt_fondo.setFocus()

    def _aceptar(self) -> None:
        try:
            fondo = parsear_pesos(self.txt_fondo.text() or "0")
        except ValueError:
            QMessageBox.warning(
                self,
                "Fondo inicial",
                "Escriba un monto válido en pesos sin decimales (ej. 50.000 o 0).",
            )
            self.txt_fondo.setFocus()
            return
        try:
            self.turno_id = caja.abrir_turno(fondo)
        except caja.ErrorCaja as e:
            QMessageBox.warning(self, "Abrir turno", str(e))
            return
        self.accept()
