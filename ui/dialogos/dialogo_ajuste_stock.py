"""
Diálogo de ajuste manual de stock (ingreso de mercancía, merma o corrección).
"""

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox,
    QVBoxLayout,
)

from modules import inventario
from ui.comun import activar_formato_miles, enter_pasa_al_siguiente
from utils.peso import libras_a_gramos


class DialogoAjusteStock(QDialog):
    def __init__(self, parent, producto: dict):
        super().__init__(parent)
        self.producto = producto
        self.peso = producto["tipo_venta"] == "peso"
        self.setWindowTitle("Ajustar stock")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        titulo = QLabel(producto["nombre"])
        titulo.setStyleSheet("font-size: 14pt; font-weight: bold;")
        layout.addWidget(titulo)

        form = QFormLayout()
        layout.addLayout(form)
        form.addRow("Stock actual:", QLabel(inventario.formatear_stock(producto["tipo_venta"], producto["stock"])))

        self.cmb_tipo = QComboBox()
        for clave, texto in inventario.TIPOS_AJUSTE.items():
            self.cmb_tipo.addItem(texto, clave)
        form.addRow("Tipo de ajuste:", self.cmb_tipo)

        self.txt_cantidad = QLineEdit()
        self.txt_cantidad.setPlaceholderText("Ej: 2,5" if self.peso else "Ej: 12")
        activar_formato_miles(self.txt_cantidad, permitir_coma_decimal=self.peso)
        form.addRow("Cantidad (libras):" if self.peso else "Cantidad (unidades):", self.txt_cantidad)

        self.txt_motivo = QLineEdit()
        self.txt_motivo.setPlaceholderText("Opcional: proveedor, factura, detalle...")
        self.txt_motivo.setMaxLength(200)
        form.addRow("Motivo / nota:", self.txt_motivo)

        self.lbl_resultado = QLabel("—")
        self.lbl_resultado.setStyleSheet("font-weight: bold;")
        form.addRow("Stock quedará en:", self.lbl_resultado)

        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Save).setText("Guardar (Ctrl+S)")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar (Esc)")
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._guardar)

        self.cmb_tipo.currentIndexChanged.connect(self._previsualizar)
        self.txt_cantidad.textChanged.connect(self._previsualizar)
        enter_pasa_al_siguiente(self)
        self.txt_cantidad.setFocus()

    def _cantidad(self) -> int:
        texto = self.txt_cantidad.text().strip()
        if self.peso:
            return libras_a_gramos(texto)
        limpio = texto.replace(".", "")
        if not limpio.isdigit():
            raise ValueError("Use un número entero de unidades.")
        return int(limpio)

    def _previsualizar(self) -> None:
        try:
            cantidad = self._cantidad()
        except ValueError:
            self.lbl_resultado.setText("—")
            return
        actual = self.producto["stock"]
        tipo = self.cmb_tipo.currentData()
        nuevo = {"ingreso": actual + cantidad, "merma": actual - cantidad, "correccion": cantidad}[tipo]
        texto = inventario.formatear_stock(self.producto["tipo_venta"], nuevo)
        if nuevo < 0:
            texto += "  ⚠ no puede quedar negativo"
        self.lbl_resultado.setText(texto)

    def _guardar(self) -> None:
        try:
            cantidad = self._cantidad()
            inventario.ajustar_stock(self.producto["id"], self.cmb_tipo.currentData(),
                                     cantidad, self.txt_motivo.text())
        except ValueError as e:
            QMessageBox.warning(self, "Ajustar stock", f"Cantidad no válida. {e}")
            return
        except inventario.ErrorInventario as e:
            QMessageBox.warning(self, "Ajustar stock", "\n".join(e.errores))
            return
        self.accept()
