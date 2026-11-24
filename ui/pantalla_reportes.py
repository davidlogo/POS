"""
Pantalla de Reportes (Atajo F10).

Incluye 4 submenús independientes, cada uno con su propio filtro de fechas
(Hoy / Ayer / Personalizado / Todos) y exportación a Excel (.xlsx), sin CSV:
  1. Ventas: indicadores, ventas con su detalle y productos más vendidos.
  2. Inventario: estado actual del stock y movimientos de stock del período.
  3. Devoluciones: listado (sin hora en la tabla; al exportar a Excel incluye fecha y hora completa)
     y detalle de los productos devueltos.
  4. Caja: listado de todos los cierres y turnos (con opción de filtrar por fecha) y sus retiros/gastos.
"""

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QButtonGroup, QDateEdit, QFileDialog, QFrame, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from modules import inventario, reportes, ventas
from ui.comun import FlowLayout
from utils.dinero import formatear_pesos
from utils.fechas import formatear_fecha_dmy, formatear_fecha_hora_dmy, rango_fechas
from utils.porcentajes import porcentaje_a_texto

_ENC_VENTAS = ["# Venta", "Fecha y hora", "Medio pago", "Total", "Devuelto"]
_ENC_DETALLE_VENTA = ["Código", "Producto", "Cant. vendida", "Precio unit.", "% IVA", "Subtotal", "Devuelto"]
_ENC_PRODUCTOS = [
    "#",
    "Código",
    "Producto",
    "Tipo",
    "Cantidad neta",
    "Total vendido",
    "Devuelto",
    "Venta neta",
]
_ENC_INVENTARIO = [
    "Código",
    "Producto",
    "Categoría",
    "Tipo",
    "Stock actual",
    "Stock mínimo",
    "Estado",
    "Precio venta",
    "Valor stock",
]
_ENC_MOV_STOCK = ["# Mov.", "Fecha y hora", "Producto", "Tipo", "Cantidad", "Stock ant.", "Stock nuevo", "Motivo"]
_ENC_DEVOLUCIONES = ["# Dev.", "Venta", "Fecha", "Motivo", "Devuelto"]
_ENC_DETALLE_DEV = ["Código", "Producto", "Cant. devuelta", "Valor devuelto", "Repone stock"]
_ENC_CAJA = [
    "# Turno",
    "Apertura",
    "Cierre",
    "Base",
    "Ventas Efec.",
    "Ventas Transf.",
    "Devoluciones",
    "Retiros/Gastos",
    "Efectivo caja",
    "Contado",
    "Diferencia",
]
_ENC_MOV_CAJA = ["Fecha y hora", "Tipo", "Motivo", "Monto"]


def _crear_tarjeta(titulo: str, color_borde: str, color_valor: str) -> tuple[QFrame, QLabel, QLabel]:
    """Crea una tarjeta visual de indicador con título, valor grande y subtítulo."""
    marco = QFrame()
    marco.setStyleSheet(
        f"QFrame {{ background-color: #ffffff; border: 1px solid #cbd5e1; "
        f"border-left: 5px solid {color_borde}; border-radius: 8px; padding: 6px; }}"
        "QLabel { border: none; }"
    )
    vbox = QVBoxLayout(marco)
    vbox.setContentsMargins(6, 3, 6, 3)
    vbox.setSpacing(1)

    lbl_tit = QLabel(titulo)
    lbl_tit.setStyleSheet("color: #475569; font-size: 9pt; font-weight: bold;")
    lbl_tit.setWordWrap(True)
    vbox.addWidget(lbl_tit)

    lbl_val = QLabel("$ 0")
    lbl_val.setStyleSheet(f"color: {color_valor}; font-size: 16pt; font-weight: 800;")
    vbox.addWidget(lbl_val)

    lbl_sub = QLabel("")
    lbl_sub.setStyleSheet("color: #64748b; font-size: 8.8pt;")
    lbl_sub.setWordWrap(True)
    vbox.addWidget(lbl_sub)

    return marco, lbl_val, lbl_sub


def _formatear_diferencia(diferencia: int) -> tuple[str, str]:
    if diferencia == 0:
        return "$ 0 (Exacto)", "#15803d"
    if diferencia > 0:
        return f"+{formatear_pesos(diferencia)} (Sobrante)", "#15803d"
    return f"{formatear_pesos(diferencia)} (Faltante)", "#dc2626"


