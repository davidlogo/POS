"""
Pantalla de Inventario.

Permite:
  - Buscar por nombre o código de barras (en vivo).
  - Filtrar inactivos y productos con stock bajo.
  - Ver banda de alerta cuando hay productos con stock <= stock mínimo.
  - Crear, editar, ajustar stock y desactivar/reactivar productos.
  - Descargar plantilla Excel, importar desde Excel/CSV (con vista previa) y exportar a Excel.
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modules import importar_exportar as imp
from modules import inventario
from ui.comun import FlowLayout
from ui.dialogos.dialogo_ajuste_stock import DialogoAjusteStock
from ui.dialogos.dialogo_importar import DialogoImportar
from ui.dialogos.dialogo_producto import DialogoProducto
from utils.dinero import formatear_pesos
from utils.porcentajes import porcentaje_a_texto

_ENCABEZADOS = [
    "Código",
    "Nombre",
    "Categoría",
    "Tipo",
    "% IVA",
    "Precio final",
    "Stock",
    "Stock mín.",
    "Estado",
]


class PantallaInventario(QWidget):
    inventario_actualizado = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.productos: list[dict] = []

        layout = QVBoxLayout(self)

        # ---------------- Banda de alerta de stock bajo ----------------
        self.marco_alerta = QFrame()
        self.marco_alerta.setStyleSheet(
            "QFrame { background-color: #fff3cd; border: 1px solid #ffeeba; border-radius: 4px; }"
            "QLabel { color: #856404; font-weight: bold; border: none; }"
        )
        fila_alerta = QHBoxLayout(self.marco_alerta)
        fila_alerta.setContentsMargins(10, 6, 10, 6)
        self.lbl_alerta = QLabel()
        self.btn_ver_bajo = QPushButton("Ver productos con stock bajo")
        self.btn_ver_bajo.setStyleSheet(
            "background-color: #856404; color: white; padding: 4px 10px; border-radius: 3px;"
        )
        self.btn_ver_bajo.clicked.connect(self._activar_filtro_stock_bajo)
        fila_alerta.addWidget(self.lbl_alerta)
        fila_alerta.addStretch()
        fila_alerta.addWidget(self.btn_ver_bajo)
        layout.addWidget(self.marco_alerta)

        # ---------------- Barra de búsqueda y filtros ----------------
        fila_busqueda = QHBoxLayout()
        self.txt_buscar = QLineEdit()
        self.txt_buscar.setPlaceholderText("Buscar por nombre o código de barras...")
        self.txt_buscar.setClearButtonEnabled(True)
        self.txt_buscar.textChanged.connect(self.recargar)
        fila_busqueda.addWidget(QLabel("Buscar:"))
        fila_busqueda.addWidget(self.txt_buscar, stretch=1)

        self.chk_stock_bajo = QCheckBox("Solo stock bajo")
        self.chk_stock_bajo.toggled.connect(self.recargar)
        fila_busqueda.addWidget(self.chk_stock_bajo)

        self.chk_inactivos = QCheckBox("Mostrar desactivados")
        self.chk_inactivos.toggled.connect(self.recargar)
        fila_busqueda.addWidget(self.chk_inactivos)

        layout.addLayout(fila_busqueda)

        # ---------------- Botones de acción (principales a la izq., Plantilla/Importar a la der.) ----------------
        barra_acciones = QHBoxLayout()
        barra_acciones.setSpacing(8)

        fila_acciones_izq = FlowLayout(margin=0, h_spacing=6, v_spacing=6)

        self.btn_nuevo = QPushButton("+ Nuevo producto")
        self.btn_nuevo.setMinimumHeight(32)
        self.btn_nuevo.clicked.connect(self._nuevo_producto)
        fila_acciones_izq.addWidget(self.btn_nuevo)

        self.btn_editar = QPushButton("Editar")
        self.btn_editar.setMinimumHeight(32)
        self.btn_editar.clicked.connect(self._editar_producto)
        fila_acciones_izq.addWidget(self.btn_editar)

        self.btn_stock = QPushButton("Ajustar stock")
        self.btn_stock.setMinimumHeight(32)
        self.btn_stock.clicked.connect(self._ajustar_stock)
        fila_acciones_izq.addWidget(self.btn_stock)

        self.btn_activar = QPushButton("Desactivar")
        self.btn_activar.setMinimumHeight(32)
        self.btn_activar.clicked.connect(self._cambiar_activo)
        fila_acciones_izq.addWidget(self.btn_activar)

        barra_acciones.addLayout(fila_acciones_izq, stretch=1)

        fila_acciones_der = QHBoxLayout()
        fila_acciones_der.setSpacing(6)

        self.btn_plantilla = QPushButton("Plantilla Excel")
        self.btn_plantilla.setMinimumHeight(32)
        self.btn_plantilla.clicked.connect(self._descargar_plantilla)
        fila_acciones_der.addWidget(self.btn_plantilla)

        self.btn_importar = QPushButton("Importar Excel / CSV")
        self.btn_importar.setMinimumHeight(32)
        self.btn_importar.clicked.connect(self._importar)
        fila_acciones_der.addWidget(self.btn_importar)

        barra_acciones.addLayout(fila_acciones_der)
        layout.addLayout(barra_acciones)

        # ---------------- Tabla de productos ----------------
        self.tabla = QTableWidget(0, len(_ENCABEZADOS))
        self.tabla.setHorizontalHeaderLabels(_ENCABEZADOS)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.itemSelectionChanged.connect(self._actualizar_botones)
        self.tabla.cellDoubleClicked.connect(lambda *_: self._editar_producto())
        layout.addWidget(self.tabla)

        # Pie con conteo
        self.lbl_conteo = QLabel()
        self.lbl_conteo.setStyleSheet("color: gray;")
        layout.addWidget(self.lbl_conteo)

        self.recargar()

    def showEvent(self, event) -> None:
        """Cada vez que el usuario entra a la pestaña, refresca la lista y pone foco en buscar."""
        super().showEvent(event)
        self.recargar()
        self.txt_buscar.setFocus()

    # -----------------------------------------------------------------
    # Carga de tabla y estado
    # -----------------------------------------------------------------
    def _producto_seleccionado(self) -> dict | None:
        fila = self.tabla.currentRow()
        if 0 <= fila < len(self.productos):
            return self.productos[fila]
        return None

    def _activar_filtro_stock_bajo(self) -> None:
        self.chk_stock_bajo.setChecked(True)

    def _actualizar_alerta_stock_bajo(self) -> None:
        bajos = inventario.contar_stock_bajo()
        if bajos > 0:
            plural = "producto tiene" if bajos == 1 else "productos tienen"
            self.lbl_alerta.setText(f"⚠ Alerta: {bajos} {plural} stock bajo o agotado.")
            self.marco_alerta.setVisible(True)
        else:
            self.marco_alerta.setVisible(False)

    def recargar(self, seleccionar_id: int | None = None) -> None:
        if not isinstance(seleccionar_id, int):
            actual = self._producto_seleccionado()
            seleccionar_id = actual["id"] if actual else None

        self.productos = inventario.buscar(
            texto=self.txt_buscar.text(),
            incluir_inactivos=self.chk_inactivos.isChecked(),
            solo_stock_bajo=self.chk_stock_bajo.isChecked(),
        )

        self.tabla.setRowCount(len(self.productos))
        fila_a_seleccionar = -1

        for i, p in enumerate(self.productos):
            if p["id"] == seleccionar_id:
                fila_a_seleccionar = i

            tipo = p["tipo_venta"]
            es_peso = tipo == "peso"
            sufijo = " / lb" if es_peso else ""
            activo = bool(p["activo"])
            stock_bajo = activo and p["stock"] <= p["stock_minimo"]

            if not activo:
                estado = "Desactivado"
            elif stock_bajo:
                estado = "⚠ Stock bajo"
            else:
                estado = "Activo"

            valores = [
                p["codigo_barras"] or "—",
                p["nombre"],
                p["categoria"] or "—",
                "Peso (lb)" if es_peso else "Unidad",
                porcentaje_a_texto(p["iva_pct"]),
                formatear_pesos(p["precio_final"]) + sufijo,
                inventario.formatear_stock(tipo, p["stock"]),
                inventario.formatear_stock(tipo, p["stock_minimo"]),
                estado,
            ]

            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col in (4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if not activo:
                    item.setForeground(QBrush(QColor("#888888")))
                elif stock_bajo:
                    item.setForeground(QBrush(QColor("#b45309")))
                self.tabla.setItem(i, col, item)

        if fila_a_seleccionar >= 0:
            self.tabla.setCurrentCell(fila_a_seleccionar, 0)
            self.tabla.selectRow(fila_a_seleccionar)
        elif self.productos:
            self.tabla.setCurrentCell(0, 0)
            self.tabla.selectRow(0)

        self.lbl_conteo.setText(f"{len(self.productos)} producto(s) mostrados.")
        self._actualizar_alerta_stock_bajo()
        self._actualizar_botones()
        self.inventario_actualizado.emit()

    def _actualizar_botones(self) -> None:
        p = self._producto_seleccionado()
        hay = p is not None
        self.btn_editar.setEnabled(hay)
        self.btn_stock.setEnabled(hay)
        self.btn_activar.setEnabled(hay)
        if hay:
            self.btn_activar.setText("Desactivar" if p["activo"] else "Reactivar")

    # -----------------------------------------------------------------
    # Acciones CRUD
    # -----------------------------------------------------------------
    def _nuevo_producto(self) -> None:
        dlg = DialogoProducto(self)
        if dlg.exec():
            self.recargar(seleccionar_id=dlg.producto_id)

    def _editar_producto(self) -> None:
        p = self._producto_seleccionado()
        if not p:
            return
        # Leemos fresco desde la BD
        fresco = inventario.obtener(p["id"])
        dlg = DialogoProducto(self, producto=fresco)
        if dlg.exec():
            self.recargar(seleccionar_id=p["id"])

    def _ajustar_stock(self) -> None:
        p = self._producto_seleccionado()
        if not p:
            return
        fresco = inventario.obtener(p["id"])
        dlg = DialogoAjusteStock(self, producto=fresco)
        if dlg.exec():
            self.recargar(seleccionar_id=p["id"])

    def _cambiar_activo(self) -> None:
        p = self._producto_seleccionado()
        if not p:
            return
        if p["activo"]:
            resp = QMessageBox.question(
                self,
                "Desactivar producto",
                f"¿Desactivar '{p['nombre']}'?\n\n"
                "No aparecerá en las ventas, pero se conserva su historial "
                "y puede reactivarlo cuando quiera.",
            )
            if resp != QMessageBox.Yes:
                return
            inventario.cambiar_activo(p["id"], False)
        else:
            inventario.cambiar_activo(p["id"], True)
        self.recargar(seleccionar_id=p["id"])

    # -----------------------------------------------------------------
    # Excel / CSV
    # -----------------------------------------------------------------
    def _descargar_plantilla(self) -> None:
        sugerido = str(Path.home() / "Desktop" / "plantilla_productos.xlsx")
        ruta, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar plantilla de productos",
            sugerido,
            "Archivo de Excel (*.xlsx)",
        )
        if not ruta:
            return
        if not ruta.lower().endswith(".xlsx"):
            ruta += ".xlsx"
        try:
            imp.generar_plantilla(ruta)
            QMessageBox.information(
                self,
                "Plantilla creada",
                f"Plantilla guardada en:\n{ruta}\n\n"
                "Ábrala en Excel, llene sus productos y luego use «Importar Excel / CSV».",
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo guardar la plantilla:\n\n{e}")

    def _importar(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo de productos",
            str(Path.home() / "Desktop"),
            "Excel o CSV (*.xlsx *.xlsm *.csv *.txt)",
        )
        if not ruta:
            return
        try:
            crudas = imp.leer_archivo(ruta)
            filas = imp.validar_filas(crudas)
        except imp.ErrorImportacion as e:
            QMessageBox.warning(self, "No se pudo leer el archivo", str(e))
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Error al procesar el archivo:\n\n{e}")
            return

        if not filas:
            QMessageBox.information(self, "Importar", "El archivo no contiene filas de productos.")
            return

        dlg = DialogoImportar(self, filas, Path(ruta).name)
        if dlg.exec() and dlg.resultado:
            r = dlg.resultado
            QMessageBox.information(
                self,
                "Importación completada",
                f"Productos creados: {r['creados']}\n"
                f"Productos actualizados: {r['actualizados']}\n"
                f"Saltados: {r['saltados']}\n"
                f"Con errores (no importados): {r['errores']}",
            )
            self.recargar()
