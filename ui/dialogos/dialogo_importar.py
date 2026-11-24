"""
Vista previa de la importación.

Muestra cada fila del archivo con su estado:
  - Nuevo (verde): se creará.
  - Existente (amarillo): el código ya existe -> elegir Actualizar o Saltar.
  - Error (rojo): no se importará; la columna Observaciones dice por qué.
Nada se guarda hasta pulsar "Importar".
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from modules import importar_exportar as imp
from modules import inventario
from utils.dinero import formatear_pesos
from utils.porcentajes import porcentaje_a_texto

# Colores con texto oscuro (legibles en tema claro y oscuro)
_COLORES = {
    "nuevo": ("#d4edda", "#155724"),
    "existente": ("#fff3cd", "#856404"),
    "error": ("#f8d7da", "#721c24"),
}

_ENCABEZADOS = ["Fila", "Acción", "Código", "Nombre", "Categoría", "Tipo", "Costo",
                "% Gan.", "% IVA", "Precio", "Stock", "Stock mín.", "Observaciones"]


class DialogoImportar(QDialog):
    def __init__(self, parent, filas: list[imp.FilaImportacion], nombre_archivo: str):
        super().__init__(parent)
        self.filas = filas
        self.resultado = None
        self.setWindowTitle(f"Importar productos – {nombre_archivo}")
        self.resize(1200, 600)

        layout = QVBoxLayout(self)
        self.lbl_resumen = QLabel()
        self.lbl_resumen.setStyleSheet("font-size: 12pt;")
        self.lbl_resumen.setWordWrap(True)
        layout.addWidget(self.lbl_resumen)

        # Botones para decidir sobre todos los existentes a la vez
        fila_botones = QHBoxLayout()
        self.btn_actualizar_todos = QPushButton("Actualizar todos los existentes")
        self.btn_saltar_todos = QPushButton("Saltar todos los existentes")
        self.btn_actualizar_todos.clicked.connect(lambda: self._decidir_todos("actualizar"))
        self.btn_saltar_todos.clicked.connect(lambda: self._decidir_todos("saltar"))
        fila_botones.addWidget(self.btn_actualizar_todos)
        fila_botones.addWidget(self.btn_saltar_todos)
        fila_botones.addStretch()
        layout.addLayout(fila_botones)

        self.tabla = QTableWidget(len(filas), len(_ENCABEZADOS))
        self.tabla.setHorizontalHeaderLabels(_ENCABEZADOS)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionMode(QTableWidget.NoSelection)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.tabla)

        self.combos: dict[int, QComboBox] = {}
        for i, f in enumerate(filas):
            self._llenar_fila(i, f)

        # Botones finales
        abajo = QHBoxLayout()
        abajo.addStretch()
        self.btn_importar = QPushButton("Importar")
        self.btn_importar.setMinimumHeight(34)
        self.btn_importar.clicked.connect(self._importar)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.reject)
        abajo.addWidget(self.btn_importar)
        abajo.addWidget(btn_cancelar)
        layout.addLayout(abajo)

        hay_existentes = any(f.existente and f.accion != "error" for f in filas)
        self.btn_actualizar_todos.setVisible(hay_existentes)
        self.btn_saltar_todos.setVisible(hay_existentes)
        self._actualizar_resumen()

    # -----------------------------------------------------------------
    def _llenar_fila(self, i: int, f: imp.FilaImportacion) -> None:
        d = f.final
        tipo = d.get("tipo_venta") or "unidad"

        def cantidad(clave):
            v = d.get(clave)
            return "" if v is None else inventario.formatear_stock(tipo, v)

        valores = [
            str(f.numero), "",
            d.get("codigo_barras") or "",
            d.get("nombre") or "",
            d.get("categoria") or "",
            tipo,
            formatear_pesos(d["costo"]) if d.get("costo") is not None else "",
            porcentaje_a_texto(d["ganancia_pct"]) if d.get("ganancia_pct") is not None else "",
            porcentaje_a_texto(d["iva_pct"]) if d.get("iva_pct") is not None else "",
            formatear_pesos(f.precio) if f.precio is not None else "",
            cantidad("stock"),
            cantidad("stock_minimo"),
            " | ".join(f.errores or f.observaciones),
        ]

        if f.accion == "error":
            estado, texto_accion = "error", "Error"
        elif f.existente:
            estado, texto_accion = "existente", None
        else:
            estado, texto_accion = "nuevo", "Nuevo"
        fondo, letra = _COLORES[estado]

        for col, valor in enumerate(valores):
            item = QTableWidgetItem(valor)
            item.setBackground(QBrush(QColor(fondo)))
            item.setForeground(QBrush(QColor(letra)))
            if col == 1 and texto_accion:
                item.setText(texto_accion)
            self.tabla.setItem(i, col, item)

        if estado == "existente":
            combo = QComboBox()
            combo.addItem("Saltar", "saltar")
            combo.addItem("Actualizar", "actualizar")
            combo.setCurrentIndex(combo.findData(f.accion))
            combo.currentIndexChanged.connect(lambda _, fila=f, c=combo: self._cambiar_accion(fila, c))
            self.tabla.setCellWidget(i, 1, combo)
            self.combos[i] = combo

    def _cambiar_accion(self, fila: imp.FilaImportacion, combo: QComboBox) -> None:
        fila.accion = combo.currentData()
        self._actualizar_resumen()

    def _decidir_todos(self, accion: str) -> None:
        for i, combo in self.combos.items():
            combo.setCurrentIndex(combo.findData(accion))  # dispara _cambiar_accion

    def _actualizar_resumen(self) -> None:
        r = imp.resumen(self.filas)
        partes = [f"<b>{len(self.filas)}</b> filas leídas:",
                  f"<span style='color:#28a745'><b>{r['nuevo']}</b> nuevos</span>"]
        if r["existente"]:
            partes.append(f"<span style='color:#d39e00'><b>{r['existente']}</b> ya existen "
                          f"({r['actualizar']} actualizar, {r['saltar']} saltar)</span>")
        if r["error"]:
            partes.append(f"<span style='color:#dc3545'><b>{r['error']}</b> con errores "
                          f"(no se importarán)</span>")
        self.lbl_resumen.setText(" · ".join(partes))
        a_guardar = r["nuevo"] + r["actualizar"]
        self.btn_importar.setText(f"Importar ({a_guardar} productos)")
        self.btn_importar.setEnabled(a_guardar > 0)

    def _importar(self) -> None:
        r = imp.resumen(self.filas)
        mensaje = f"Se crearán {r['nuevo']} productos y se actualizarán {r['actualizar']}."
        if r["error"]:
            mensaje += f"\n{r['error']} filas con errores NO se importarán."
        mensaje += "\n\n¿Continuar?"
        if QMessageBox.question(self, "Confirmar importación", mensaje) != QMessageBox.Yes:
            return
        try:
            self.resultado = imp.aplicar_importacion(self.filas)
        except Exception as e:  # noqa: BLE001 - la transacción ya deshizo todo
            QMessageBox.critical(self, "Importación cancelada",
                                 f"Ocurrió un error y NO se guardó ningún cambio:\n\n{e}")
            return
        self.accept()
