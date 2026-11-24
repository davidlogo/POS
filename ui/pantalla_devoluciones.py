"""
Pantalla de Devoluciones (Fase 5 - Atajo F7).

Ajustes solicitados:
  - 2.1 Los cuadros de «Cant. a devolver» funcionan igual que en Ventas: al hacer clic
    o entrar en el cuadro, el nuevo valor digitado reemplaza automáticamente al valor
    actual sin tener que borrarlo primero.
  - 2.2 Al confirmar la devolución se eliminan los cuadros de confirmación/notificación
    y en su lugar únicamente se solicita la contraseña del sistema.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from modules import ajustes, auth, caja, devoluciones, inventario, ventas
from ui.comun import CampoNumeroReemplazo, FlowLayout, activar_formato_miles
from utils.dinero import formatear_pesos
from utils.fechas import formatear_fecha_dmy, formatear_fecha_hora_dmy

_ENCABEZADOS_VENTAS = ["# Venta", "Fecha", "Medio pago", "Total"]
_ENCABEZADOS_ITEMS = [
    "Producto",
    "Precio unit.",
    "Vendido",
    "Disponible",
    "Cant. a devolver",
    "Reponer stock",
    "Valor a devolver",
]
_ENCABEZADOS_HISTORIAL = ["# Dev.", "Venta", "Fecha", "Motivo", "Devuelto"]


class PantallaDevoluciones(QWidget):
    devolucion_registrada = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ventas_encontradas: list[dict] = []
        self.historial_devoluciones: list[dict] = []
        self.venta_actual: dict | None = None
        self.controles_items: list[dict] = []

        layout_raiz = QHBoxLayout(self)
        divisor = QSplitter(Qt.Horizontal)
        layout_raiz.addWidget(divisor)

        # =====================================================================
        # COLUMNA IZQUIERDA: Buscador de ventas + Lista de ventas + Historial
        # =====================================================================
        panel_izq = QWidget()
        col_izq = QVBoxLayout(panel_izq)
        col_izq.setContentsMargins(0, 0, 6, 0)

        grupo_buscar = QGroupBox("1. Buscar venta del turno actual")
        vbox_busq = QVBoxLayout(grupo_buscar)

        fila_busq = QHBoxLayout()
        fila_busq.addWidget(QLabel("Venta # o producto:"))
        self.txt_buscar = QLineEdit()
        self.txt_buscar.setPlaceholderText("Ej: 12, #12, nombre o código del producto...")
        self.txt_buscar.setClearButtonEnabled(True)
        self.txt_buscar.textChanged.connect(self.recargar_ventas)
        fila_busq.addWidget(self.txt_buscar, stretch=1)

        btn_refrescar = QPushButton("Actualizar")
        btn_refrescar.clicked.connect(self.recargar_todo)
        fila_busq.addWidget(btn_refrescar)
        vbox_busq.addLayout(fila_busq)

        self.tabla_ventas = QTableWidget(0, len(_ENCABEZADOS_VENTAS))
        self.tabla_ventas.setObjectName("tabla_ventas_devoluciones")
        self.tabla_ventas.setHorizontalHeaderLabels(_ENCABEZADOS_VENTAS)
        self.tabla_ventas.verticalHeader().setVisible(False)
        self.tabla_ventas.setAlternatingRowColors(True)
        self.tabla_ventas.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_ventas.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla_ventas.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla_ventas.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_ventas.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla_ventas.itemSelectionChanged.connect(self._al_seleccionar_venta)
        vbox_busq.addWidget(self.tabla_ventas)

        col_izq.addWidget(grupo_buscar, stretch=3)

        # Historial de devoluciones del turno actual
        grupo_hist = QGroupBox("Devoluciones del turno actual")
        vbox_hist = QVBoxLayout(grupo_hist)
        self.tabla_historial = QTableWidget(0, len(_ENCABEZADOS_HISTORIAL))
        self.tabla_historial.setObjectName("tabla_historial_devoluciones")
        self.tabla_historial.setHorizontalHeaderLabels(_ENCABEZADOS_HISTORIAL)
        self.tabla_historial.verticalHeader().setVisible(False)
        self.tabla_historial.setAlternatingRowColors(True)
        self.tabla_historial.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_historial.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla_historial.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla_historial.setStyleSheet(
            "QTableWidget::item:selected, QTableWidget::item:selected:active, "
            "QTableWidget::item:selected:!active { "
            "background-color: #fde047; color: #0f172a; font-weight: bold; }"
        )
        self.tabla_historial.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_historial.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        vbox_hist.addWidget(self.tabla_historial)
        col_izq.addWidget(grupo_hist, stretch=2)

        divisor.addWidget(panel_izq)

        # =====================================================================
        # COLUMNA DERECHA: Detalle de la venta y formulario de devolución
        # =====================================================================
        grupo_det = QGroupBox("2. Seleccionar productos a devolver")
        vbox_det = QVBoxLayout(grupo_det)

        self.lbl_info_venta = QLabel("Seleccione una venta en la tabla de la izquierda.")
        self.lbl_info_venta.setStyleSheet("font-size: 12pt; font-weight: bold; color: #1e3a8a;")
        self.lbl_info_venta.setWordWrap(True)
        vbox_det.addWidget(self.lbl_info_venta)

        # Botones rápidos para llenar o limpiar cantidades
        fila_rap = FlowLayout(margin=0, h_spacing=6, v_spacing=4)
        self.btn_devolver_todo = QPushButton("Devolver toda la venta (todo lo disponible)")
        self.btn_devolver_todo.clicked.connect(self._marcar_todo_disponible)
        self.btn_limpiar_cant = QPushButton("Poner cantidades en 0")
        self.btn_limpiar_cant.clicked.connect(self._poner_cantidades_en_cero)
        fila_rap.addWidget(self.btn_devolver_todo)
        fila_rap.addWidget(self.btn_limpiar_cant)
        vbox_det.addLayout(fila_rap)

        self.tabla_items = QTableWidget(0, len(_ENCABEZADOS_ITEMS))
        self.tabla_items.setObjectName("tabla_items_devoluciones")
        self.tabla_items.setHorizontalHeaderLabels(_ENCABEZADOS_ITEMS)
        self.tabla_items.verticalHeader().setVisible(False)
        self.tabla_items.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.tabla_items.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_items.setSelectionMode(QTableWidget.NoSelection)
        self.tabla_items.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.tabla_items.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_items.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.tabla_items.setColumnWidth(0, 170)
        self.tabla_items.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        vbox_det.addWidget(self.tabla_items, stretch=1)

        # Motivo de la devolución
        fila_motivo = QHBoxLayout()
        fila_motivo.addWidget(QLabel("Motivo de la devolución: *"))
        self.txt_motivo = QLineEdit()
        self.txt_motivo.setPlaceholderText(
            "Obligatorio: ej. Producto defectuoso, cambio de opinión, error en cobro..."
        )
        self.txt_motivo.setMaxLength(200)
        fila_motivo.addWidget(self.txt_motivo, stretch=1)
        vbox_det.addLayout(fila_motivo)

        # Recuadro grande con VALOR A DEVOLVER EN EFECTIVO
        marco_reembolso = QFrame()
        marco_reembolso.setStyleSheet(
            "QFrame { background-color: #fff7ed; border: 2px solid #f97316; border-radius: 8px; padding: 8px; }"
            "QLabel { border: none; }"
        )
        fila_reemb = QHBoxLayout(marco_reembolso)
        lbl_tit_reemb = QLabel("VALOR A DEVOLVER (SALE EN EFECTIVO):")
        lbl_tit_reemb.setStyleSheet("color: #9a3412; font-weight: bold; font-size: 11pt;")
        self.lbl_total_devolver = QLabel("$ 0")
        self.lbl_total_devolver.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_total_devolver.setStyleSheet("color: #c2410c; font-size: 22pt; font-weight: 800;")
        fila_reemb.addWidget(lbl_tit_reemb)
        fila_reemb.addStretch()
        fila_reemb.addWidget(self.lbl_total_devolver)
        vbox_det.addWidget(marco_reembolso)

        self.btn_confirmar = QPushButton("Registrar devolución en efectivo")
        self.btn_confirmar.setMinimumHeight(46)
        self.btn_confirmar.setStyleSheet(
            "QPushButton { background-color: #ea580c; color: white; font-size: 13pt; "
            "font-weight: bold; border: none; border-radius: 8px; }"
            "QPushButton:hover { background-color: #c2410c; }"
            "QPushButton:disabled { background-color: #cbd5e1; color: #64748b; }"
        )
        self.btn_confirmar.clicked.connect(self._confirmar_devolucion)
        vbox_det.addWidget(self.btn_confirmar)

        divisor.addWidget(grupo_det)
        divisor.setStretchFactor(0, 5)
        divisor.setStretchFactor(1, 6)

        self.recargar_todo()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.recargar_todo()
        self.txt_buscar.setFocus()

    # =====================================================================
    # Carga de ventas e historial
    # =====================================================================
    def recargar_todo(self, seleccionar_venta_id: int | None = None) -> None:
        self.recargar_historial()
        self.recargar_ventas(seleccionar_venta_id=seleccionar_venta_id)

    def recargar_ventas(self, seleccionar_venta_id: int | None = None) -> None:
        if not isinstance(seleccionar_venta_id, int) and self.venta_actual:
            seleccionar_venta_id = self.venta_actual["id"]

        hay_turno = caja.hay_turno_abierto()
        self.txt_buscar.setEnabled(hay_turno)
        self.txt_motivo.setEnabled(hay_turno)
        if not hay_turno:
            self.txt_buscar.blockSignals(True)
            self.txt_buscar.clear()
            self.txt_buscar.blockSignals(False)
            self.txt_motivo.clear()

        self.ventas_encontradas = devoluciones.buscar_ventas(
            texto=self.txt_buscar.text(),
            solo_turno_abierto=True,
        )
        self.tabla_ventas.setRowCount(len(self.ventas_encontradas))
        fila_sel = -1

        mapa_medios = dict(ventas.MEDIOS_PAGO)
        for i, v in enumerate(self.ventas_encontradas):
            if v["id"] == seleccionar_venta_id:
                fila_sel = i
            dev = v["total_devuelto"]
            valores = [
                f"#{v['id']}",
                formatear_fecha_hora_dmy(v["fecha"]),
                mapa_medios.get(v["medio_pago"], v["medio_pago"]),
                formatear_pesos(v["total"]),
            ]
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col in (0, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if dev >= v["total"] and v["total"] > 0:
                    item.setForeground(QBrush(QColor("#94a3b8")))
                self.tabla_ventas.setItem(i, col, item)

        if fila_sel >= 0:
            self.tabla_ventas.setCurrentCell(fila_sel, 0)
            self.tabla_ventas.selectRow(fila_sel)
        elif self.ventas_encontradas:
            self.tabla_ventas.setCurrentCell(0, 0)
            self.tabla_ventas.selectRow(0)
        else:
            self.venta_actual = None
            self._cargar_detalle_venta(None)
            self._resaltar_devoluciones_en_historial(None)

    def recargar_historial(self) -> None:
        self.historial_devoluciones = devoluciones.listar_devoluciones_recientes(
            limite=100,
            solo_turno_abierto=True,
        )
        self.tabla_historial.setRowCount(len(self.historial_devoluciones))
        for i, d in enumerate(self.historial_devoluciones):
            fecha_completa = formatear_fecha_hora_dmy(d["fecha"])
            valores = [
                f"#{d['id']}",
                f"Venta #{d['venta_id']}",
                formatear_fecha_dmy(d["fecha"]),
                d["motivo"],
                formatear_pesos(d["total_devuelto"]),
            ]
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col in (0, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 2:
                    item.setData(Qt.UserRole, fecha_completa)
                    item.setToolTip(fecha_completa)
                self.tabla_historial.setItem(i, col, item)

        venta_sel_id = self.venta_actual["id"] if self.venta_actual else None
        self._resaltar_devoluciones_en_historial(venta_sel_id)

    def _resaltar_devoluciones_en_historial(self, venta_id: int | None) -> None:
        """Selecciona y resalta en amarillo en el historial las devoluciones de la venta elegida."""
        self.tabla_historial.clearSelection()
        fondo_amarillo = QBrush(QColor("#fef08a"))
        texto_oscuro = QBrush(QColor("#0f172a"))
        primera_fila = -1

        for i, d in enumerate(self.historial_devoluciones):
            coincide = venta_id is not None and d["venta_id"] == venta_id
            if coincide and primera_fila < 0:
                primera_fila = i
            for col in range(self.tabla_historial.columnCount()):
                item = self.tabla_historial.item(i, col)
                if item is None:
                    continue
                fuente = item.font()
                fuente.setBold(coincide)
                item.setFont(fuente)
                if coincide:
                    item.setBackground(fondo_amarillo)
                    item.setForeground(texto_oscuro)
                else:
                    item.setBackground(QBrush())
                    item.setForeground(QBrush())

        if primera_fila >= 0:
            self.tabla_historial.selectRow(primera_fila)
            item_dest = self.tabla_historial.item(primera_fila, 0)
            if item_dest is not None:
                self.tabla_historial.scrollToItem(item_dest)

    # =====================================================================
    # Detalle de la venta seleccionada
    # =====================================================================
    def _al_seleccionar_venta(self) -> None:
        fila = self.tabla_ventas.currentRow()
        if not (0 <= fila < len(self.ventas_encontradas)):
            self._cargar_detalle_venta(None)
            self._resaltar_devoluciones_en_historial(None)
            return
        venta_id = self.ventas_encontradas[fila]["id"]
        detalle = devoluciones.obtener_venta_para_devolucion(venta_id)
        self._cargar_detalle_venta(detalle)
        self._resaltar_devoluciones_en_historial(venta_id)

    def _cargar_detalle_venta(self, detalle: dict | None) -> None:
        self.venta_actual = detalle
        self.controles_items.clear()
        self.tabla_items.setRowCount(0)

        if detalle is None:
            if not caja.hay_turno_abierto():
                self.lbl_info_venta.setText(
                    "⚠ Caja cerrada — Abra un turno en Caja (F9) para registrar devoluciones del día."
                )
            elif not self.ventas_encontradas:
                self.lbl_info_venta.setText("No hay ventas registradas en el turno actual.")
            else:
                self.lbl_info_venta.setText("Seleccione una venta en la tabla de la izquierda.")
            self.btn_devolver_todo.setEnabled(False)
            self.btn_limpiar_cant.setEnabled(False)
            self.btn_confirmar.setEnabled(False)
            self.lbl_total_devolver.setText("$ 0")
            return

        medio_txt = dict(ventas.MEDIOS_PAGO).get(detalle["medio_pago"], detalle["medio_pago"])
        ya_dev = detalle["total_devuelto"]
        extra_dev = f"   |   Ya devuelto: {formatear_pesos(ya_dev)}" if ya_dev > 0 else ""
        self.lbl_info_venta.setText(
            f"Venta #{detalle['id']}  ·  Fecha: {formatear_fecha_hora_dmy(detalle['fecha'])}  ·  "
            f"Pago original: {medio_txt}  ·  Total: {formatear_pesos(detalle['total'])}{extra_dev}"
        )

        items = detalle["items"]
        self.tabla_items.setRowCount(len(items))
        tam_pt = ajustes.obtener_entero("tamano_texto_listas")
        altura_fila = max(42, int(tam_pt * 2.9) + 8)
        alto_caja = max(30, int(tam_pt * 2.1) + 4)
        ancho_unid = max(44, int(tam_pt * 3.5))
        ancho_caja = max(118, int(tam_pt * 9.2))
        ancho_col_cant = max(138, ancho_caja + 16)
        self.tabla_items.verticalHeader().setMinimumSectionSize(altura_fila)
        self.tabla_items.verticalHeader().setDefaultSectionSize(altura_fila)
        self.tabla_items.setColumnWidth(0, max(170, self.tabla_items.columnWidth(0)))
        self.tabla_items.setColumnWidth(4, ancho_col_cant)
        hay_algo_disponible = False

        for i, it in enumerate(items):
            self.tabla_items.setRowHeight(i, altura_fila)
            es_peso = it["tipo_venta"] == "peso"
            sufijo = " / lb" if es_peso else ""
            disp = it["cantidad_disponible"]
            if disp > 0:
                hay_algo_disponible = True

            celdas_info = [
                (0, it["nombre"], Qt.AlignLeft | Qt.AlignVCenter),
                (1, formatear_pesos(it["precio_unitario"]) + sufijo, Qt.AlignRight | Qt.AlignVCenter),
                (2, inventario.formatear_stock(it["tipo_venta"], it["cantidad"]), Qt.AlignRight | Qt.AlignVCenter),
                (3, inventario.formatear_stock(it["tipo_venta"], disp), Qt.AlignRight | Qt.AlignVCenter),
            ]
            for col, texto, alin in celdas_info:
                c = QTableWidgetItem(texto)
                c.setTextAlignment(alin)
                self.tabla_items.setItem(i, col, c)

            # Columna 4: Caja integrada [ número | UND/G ] sin solapamientos
            contenedor_cant = QWidget()
            contenedor_cant.setStyleSheet("background: transparent;")
            lay_ext = QHBoxLayout(contenedor_cant)
            lay_ext.setContentsMargins(6, 2, 6, 2)
            lay_ext.setAlignment(Qt.AlignCenter)

            caja_blanca = QFrame()
            caja_blanca.setObjectName("caja_cantidad_devolucion")
            caja_blanca.setFixedSize(ancho_caja, alto_caja)
            lay_int = QHBoxLayout(caja_blanca)
            lay_int.setContentsMargins(1, 1, 1, 1)
            lay_int.setSpacing(0)

            txt_cant = CampoNumeroReemplazo()
            txt_cant.setObjectName("campo_cantidad_carrito")
            txt_cant.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            txt_cant.setText("0")
            txt_cant.setEnabled(disp > 0)
            activar_formato_miles(txt_cant)
            txt_cant.textChanged.connect(lambda _, fila=i: self._al_cambiar_cantidad_item(fila))

            lbl_u = QLabel("G" if es_peso else "UND")
            lbl_u.setObjectName("unidad_cantidad_devolucion")
            lbl_u.setFixedWidth(ancho_unid)
            lbl_u.setAlignment(Qt.AlignCenter)

            lay_int.addWidget(txt_cant, stretch=1)
            lay_int.addWidget(lbl_u)
            lay_ext.addWidget(caja_blanca)
            self.tabla_items.setCellWidget(i, 4, contenedor_cant)

            # Columna 5: Solo casilla centrada (sin texto)
            contenedor_chk = QWidget()
            contenedor_chk.setStyleSheet("background: transparent;")
            lay_chk = QHBoxLayout(contenedor_chk)
            lay_chk.setContentsMargins(0, 0, 0, 0)
            lay_chk.setAlignment(Qt.AlignCenter)
            chk = QCheckBox()
            chk.setFixedSize(24, 24)
            chk.setToolTip("Reponer al stock")
            chk.setChecked(True)
            chk.setEnabled(disp > 0)
            lay_chk.addWidget(chk)
            self.tabla_items.setCellWidget(i, 5, contenedor_chk)

            # Columna 6: Valor a devolver de esta línea
            item_val = QTableWidgetItem("$ 0")
            item_val.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tabla_items.setItem(i, 6, item_val)

            self.controles_items.append({
                "item_venta": it,
                "txt_cant": txt_cant,
                "chk_reponer": chk,
                "celda_valor": item_val,
            })

        self.btn_devolver_todo.setEnabled(hay_algo_disponible)
        self.btn_limpiar_cant.setEnabled(hay_algo_disponible)
        self._recalcular_totales_devolucion()

    def _leer_cantidad_ctrl(self, ctrl: dict) -> int:
        limpio = ctrl["txt_cant"].text().replace(".", "").strip()
        if not limpio or not limpio.isdigit():
            return 0
        val = int(limpio)
        max_disp = ctrl["item_venta"]["cantidad_disponible"]
        if val > max_disp:
            val = max_disp
            ctrl["txt_cant"].blockSignals(True)
            ctrl["txt_cant"].setText(f"{val:,}".replace(",", "."))
            ctrl["txt_cant"].blockSignals(False)
        return val

    def _al_cambiar_cantidad_item(self, fila: int) -> None:
        if 0 <= fila < len(self.controles_items):
            self._leer_cantidad_ctrl(self.controles_items[fila])
        self._recalcular_totales_devolucion()

    def _marcar_todo_disponible(self) -> None:
        for ctrl in self.controles_items:
            disp = ctrl["item_venta"]["cantidad_disponible"]
            ctrl["txt_cant"].setText(f"{disp:,}".replace(",", "."))

    def _poner_cantidades_en_cero(self) -> None:
        for ctrl in self.controles_items:
            ctrl["txt_cant"].setText("0")

    def _recalcular_totales_devolucion(self) -> None:
        total = 0
        hay_cantidad = False
        for ctrl in self.controles_items:
            cant = self._leer_cantidad_ctrl(ctrl)
            if cant > 0:
                hay_cantidad = True
            valor, _ = devoluciones.calcular_valor_devolucion_item(ctrl["item_venta"], cant)
            total += valor
            ctrl["celda_valor"].setText(formatear_pesos(valor))

        self.lbl_total_devolver.setText(formatear_pesos(total))
        self.btn_confirmar.setEnabled(hay_cantidad)

    # =====================================================================
    # Confirmar devolución (solo solicita contraseña, sin cuadros extra)
    # =====================================================================
    def _confirmar_devolucion(self) -> None:
        if not self.venta_actual:
            return
        motivo = self.txt_motivo.text().strip()
        if not motivo:
            self.txt_motivo.setFocus()
            return

        lineas = []
        for ctrl in self.controles_items:
            cant = self._leer_cantidad_ctrl(ctrl)
            if cant > 0:
                lineas.append({
                    "venta_item_id": ctrl["item_venta"]["id"],
                    "cantidad": cant,
                    "repone_stock": ctrl["chk_reponer"].isChecked(),
                })

        if not lineas:
            return

        clave, ok = QInputDialog.getText(
            self,
            "Autorizar devolución",
            "Ingrese la contraseña del sistema para registrar la devolución:",
            QLineEdit.Password,
        )
        if not ok or not auth.verificar_clave(clave):
            return

        try:
            res = devoluciones.registrar_devolucion(
                venta_id=self.venta_actual["id"],
                motivo=motivo,
                lineas=lineas,
            )
        except Exception:  # noqa: BLE001
            return

        self.txt_motivo.clear()
        self.recargar_todo(seleccionar_venta_id=res["venta_id"])
        self.devolucion_registrada.emit()