class _BarraFiltroReporte(QFrame):
    """Barra de filtro de fechas (Hoy / Ayer / Personalizado / Todos) + Exportar a Excel."""

    filtro_cambiado = Signal()
    exportar_solicitado = Signal()

    def __init__(self, texto_exportar: str, modo_inicial: str = "hoy", parent=None):
        super().__init__(parent)
        self.modo: str = modo_inicial
        self.setStyleSheet(
            "QFrame { background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 6px; }"
            "QLabel { border: none; font-weight: bold; }"
        )
        fila = FlowLayout(self, margin=6, h_spacing=6, v_spacing=6)
        fila.addWidget(QLabel("Período:"))

        self.grupo_rango = QButtonGroup(self)
        self.grupo_rango.setExclusive(True)
        estilo_btn = (
            "QPushButton { padding: 5px 12px; border: 1px solid #94a3b8; border-radius: 6px; background: #f8fafc; }"
            "QPushButton:checked { background-color: #1e40af; color: white; border-color: #1e3a8a; }"
        )
        self.botones: dict[str, QPushButton] = {}
        for codigo, texto in (
            ("hoy", "Hoy"),
            ("ayer", "Ayer"),
            ("personalizado", "Personalizado"),
            ("todos", "Todos"),
        ):
            b = QPushButton(texto)
            b.setCheckable(True)
            b.setStyleSheet(estilo_btn)
            b.clicked.connect(lambda _, c=codigo: self.establecer_modo(c))
            self.grupo_rango.addButton(b)
            self.botones[codigo] = b
            fila.addWidget(b)

        self.lbl_desde = QLabel("Desde:")
        self.dt_desde = QDateEdit(QDate.currentDate())
        self.dt_desde.setCalendarPopup(True)
        self.dt_desde.setDisplayFormat("dd-MM-yyyy")
        self.dt_desde.setMinimumWidth(115)
        self.dt_desde.dateChanged.connect(self._al_cambiar_fecha)

        self.lbl_hasta = QLabel("Hasta:")
        self.dt_hasta = QDateEdit(QDate.currentDate())
        self.dt_hasta.setCalendarPopup(True)
        self.dt_hasta.setDisplayFormat("dd-MM-yyyy")
        self.dt_hasta.setMinimumWidth(115)
        self.dt_hasta.dateChanged.connect(self._al_cambiar_fecha)

        fila.addWidget(self.lbl_desde)
        fila.addWidget(self.dt_desde)
        fila.addWidget(self.lbl_hasta)
        fila.addWidget(self.dt_hasta)

        btn_consultar = QPushButton("Consultar")
        btn_consultar.setMinimumHeight(32)
        btn_consultar.clicked.connect(self.filtro_cambiado.emit)
        fila.addWidget(btn_consultar)

        self.btn_excel = QPushButton(texto_exportar)
        self.btn_excel.setMinimumHeight(32)
        self.btn_excel.setStyleSheet(
            "QPushButton { background-color: #15803d; color: white; border: none; padding: 5px 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #166534; }"
        )
        self.btn_excel.clicked.connect(self.exportar_solicitado.emit)
        fila.addWidget(self.btn_excel)

        self.establecer_modo(modo_inicial, emitir=False)

    def _qdate_a_date(self, qd: QDate) -> date:
        return date(qd.year(), qd.month(), qd.day())

    def establecer_modo(self, modo: str, emitir: bool = True) -> None:
        self.modo = modo
        if modo in self.botones:
            self.botones[modo].setChecked(True)

        es_pers = modo == "personalizado"
        es_todos = modo == "todos"
        for w in (self.lbl_desde, self.dt_desde, self.lbl_hasta, self.dt_hasta):
            w.setVisible(not es_todos)
        self.dt_desde.setEnabled(es_pers)
        self.dt_hasta.setEnabled(es_pers)

        if not es_todos and not es_pers:
            ini, fin = rango_fechas(modo)
            self.dt_desde.blockSignals(True)
            self.dt_hasta.blockSignals(True)
            self.dt_desde.setDate(QDate.fromString(ini, "yyyy-MM-dd"))
            self.dt_hasta.setDate(QDate.fromString(fin, "yyyy-MM-dd"))
            self.dt_desde.blockSignals(False)
            self.dt_hasta.blockSignals(False)

        if emitir:
            self.filtro_cambiado.emit()

    def _al_cambiar_fecha(self) -> None:
        if self.modo == "personalizado":
            self.filtro_cambiado.emit()

    def rango(self) -> tuple[str | None, str | None]:
        """Devuelve (fecha_desde_iso, fecha_hasta_iso) o (None, None) si el modo es 'todos'."""
        if self.modo == "todos":
            return None, None
        return rango_fechas(
            self.modo,
            desde=self._qdate_a_date(self.dt_desde.date()),
            hasta=self._qdate_a_date(self.dt_hasta.date()),
        )


