"""
Diálogo para recuperar o descartar una venta en espera (F5).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from modules.ventas import GestorVentasEnEspera, VentaEnEspera
from utils.dinero import formatear_pesos

_ENCABEZADOS = ["#", "Hora", "Nota", "Productos", "Total"]


class DialogoVentasEspera(QDialog):
    def __init__(self, parent, gestor: GestorVentasEnEspera):
        super().__init__(parent)
        self.gestor = gestor
        self.venta_recuperada: VentaEnEspera | None = None
        self.setWindowTitle("Ventas en espera (F5)")
        self.resize(740, 400)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Seleccione una venta pausada para retomarla (Enter o doble clic):"))

        self.tabla = QTableWidget(0, len(_ENCABEZADOS))
        self.tabla.setHorizontalHeaderLabels(_ENCABEZADOS)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tabla.cellDoubleClicked.connect(lambda *_: self._recuperar())
        layout.addWidget(self.tabla)

        abajo = QHBoxLayout()
        self.btn_eliminar = QPushButton("Descartar seleccionada")
        self.btn_eliminar.clicked.connect(self._eliminar)
        abajo.addWidget(self.btn_eliminar)
        abajo.addStretch()

        self.btn_recuperar = QPushButton("Recuperar venta (Enter)")
        self.btn_recuperar.setDefault(True)
        self.btn_recuperar.setMinimumHeight(34)
        self.btn_recuperar.setStyleSheet(
            "QPushButton { background-color: #1e40af; color: white; font-weight: bold; }"
        )
        self.btn_recuperar.clicked.connect(self._recuperar)
        btn_cerrar = QPushButton("Cerrar (Esc)")
        btn_cerrar.setMinimumHeight(34)
        btn_cerrar.clicked.connect(self.reject)
        abajo.addWidget(self.btn_recuperar)
        abajo.addWidget(btn_cerrar)
        layout.addLayout(abajo)

        self._recargar()

    def _recargar(self) -> None:
        lista = self.gestor.listar()
        self.tabla.setRowCount(len(lista))
        for i, v in enumerate(lista):
            nombres = ", ".join(it.nombre for it in v.carrito.items[:3])
            if len(v.carrito.items) > 3:
                nombres += f" (+{len(v.carrito.items) - 3} más)"
            valores = [
                f"#{v.numero}",
                v.hora,
                v.nota or "—",
                f"{len(v.carrito.items)} ítem(s): {nombres}",
                formatear_pesos(v.carrito.total()),
            ]
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col == 4:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla.setItem(i, col, item)
        if lista:
            self.tabla.selectRow(0)
        hay = bool(lista)
        self.btn_recuperar.setEnabled(hay)
        self.btn_eliminar.setEnabled(hay)

    def _recuperar(self) -> None:
        fila = self.tabla.currentRow()
        if 0 <= fila < self.gestor.cantidad():
            self.venta_recuperada = self.gestor.recuperar(fila)
            self.accept()

    def _eliminar(self) -> None:
        fila = self.tabla.currentRow()
        if 0 <= fila < self.gestor.cantidad():
            self.gestor.eliminar(fila)
            self._recargar()
