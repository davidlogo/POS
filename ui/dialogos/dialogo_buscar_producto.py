"""
Diálogo de búsqueda rápida de productos por nombre o código (F2 en Ventas).

Pensado para operar 100 % con teclado:
  - Al abrir, el cursor está en el buscador.
  - Las flechas Arriba/Abajo mueven la selección de la tabla sin perder el texto.
  - Enter agrega el producto seleccionado al carrito.
"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from modules import inventario
from utils.dinero import formatear_pesos

_ENCABEZADOS = ["Código", "Nombre", "Categoría", "Tipo", "Precio", "Stock"]


class DialogoBuscarProducto(QDialog):
    def __init__(self, parent=None, texto_inicial: str = ""):
        super().__init__(parent)
        self.producto_elegido: dict | None = None
        self.productos: list[dict] = []
        self.setWindowTitle("Buscar producto (F2)")
        self.resize(820, 480)

        layout = QVBoxLayout(self)

        fila_busq = QHBoxLayout()
        fila_busq.addWidget(QLabel("Buscar producto:"))
        self.txt_buscar = QLineEdit(texto_inicial)
        self.txt_buscar.setPlaceholderText("Escriba parte del nombre o código... (Flechas ↑↓ y Enter para elegir)")
        self.txt_buscar.setClearButtonEnabled(True)
        self.txt_buscar.textChanged.connect(self._filtrar)
        self.txt_buscar.returnPressed.connect(self._elegir_actual)
        self.txt_buscar.installEventFilter(self)
        fila_busq.addWidget(self.txt_buscar, stretch=1)
        layout.addLayout(fila_busq)

        self.tabla = QTableWidget(0, len(_ENCABEZADOS))
        self.tabla.setHorizontalHeaderLabels(_ENCABEZADOS)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.cellDoubleClicked.connect(lambda *_: self._elegir_actual())
        layout.addWidget(self.tabla)

        abajo = QHBoxLayout()
        lbl_ayuda = QLabel("↑ / ↓ para moverse · Enter o doble clic para agregar · Esc para cerrar")
        lbl_ayuda.setStyleSheet("color: #64748b;")
        abajo.addWidget(lbl_ayuda)
        abajo.addStretch()

        self.btn_agregar = QPushButton("Seleccionar (Enter)")
        self.btn_agregar.setMinimumHeight(34)
        self.btn_agregar.setStyleSheet(
            "QPushButton { background-color: #1e40af; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        self.btn_agregar.clicked.connect(self._elegir_actual)
        btn_cancelar = QPushButton("Cancelar (Esc)")
        btn_cancelar.setMinimumHeight(34)
        btn_cancelar.clicked.connect(self.reject)
        abajo.addWidget(self.btn_agregar)
        abajo.addWidget(btn_cancelar)
        layout.addLayout(abajo)

        self._filtrar()
        self.txt_buscar.setFocus()

    def eventFilter(self, obj, event) -> bool:
        """Permite mover la fila seleccionada con las flechas ↑/↓ sin salir del campo de búsqueda."""
        if obj is self.txt_buscar and event.type() == QEvent.KeyPress:
            tecla = event.key()
            if tecla in (Qt.Key_Down, Qt.Key_Up) and self.tabla.rowCount() > 0:
                actual = max(0, self.tabla.currentRow())
                nueva = actual + (1 if tecla == Qt.Key_Down else -1)
                nueva = max(0, min(self.tabla.rowCount() - 1, nueva))
                self.tabla.selectRow(nueva)
                return True
        return super().eventFilter(obj, event)

    def _filtrar(self) -> None:
        self.productos = inventario.buscar(texto=self.txt_buscar.text(), incluir_inactivos=False)
        self.tabla.setRowCount(len(self.productos))
        for i, p in enumerate(self.productos):
            es_peso = p["tipo_venta"] == "peso"
            sufijo = " / lb" if es_peso else ""
            valores = [
                p["codigo_barras"] or "—",
                p["nombre"],
                p["categoria"] or "—",
                "Peso (lb)" if es_peso else "Unidad",
                formatear_pesos(p["precio_final"]) + sufijo,
                inventario.formatear_stock(p["tipo_venta"], p["stock"]),
            ]
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col in (4, 5):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla.setItem(i, col, item)

        if self.productos:
            self.tabla.selectRow(0)
        self.btn_agregar.setEnabled(bool(self.productos))

    def _elegir_actual(self) -> None:
        fila = self.tabla.currentRow()
        if 0 <= fila < len(self.productos):
            self.producto_elegido = self.productos[fila]
            self.accept()