class PantallaReportes(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ventas_periodo: list[dict] = []
        self.devoluciones_periodo: list[dict] = []
        self.turnos_periodo: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # =====================================================================
        # SUBMENÚS PRINCIPALES: Ventas | Inventario | Devoluciones | Caja
        # (cada uno con su propio filtro de fechas y botón Exportar a Excel)
        # =====================================================================
        self.sub_pestanas = QTabWidget()
        self.sub_pestanas.addTab(self._construir_tab_ventas(), "Ventas")
        self.sub_pestanas.addTab(self._construir_tab_inventario(), "Inventario")
        self.sub_pestanas.addTab(self._construir_tab_devoluciones(), "Devoluciones")
        self.sub_pestanas.addTab(self._construir_tab_caja(), "Caja")

        layout.addWidget(self.sub_pestanas, stretch=1)

        self.recargar()

    # =====================================================================
    # Construcción de los 4 submenús (cada uno con su propio filtro)
    # =====================================================================
    def _construir_tab_ventas(self) -> QWidget:
        pag = QWidget()
        vbox = QVBoxLayout(pag)
        vbox.setSpacing(10)

        self.filtro_ventas = _BarraFiltroReporte("Exportar Ventas (.xlsx)", modo_inicial="hoy")
        self.filtro_ventas.filtro_cambiado.connect(self._recargar_ventas)
        self.filtro_ventas.exportar_solicitado.connect(
            lambda: self._exportar_excel("ventas", self.filtro_ventas)
        )
        vbox.addWidget(self.filtro_ventas)

        fila_kpi = QHBoxLayout()
        fila_kpi.setSpacing(10)
        t1, self.lbl_kpi_neta, self.lbl_sub_neta = _crear_tarjeta(
            "VENTA NETA (VENTAS − DEVOLUCIONES)", "#2563eb", "#1e3a8a"
        )
        t2, self.lbl_kpi_tickets, self.lbl_sub_tickets = _crear_tarjeta(
            "NÚMERO DE VENTAS Y TICKET PROMEDIO", "#0891b2", "#0e7490"
        )
        t3, self.lbl_kpi_medios, self.lbl_sub_medios = _crear_tarjeta(
            "DESGLOSE POR MEDIO DE PAGO", "#7c3aed", "#5b21b6"
        )
        for tarjeta in (t1, t2, t3):
            fila_kpi.addWidget(tarjeta, stretch=1)
        vbox.addLayout(fila_kpi)

        self.sub_ventas = QTabWidget()

        pag_ventas = QWidget()
        lay_ventas = QHBoxLayout(pag_ventas)

        grupo_lista_v = QGroupBox("Ventas del período (seleccione una para ver su detalle)")
        vbox_lv = QVBoxLayout(grupo_lista_v)
        self.tabla_ventas = QTableWidget(0, len(_ENC_VENTAS))
        self.tabla_ventas.setHorizontalHeaderLabels(_ENC_VENTAS)
        self.tabla_ventas.verticalHeader().setVisible(False)
        self.tabla_ventas.setAlternatingRowColors(True)
        self.tabla_ventas.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_ventas.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla_ventas.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla_ventas.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_ventas.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla_ventas.itemSelectionChanged.connect(self._al_seleccionar_venta)
        vbox_lv.addWidget(self.tabla_ventas)
        lay_ventas.addWidget(grupo_lista_v, stretch=5)

        grupo_det_v = QGroupBox("Detalle de la venta seleccionada")
        vbox_dv = QVBoxLayout(grupo_det_v)
        self.lbl_encabezado_detalle = QLabel("Seleccione una venta en la tabla de la izquierda.")
        self.lbl_encabezado_detalle.setStyleSheet("font-weight: bold; color: #1e3a8a;")
        self.lbl_encabezado_detalle.setWordWrap(True)
        vbox_dv.addWidget(self.lbl_encabezado_detalle)

        self.tabla_detalle = QTableWidget(0, len(_ENC_DETALLE_VENTA))
        self.tabla_detalle.setHorizontalHeaderLabels(_ENC_DETALLE_VENTA)
        self.tabla_detalle.verticalHeader().setVisible(False)
        self.tabla_detalle.setAlternatingRowColors(True)
        self.tabla_detalle.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_detalle.setSelectionMode(QTableWidget.NoSelection)
        self.tabla_detalle.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_detalle.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        vbox_dv.addWidget(self.tabla_detalle)

        self.lbl_pie_detalle = QLabel("")
        self.lbl_pie_detalle.setStyleSheet("color: #475569; font-size: 9.5pt;")
        self.lbl_pie_detalle.setWordWrap(True)
        vbox_dv.addWidget(self.lbl_pie_detalle)
        lay_ventas.addWidget(grupo_det_v, stretch=6)

        self.sub_ventas.addTab(pag_ventas, "Ventas y detalle de cada venta")

        pag_prod = QWidget()
        lay_prod = QVBoxLayout(pag_prod)
        self.tabla_productos = QTableWidget(0, len(_ENC_PRODUCTOS))
        self.tabla_productos.setHorizontalHeaderLabels(_ENC_PRODUCTOS)
        self.tabla_productos.verticalHeader().setVisible(False)
        self.tabla_productos.setAlternatingRowColors(True)
        self.tabla_productos.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_productos.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla_productos.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_productos.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        lay_prod.addWidget(self.tabla_productos)
        self.sub_ventas.addTab(pag_prod, "Productos más vendidos")

        vbox.addWidget(self.sub_ventas, stretch=1)
        return pag

    def _construir_tab_inventario(self) -> QWidget:
        pag = QWidget()
        vbox = QVBoxLayout(pag)
        vbox.setSpacing(10)

        self.filtro_inventario = _BarraFiltroReporte("Exportar Inventario (.xlsx)", modo_inicial="hoy")
        self.filtro_inventario.filtro_cambiado.connect(self._recargar_inventario)
        self.filtro_inventario.exportar_solicitado.connect(
            lambda: self._exportar_excel("inventario", self.filtro_inventario)
        )
        vbox.addWidget(self.filtro_inventario)

        fila_kpi = QHBoxLayout()
        fila_kpi.setSpacing(10)
        t1, self.lbl_inv_total, self.lbl_inv_sub_total = _crear_tarjeta(
            "PRODUCTOS ACTIVOS", "#2563eb", "#1e3a8a"
        )
        t2, self.lbl_inv_bajo, self.lbl_inv_sub_bajo = _crear_tarjeta(
            "ALERTAS DE STOCK", "#f59e0b", "#b45309"
        )
        t3, self.lbl_inv_valor, self.lbl_inv_sub_valor = _crear_tarjeta(
            "VALOR EN INVENTARIO (PRECIO VENTA)", "#15803d", "#166534"
        )
        for tarjeta in (t1, t2, t3):
            fila_kpi.addWidget(tarjeta, stretch=1)
        vbox.addLayout(fila_kpi)

        self.sub_inventario = QTabWidget()

        pag_stock = QWidget()
        lay_stock = QVBoxLayout(pag_stock)
        self.tabla_inventario = QTableWidget(0, len(_ENC_INVENTARIO))
        self.tabla_inventario.setHorizontalHeaderLabels(_ENC_INVENTARIO)
        self.tabla_inventario.verticalHeader().setVisible(False)
        self.tabla_inventario.setAlternatingRowColors(True)
        self.tabla_inventario.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_inventario.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla_inventario.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_inventario.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        lay_stock.addWidget(self.tabla_inventario)
        self.sub_inventario.addTab(pag_stock, "Stock actual")

        pag_mov = QWidget()
        lay_mov = QVBoxLayout(pag_mov)
        self.tabla_mov_stock = QTableWidget(0, len(_ENC_MOV_STOCK))
        self.tabla_mov_stock.setHorizontalHeaderLabels(_ENC_MOV_STOCK)
        self.tabla_mov_stock.verticalHeader().setVisible(False)
        self.tabla_mov_stock.setAlternatingRowColors(True)
        self.tabla_mov_stock.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_mov_stock.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla_mov_stock.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_mov_stock.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        lay_mov.addWidget(self.tabla_mov_stock)
        self.sub_inventario.addTab(pag_mov, "Movimientos de stock del período")

        vbox.addWidget(self.sub_inventario, stretch=1)
        return pag

    def _construir_tab_devoluciones(self) -> QWidget:
        pag = QWidget()
        vbox = QVBoxLayout(pag)
        vbox.setSpacing(10)

        self.filtro_devoluciones = _BarraFiltroReporte("Exportar Devoluciones (.xlsx)", modo_inicial="todos")
        self.filtro_devoluciones.filtro_cambiado.connect(self._recargar_devoluciones)
        self.filtro_devoluciones.exportar_solicitado.connect(
            lambda: self._exportar_excel("devoluciones", self.filtro_devoluciones)
        )
        vbox.addWidget(self.filtro_devoluciones)

        fila_kpi = QHBoxLayout()
        fila_kpi.setSpacing(10)
        t1, self.lbl_dev_total, self.lbl_dev_sub_total = _crear_tarjeta(
            "TOTAL DEVUELTO", "#ea580c", "#c2410c"
        )
        t2, self.lbl_dev_lineas, self.lbl_dev_sub_lineas = _crear_tarjeta(
            "PRODUCTOS DEVUELTOS", "#0891b2", "#0e7490"
        )
        t3, self.lbl_dev_stock, self.lbl_dev_sub_stock = _crear_tarjeta(
            "REPOSICIÓN AL INVENTARIO", "#15803d", "#166534"
        )
        for tarjeta in (t1, t2, t3):
            fila_kpi.addWidget(tarjeta, stretch=1)
        vbox.addLayout(fila_kpi)

        cuerpo = QHBoxLayout()

        grupo_lista = QGroupBox("Devoluciones del período (seleccione una para ver detalle)")
        vbox_l = QVBoxLayout(grupo_lista)
        self.tabla_devoluciones = QTableWidget(0, len(_ENC_DEVOLUCIONES))
        self.tabla_devoluciones.setHorizontalHeaderLabels(_ENC_DEVOLUCIONES)
        self.tabla_devoluciones.verticalHeader().setVisible(False)
        self.tabla_devoluciones.setAlternatingRowColors(True)
        self.tabla_devoluciones.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_devoluciones.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla_devoluciones.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla_devoluciones.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_devoluciones.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tabla_devoluciones.itemSelectionChanged.connect(self._al_seleccionar_devolucion)
        vbox_l.addWidget(self.tabla_devoluciones)
        cuerpo.addWidget(grupo_lista, stretch=5)

        grupo_det = QGroupBox("Detalle de la devolución seleccionada")
        vbox_d = QVBoxLayout(grupo_det)
        self.lbl_detalle_dev = QLabel("Seleccione una devolución en la tabla de la izquierda.")
        self.lbl_detalle_dev.setStyleSheet("font-size: 13pt; font-weight: bold; color: #1e3a8a;")
        self.lbl_detalle_dev.setWordWrap(True)
        vbox_d.addWidget(self.lbl_detalle_dev)

        self.tabla_detalle_dev = QTableWidget(0, len(_ENC_DETALLE_DEV))
        self.tabla_detalle_dev.setHorizontalHeaderLabels(_ENC_DETALLE_DEV)
        self.tabla_detalle_dev.verticalHeader().setVisible(False)
        self.tabla_detalle_dev.setAlternatingRowColors(True)
        self.tabla_detalle_dev.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_detalle_dev.setSelectionMode(QTableWidget.NoSelection)
        self.tabla_detalle_dev.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_detalle_dev.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        vbox_d.addWidget(self.tabla_detalle_dev)
        cuerpo.addWidget(grupo_det, stretch=5)

        vbox.addLayout(cuerpo, stretch=1)
        return pag

    def _construir_tab_caja(self) -> QWidget:
        pag = QWidget()
        vbox = QVBoxLayout(pag)
        vbox.setSpacing(10)

        # Por defecto muestra todos los cierres y turnos para verlos de inmediato
        self.filtro_caja = _BarraFiltroReporte("Exportar Caja (.xlsx)", modo_inicial="todos")
        self.filtro_caja.filtro_cambiado.connect(self._recargar_caja)
        self.filtro_caja.exportar_solicitado.connect(
            lambda: self._exportar_excel("caja", self.filtro_caja)
        )
        vbox.addWidget(self.filtro_caja)

        fila_kpi = QHBoxLayout()
        fila_kpi.setSpacing(10)
        t1, self.lbl_caja_turnos, self.lbl_caja_sub_turnos = _crear_tarjeta(
            "TURNOS / CIERRES", "#2563eb", "#1e3a8a"
        )
        t2, self.lbl_caja_ventas, self.lbl_caja_sub_ventas = _crear_tarjeta(
            "VENTAS EN EFECTIVO", "#15803d", "#166534"
        )
        t3, self.lbl_caja_salidas, self.lbl_caja_sub_salidas = _crear_tarjeta(
            "RETIROS, GASTOS Y DIFERENCIA", "#dc2626", "#b91c1c"
        )
        for tarjeta in (t1, t2, t3):
            fila_kpi.addWidget(tarjeta, stretch=1)
        vbox.addLayout(fila_kpi)

        cuerpo = QHBoxLayout()

        grupo_turnos = QGroupBox("Cierres y turnos de caja (seleccione uno para ver detalle)")
        vbox_t = QVBoxLayout(grupo_turnos)
        self.tabla_caja_turnos = QTableWidget(0, len(_ENC_CAJA))
        self.tabla_caja_turnos.setHorizontalHeaderLabels(_ENC_CAJA)
        self.tabla_caja_turnos.verticalHeader().setVisible(False)
        self.tabla_caja_turnos.setAlternatingRowColors(True)
        self.tabla_caja_turnos.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_caja_turnos.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla_caja_turnos.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla_caja_turnos.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_caja_turnos.itemSelectionChanged.connect(self._al_seleccionar_turno_caja)
        vbox_t.addWidget(self.tabla_caja_turnos)
        cuerpo.addWidget(grupo_turnos, stretch=6)

        grupo_det = QGroupBox("Detalle y retiros/gastos del turno")
        vbox_d = QVBoxLayout(grupo_det)
        self.lbl_detalle_caja = QLabel("Seleccione un cierre en la tabla de la izquierda.")
        self.lbl_detalle_caja.setWordWrap(True)
        self.lbl_detalle_caja.setStyleSheet("font-size: 10pt;")
        vbox_d.addWidget(self.lbl_detalle_caja)

        self.tabla_mov_caja = QTableWidget(0, len(_ENC_MOV_CAJA))
        self.tabla_mov_caja.setHorizontalHeaderLabels(_ENC_MOV_CAJA)
        self.tabla_mov_caja.verticalHeader().setVisible(False)
        self.tabla_mov_caja.setAlternatingRowColors(True)
        self.tabla_mov_caja.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_mov_caja.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_mov_caja.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        vbox_d.addWidget(self.tabla_mov_caja)
        cuerpo.addWidget(grupo_det, stretch=4)

        vbox.addLayout(cuerpo, stretch=1)
        return pag

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.recargar()

    # =====================================================================
    # Carga de datos independiente por submenú
    # =====================================================================
    def recargar(self) -> None:
        self._recargar_ventas()
        self._recargar_inventario()
        self._recargar_devoluciones()
        self._recargar_caja()

    def _recargar_ventas(self) -> None:
        ini, fin = self.filtro_ventas.rango()
        res = reportes.obtener_resumen(ini, fin)
        self.ventas_periodo = reportes.listar_ventas_periodo(ini, fin)
        ranking = reportes.productos_mas_vendidos(ini, fin)

        self.lbl_kpi_neta.setText(formatear_pesos(res["venta_neta"]))
        self.lbl_sub_neta.setText(
            f"Vendido bruto: {formatear_pesos(res['total_bruto'])}  ·  "
            f"Devoluciones ({res['numero_devoluciones']}): −{formatear_pesos(res['total_devoluciones'])}"
        )

        self.lbl_kpi_tickets.setText(f"{res['numero_ventas']} venta(s)")
        self.lbl_sub_tickets.setText(f"Ticket promedio: {formatear_pesos(res['ticket_promedio'])}")

        self.lbl_kpi_medios.setText(f"Efec. neto: {formatear_pesos(res['efectivo_neto'])}")
        self.lbl_sub_medios.setText(
            f"Efectivo: {formatear_pesos(res['ventas_efectivo'])}   ·   "
            f"Transferencia: {formatear_pesos(res['ventas_transferencia'])}"
        )

        self.tabla_ventas.setRowCount(len(self.ventas_periodo))
        mapa_medios = dict(ventas.MEDIOS_PAGO)
        for i, v in enumerate(self.ventas_periodo):
            dev = v["devuelto_de_esta_venta"]
            valores = [
                f"#{v['id']}",
                formatear_fecha_hora_dmy(v["fecha"]),
                mapa_medios.get(v["medio_pago"], v["medio_pago"]),
                formatear_pesos(v["total"]),
                formatear_pesos(dev) if dev > 0 else "—",
            ]
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col in (0, 3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla_ventas.setItem(i, col, item)

        if self.ventas_periodo:
            self.tabla_ventas.selectRow(0)
        else:
            self._cargar_detalle_venta(None)

        self.tabla_productos.setRowCount(len(ranking))
        for i, p in enumerate(ranking):
            es_peso = p["tipo_venta"] == "peso"
            valores = [
                str(i + 1),
                p["codigo_barras"] or "—",
                p["nombre"],
                "Peso (lb)" if es_peso else "Unidad",
                inventario.formatear_stock(p["tipo_venta"], p["cantidad_neta"]),
                formatear_pesos(p["total_vendido"]),
                formatear_pesos(p["valor_devuelto"]) if p["valor_devuelto"] > 0 else "—",
                formatear_pesos(p["venta_neta"]),
            ]
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col in (0, 4, 5, 6, 7):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla_productos.setItem(i, col, item)

    def _recargar_inventario(self) -> None:
        ini, fin = self.filtro_inventario.rango()
        rep = reportes.obtener_reporte_inventario(ini, fin)

        self.lbl_inv_total.setText(f"{rep['total_productos']} producto(s)")
        self.lbl_inv_sub_total.setText(
            f"Por unidad: {rep['por_unidad']}   ·   Por peso: {rep['por_peso']}"
        )

        self.lbl_inv_bajo.setText(f"{rep['stock_bajo']} con stock bajo")
        self.lbl_inv_sub_bajo.setText(f"Sin existencias (≤ 0): {rep['sin_stock']}")

        self.lbl_inv_valor.setText(formatear_pesos(rep["valor_venta_total"]))
        self.lbl_inv_sub_valor.setText(
            f"Movimientos registrados en el filtro: {rep['numero_movimientos']}"
        )

        prods = rep["productos"]
        self.tabla_inventario.setRowCount(len(prods))
        for i, p in enumerate(prods):
            es_peso = p["tipo_venta"] == "peso"
            suf = " / lb" if es_peso else ""
            valores = [
                p["codigo_barras"] or "—",
                p["nombre"],
                p["categoria"] or "—",
                "Peso (lb)" if es_peso else "Unidad",
                inventario.formatear_stock(p["tipo_venta"], p["stock"]),
                inventario.formatear_stock(p["tipo_venta"], p["stock_minimo"]),
                "STOCK BAJO" if p["es_stock_bajo"] else "OK",
                formatear_pesos(p["precio_final"]) + suf,
                formatear_pesos(p["valor_venta"]),
            ]
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col in (4, 5, 7, 8):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 6:
                    color = "#dc2626" if p["es_stock_bajo"] else "#15803d"
                    item.setForeground(QBrush(QColor(color)))
                self.tabla_inventario.setItem(i, col, item)

        movs = rep["movimientos"]
        self.tabla_mov_stock.setRowCount(len(movs))
        for i, m in enumerate(movs):
            signo = "+" if m["cantidad"] > 0 else ""
            cant_txt = f"{signo}{inventario.formatear_stock(m['tipo_venta'], m['cantidad'])}"
            valores = [
                f"#{m['id']}",
                formatear_fecha_hora_dmy(m["fecha"]),
                m["producto_nombre"],
                (m["tipo"] or "").upper(),
                cant_txt,
                inventario.formatear_stock(m["tipo_venta"], m["stock_anterior"]),
                inventario.formatear_stock(m["tipo_venta"], m["stock_nuevo"]),
                m["motivo"] or "—",
            ]
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col in (0, 4, 5, 6):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 4:
                    item.setForeground(QBrush(QColor("#15803d" if m["cantidad"] >= 0 else "#dc2626")))
                self.tabla_mov_stock.setItem(i, col, item)

    def _recargar_devoluciones(self) -> None:
        ini, fin = self.filtro_devoluciones.rango()
        rep = reportes.obtener_reporte_devoluciones(ini, fin)
        self.devoluciones_periodo = rep["devoluciones"]

        self.lbl_dev_total.setText(formatear_pesos(rep["total_devuelto"]))
        self.lbl_dev_sub_total.setText(f"{rep['numero_devoluciones']} devolución(es) registradas")

        self.lbl_dev_lineas.setText(f"{rep['total_lineas']} ítem(s)")
        self.lbl_dev_sub_lineas.setText(
            f"Repuestas al stock: {rep['lineas_repuestas']}  ·  No repuestas: {rep['lineas_no_repuestas']}"
        )

        self.lbl_dev_stock.setText(formatear_pesos(rep["valor_repuesto"]))
        self.lbl_dev_sub_stock.setText(
            f"Valor no repuesto (dañado/merma): {formatear_pesos(rep['valor_no_repuesto'])}"
        )

        self.tabla_devoluciones.setRowCount(len(self.devoluciones_periodo))
        for i, d in enumerate(self.devoluciones_periodo):
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
                self.tabla_devoluciones.setItem(i, col, item)

        if self.devoluciones_periodo:
            self.tabla_devoluciones.selectRow(0)
        else:
            self._cargar_detalle_devolucion(None)

    def _recargar_caja(self) -> None:
        ini, fin = self.filtro_caja.rango()
        rep = reportes.obtener_reporte_caja(ini, fin)
        self.turnos_periodo = rep["turnos"]

        self.lbl_caja_turnos.setText(f"{rep['numero_turnos']} turno(s)")
        self.lbl_caja_sub_turnos.setText(
            f"Cerrados: {rep['turnos_cerrados']}  ·  Abiertos: {rep['turnos_abiertos']}  ·  "
            f"Base: {formatear_pesos(rep['total_base'])}"
        )

        self.lbl_caja_ventas.setText(formatear_pesos(rep["total_ventas_efectivo"]))
        self.lbl_caja_sub_ventas.setText(
            f"Transferencia: {formatear_pesos(rep['total_ventas_transferencia'])}  ·  "
            f"Devoluciones: −{formatear_pesos(rep['total_devoluciones_efectivo'])}"
        )

        self.lbl_caja_salidas.setText(formatear_pesos(rep["total_retiros"]))
        dif_txt, _ = _formatear_diferencia(rep["diferencia_acumulada"])
        self.lbl_caja_sub_salidas.setText(f"Diferencia en cierres: {dif_txt}")

        self.tabla_caja_turnos.setRowCount(len(self.turnos_periodo))
        for i, t in enumerate(self.turnos_periodo):
            if t["abierto"]:
                cierre_txt = "Abierto"
                contado_txt = "—"
                dif_txt_fila, dif_color = "En curso", "#475569"
            else:
                cierre_txt = formatear_fecha_dmy(t["cerrado_en"])
                contado_txt = formatear_pesos(t["efectivo_contado"] or 0)
                dif_txt_fila, dif_color = _formatear_diferencia(t["diferencia"] or 0)

            valores = [
                f"#{t['id']}",
                formatear_fecha_dmy(t["abierto_en"]),
                cierre_txt,
                formatear_pesos(t["fondo_inicial"]),
                formatear_pesos(t["ventas_efectivo"]),
                formatear_pesos(t["ventas_transferencia"]),
                formatear_pesos(t["devoluciones_efectivo"]),
                formatear_pesos(t["retiros_total"]),
                formatear_pesos(t["efectivo_esperado"]),
                contado_txt,
                dif_txt_fila,
            ]
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col >= 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 10:
                    item.setForeground(QBrush(QColor(dif_color)))
                self.tabla_caja_turnos.setItem(i, col, item)

        if self.turnos_periodo:
            self.tabla_caja_turnos.selectRow(0)
        else:
            self._cargar_detalle_caja(None)

    # =====================================================================
    # Detalles al seleccionar filas
    # =====================================================================
    def _al_seleccionar_venta(self) -> None:
        fila = self.tabla_ventas.currentRow()
        if not (0 <= fila < len(self.ventas_periodo)):
            self._cargar_detalle_venta(None)
            return
        vid = self.ventas_periodo[fila]["id"]
        self._cargar_detalle_venta(reportes.obtener_detalle_venta(vid))

    def _cargar_detalle_venta(self, det: dict | None) -> None:
        self.tabla_detalle.setRowCount(0)
        if det is None:
            self.lbl_encabezado_detalle.setText("Seleccione una venta en la tabla de la izquierda.")
            self.lbl_pie_detalle.setText("")
            return

        medio_txt = dict(ventas.MEDIOS_PAGO).get(det["medio_pago"], det["medio_pago"])
        self.lbl_encabezado_detalle.setText(
            f"Venta #{det['id']}  ·  {formatear_fecha_hora_dmy(det['fecha'])}  ·  Medio: {medio_txt}  ·  "
            f"Total: {formatear_pesos(det['total'])}  (Recibido: {formatear_pesos(det['monto_recibido'] or det['total'])}, "
            f"Cambio: {formatear_pesos(det['cambio'] or 0)})"
        )

        items = det["items"]
        self.tabla_detalle.setRowCount(len(items))
        for i, it in enumerate(items):
            es_peso = it["tipo_venta"] == "peso"
            suf = " / lb" if es_peso else ""
            dev_txt = (
                f"{inventario.formatear_stock(it['tipo_venta'], it['cantidad_devuelta'])} "
                f"({formatear_pesos(it['valor_devuelto'])})"
                if it["cantidad_devuelta"] > 0
                else "—"
            )
            valores = [
                it["codigo_barras"] or "—",
                it["nombre"],
                inventario.formatear_stock(it["tipo_venta"], it["cantidad"]),
                formatear_pesos(it["precio_unitario"]) + suf,
                porcentaje_a_texto(it["iva_pct"]),
                formatear_pesos(it["subtotal"]),
                dev_txt,
            ]
            for col, texto in enumerate(valores):
                celda = QTableWidgetItem(texto)
                if col in (2, 3, 4, 5, 6):
                    celda.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla_detalle.setItem(i, col, celda)

        if det["devoluciones"]:
            notas_dev = [
                f"Dev #{d['id']} ({formatear_fecha_hora_dmy(d['fecha'])}): "
                f"{formatear_pesos(d['total_devuelto'])} — {d['motivo']}"
                for d in det["devoluciones"]
            ]
            self.lbl_pie_detalle.setText("Devoluciones de esta venta:  " + "   |   ".join(notas_dev))
        else:
            self.lbl_pie_detalle.setText("Sin devoluciones en esta venta.")

    def _al_seleccionar_devolucion(self) -> None:
        fila = self.tabla_devoluciones.currentRow()
        if not (0 <= fila < len(self.devoluciones_periodo)):
            self._cargar_detalle_devolucion(None)
            return
        self._cargar_detalle_devolucion(self.devoluciones_periodo[fila])

    def _cargar_detalle_devolucion(self, dev: dict | None) -> None:
        self.tabla_detalle_dev.setRowCount(0)
        if dev is None:
            self.lbl_detalle_dev.setText("Seleccione una devolución en la tabla de la izquierda.")
            return

        self.lbl_detalle_dev.setText(
            f"Fecha y hora: {formatear_fecha_hora_dmy(dev['fecha'])}  ·  "
            f"Total: {formatear_pesos(dev['total_devuelto'])}\n"
            f"Motivo: {dev['motivo']}"
        )

        items = dev.get("items", [])
        self.tabla_detalle_dev.setRowCount(len(items))
        for i, it in enumerate(items):
            valores = [
                it["codigo_barras"] or "—",
                it["nombre"],
                inventario.formatear_stock(it["tipo_venta"], it["cantidad"]),
                formatear_pesos(it["valor"]),
                "Sí" if it["repone_stock"] else "No",
            ]
            for col, texto in enumerate(valores):
                celda = QTableWidgetItem(texto)
                if col in (2, 3):
                    celda.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 4:
                    celda.setTextAlignment(Qt.AlignCenter)
                self.tabla_detalle_dev.setItem(i, col, celda)

    def _al_seleccionar_turno_caja(self) -> None:
        fila = self.tabla_caja_turnos.currentRow()
        if not (0 <= fila < len(self.turnos_periodo)):
            self._cargar_detalle_caja(None)
            return
        self._cargar_detalle_caja(self.turnos_periodo[fila])

    def _cargar_detalle_caja(self, turno: dict | None) -> None:
        self.tabla_mov_caja.setRowCount(0)
        if turno is None:
            self.lbl_detalle_caja.setText("Seleccione un cierre en la tabla de la izquierda.")
            return

        cierre_str = (
            formatear_fecha_hora_dmy(turno["cerrado_en"])
            if turno["cerrado_en"]
            else "Turno abierto"
        )
        dif_str = (
            "En curso"
            if turno["abierto"]
            else _formatear_diferencia(turno["diferencia"] or 0)[0]
        )
        self.lbl_detalle_caja.setText(
            f"<b>Turno #{turno['id']}</b><br>"
            f"Apertura: {formatear_fecha_hora_dmy(turno['abierto_en'])}  ·  Cierre: {cierre_str}<br>"
            f"Efectivo en caja: <b>{formatear_pesos(turno['efectivo_esperado'])}</b>  ·  "
            f"Diferencia: <b>{dif_str}</b><br>"
            f"Notas: {turno['notas'] or '—'}"
        )

        movs = turno.get("movimientos", [])
        self.tabla_mov_caja.setRowCount(len(movs))
        for i, m in enumerate(movs):
            valores = [
                formatear_fecha_hora_dmy(m["fecha"]),
                "GASTO" if m["tipo"] == "gasto" else "RETIRO",
                m["motivo"],
                formatear_pesos(m["monto"]),
            ]
            for col, texto in enumerate(valores):
                celda = QTableWidgetItem(texto)
                if col == 3:
                    celda.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla_mov_caja.setItem(i, col, celda)

    # =====================================================================
    # Exportación únicamente a Excel (.xlsx)
    # =====================================================================
    def _exportar_excel(self, modulo: str, barra_filtro: _BarraFiltroReporte) -> None:
        ini, fin = barra_filtro.rango()
        if ini is None and fin is None:
            sugerido = str(Path.home() / "Desktop" / f"reporte_{modulo}_todos.xlsx")
        else:
            sugerido = str(
                Path.home() / "Desktop" / f"reporte_{modulo}_{formatear_fecha_dmy(ini)}_a_{formatear_fecha_dmy(fin)}.xlsx"
            )

        ruta, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar reporte a Excel",
            sugerido,
            "Archivo de Excel (*.xlsx)",
        )
        if not ruta:
            return
        if not ruta.lower().endswith(".xlsx"):
            ruta += ".xlsx"
        try:
            reportes.exportar_reporte_excel(ruta, ini, fin, modulo=modulo)
            QMessageBox.information(self, "Reporte exportado", f"Reporte guardado en:\n{ruta}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo exportar a Excel:\n\n{e}")
