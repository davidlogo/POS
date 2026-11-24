"""
Pantalla de Cierre de Caja y Turnos (Fase 7 - Atajo F9).

Incluye:
  1. Pestaña «Turno actual y cierre»:
     - 6 tarjetas de resumen en la parte superior:
         1. BASE (+)
         2. VENTAS EN EFECTIVO (+)
         3. VENTAS POR TRANSFERENCIA
         4. DEVOLUCIONES EFECTIVO (−)
         5. RETIROS Y GASTOS (−)
         = EFECTIVO EN CAJA
     - Registro de retiros y gastos de caja con motivo + listado del turno (GASTO / RETIRO).
     - En «Realizar cierre de caja»:
         * Calculadora de conteo con espacios para la cantidad de billetes de
           $ 2.000, $ 5.000, $ 10.000, $ 20.000, $ 50.000 y $ 100.000, más un último
           espacio para el Total en monedas ($).
         * Calcula automáticamente el Efectivo contado ($) y la Diferencia en vivo.
  2. Pestaña «Historial de cierres»:
     - Consulta de todos los cierres anteriores con su desglose y sus retiros/gastos.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from modules import caja, respaldos
from ui.comun import CampoNumeroReemplazo, activar_formato_miles
from ui.dialogos.dialogo_abrir_turno import DialogoAbrirTurno
from utils.dinero import formatear_pesos, parsear_pesos
from utils.fechas import formatear_fecha_dmy, formatear_fecha_hora_dmy

_ENC_MOVS = ["Hora", "Tipo", "Motivo", "Monto"]
_ENC_HISTORIAL = [
    "# Turno",
    "Apertura",
    "Cierre",
    "Base",
    "Ventas Efec.",
    "Ventas Transf.",
    "Devoluciones",
    "Retiros/Gastos",
    "Efectivo en caja",
    "Efectivo contado",
    "Diferencia",
]

DENOMINACIONES_BILLETES = (
    2_000,
    5_000,
    10_000,
    20_000,
    50_000,
    100_000,
)


def _tarjeta_caja(titulo: str, color_borde: str, color_texto: str) -> tuple[QFrame, QLabel, QLabel]:
    marco = QFrame()
    marco.setStyleSheet(
        f"QFrame {{ background-color: #ffffff; border: 1px solid #cbd5e1; "
        f"border-left: 4px solid {color_borde}; border-radius: 6px; padding: 2px; }}"
        "QLabel { border: none; }"
    )
    vbox = QVBoxLayout(marco)
    vbox.setContentsMargins(6, 2, 6, 2)
    vbox.setSpacing(0)

    lbl_t = QLabel(titulo)
    lbl_t.setStyleSheet("color: #475569; font-size: 8.2pt; font-weight: bold;")
    lbl_t.setWordWrap(True)
    vbox.addWidget(lbl_t)

    lbl_v = QLabel("$ 0")
    lbl_v.setStyleSheet(f"color: {color_texto}; font-size: 13pt; font-weight: 800;")
    vbox.addWidget(lbl_v)

    lbl_s = QLabel("")
    lbl_s.setStyleSheet("color: #64748b; font-size: 7.8pt;")
    lbl_s.setWordWrap(True)
    vbox.addWidget(lbl_s)
    return marco, lbl_v, lbl_s


def _formatear_diferencia(diferencia: int) -> tuple[str, str]:
    """Devuelve (texto_amigable, color_hex) para una diferencia de caja."""
    if diferencia == 0:
        return "$ 0  (Cuadre exacto)", "#15803d"
    if diferencia > 0:
        return f"+{formatear_pesos(diferencia)}  (Sobrante)", "#15803d"
    return f"{formatear_pesos(diferencia)}  (Faltante)", "#dc2626"


class PantallaCaja(QWidget):
    turno_cambiado = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.estado_actual: dict | None = None
        self.cierres_historial: list[dict] = []
        self._actualizando_conteo = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.sub_pestanas = QTabWidget()
        layout.addWidget(self.sub_pestanas)

        # =====================================================================
        # SUB-PESTAÑA 1: Turno actual y cierre de caja
        # =====================================================================
        pag_actual = QWidget()
        vbox_act = QVBoxLayout(pag_actual)
        vbox_act.setContentsMargins(6, 6, 6, 6)
        vbox_act.setSpacing(6)

        # --- Banda superior: Estado del turno y botón de abrir turno ---
        self.marco_estado = QFrame()
        fila_est = QHBoxLayout(self.marco_estado)
        fila_est.setContentsMargins(8, 3, 8, 3)
        self.lbl_estado_turno = QLabel()
        self.lbl_estado_turno.setStyleSheet("font-size: 11pt; font-weight: bold;")
        self.lbl_estado_turno.setWordWrap(True)
        fila_est.addWidget(self.lbl_estado_turno, stretch=1)

        self.btn_abrir_turno = QPushButton("Abrir turno de caja...")
        self.btn_abrir_turno.setMinimumHeight(30)
        self.btn_abrir_turno.setStyleSheet(
            "QPushButton { background-color: #16a34a; color: white; font-size: 10pt; "
            "font-weight: bold; padding: 4px 12px; border: none; border-radius: 6px; }"
            "QPushButton:hover { background-color: #15803d; }"
        )
        self.btn_abrir_turno.clicked.connect(self._abrir_turno)
        fila_est.addWidget(self.btn_abrir_turno)

        btn_refrescar = QPushButton("Actualizar")
        btn_refrescar.setMinimumHeight(30)
        btn_refrescar.clicked.connect(self.recargar)
        fila_est.addWidget(btn_refrescar)
        vbox_act.addWidget(self.marco_estado)

        # --- 6 Tarjetas de resumen del turno (responsivo: 6x1 >= 1020px, 3x2 en ventanas angostas) ---
        self._grilla_kpis = QGridLayout()
        self._grilla_kpis.setSpacing(5)
        self._cols_kpis_actual = 0

        c1, self.lbl_fondo, self.lbl_sub_fondo = _tarjeta_caja(
            "1. BASE (+)", "#3b82f6", "#1e3a8a"
        )
        c2, self.lbl_v_efec, self.lbl_sub_ventas = _tarjeta_caja(
            "2. VENTAS EFECTIVO (+)", "#16a34a", "#15803d"
        )
        c3, self.lbl_v_transf, self.lbl_sub_transf = _tarjeta_caja(
            "3. TRANSFERENCIAS", "#7c3aed", "#5b21b6"
        )
        c4, self.lbl_devs, self.lbl_sub_devs = _tarjeta_caja(
            "4. DEVOLUCIONES (−)", "#f97316", "#c2410c"
        )
        c5, self.lbl_retiros, self.lbl_sub_retiros = _tarjeta_caja(
            "5. RETIROS / GASTOS (−)", "#dc2626", "#b91c1c"
        )
        c6, self.lbl_esperado, self.lbl_sub_esperado = _tarjeta_caja(
            "= EFECTIVO EN CAJA", "#0f172a", "#0f172a"
        )

        self._tarjetas_kpis = (c1, c2, c3, c4, c5, c6)
        self._acomodar_tarjetas_kpis(6)
        vbox_act.addLayout(self._grilla_kpis)

        # --- Cuerpo inferior: Izquierda (Retiros/Gastos) | Derecha (Cerrar turno con conteo) ---
        cuerpo = QSplitter(Qt.Horizontal)

        # Izquierda: Retiros y gastos de caja
        self.grupo_retiros = QGroupBox("Retiros y gastos de caja del turno actual")
        vbox_ret = QVBoxLayout(self.grupo_retiros)
        vbox_ret.setSpacing(6)

        form_ret = QFormLayout()
        form_ret.setVerticalSpacing(5)
        self.cmb_tipo_mov = QComboBox()
        self.cmb_tipo_mov.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_tipo_mov.setMinimumContentsLength(18)
        for codigo, texto in caja.TIPOS_MOVIMIENTO_CAJA:
            self.cmb_tipo_mov.addItem(texto, codigo)
        form_ret.addRow("Tipo de salida:", self.cmb_tipo_mov)

        fila_monto_mot = QHBoxLayout()
        fila_monto_mot.setSpacing(6)
        self.txt_monto_mov = QLineEdit()
        self.txt_monto_mov.setPlaceholderText("$ 15.000")
        self.txt_monto_mov.setMaximumWidth(120)
        activar_formato_miles(self.txt_monto_mov)
        self.txt_motivo_mov = QLineEdit()
        self.txt_motivo_mov.setPlaceholderText("Motivo obligatorio...")
        self.txt_motivo_mov.setMinimumWidth(90)
        self.txt_motivo_mov.returnPressed.connect(self._registrar_movimiento)
        self.btn_guardar_mov = QPushButton("Registrar")
        self.btn_guardar_mov.setStyleSheet(
            "QPushButton { background-color: #1e40af; color: white; font-weight: bold; }"
        )
        self.btn_guardar_mov.clicked.connect(self._registrar_movimiento)

        fila_monto_mot.addWidget(QLabel("Monto:"))
        fila_monto_mot.addWidget(self.txt_monto_mov)
        fila_monto_mot.addWidget(QLabel("Motivo:"))
        fila_monto_mot.addWidget(self.txt_motivo_mov, stretch=1)
        fila_monto_mot.addWidget(self.btn_guardar_mov)
        form_ret.addRow(fila_monto_mot)
        vbox_ret.addLayout(form_ret)

        self.tabla_movs = QTableWidget(0, len(_ENC_MOVS))
        self.tabla_movs.setHorizontalHeaderLabels(_ENC_MOVS)
        self.tabla_movs.verticalHeader().setVisible(False)
        self.tabla_movs.setAlternatingRowColors(True)
        self.tabla_movs.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_movs.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla_movs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_movs.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        vbox_ret.addWidget(self.tabla_movs)

        cuerpo.addWidget(self.grupo_retiros)

        # Derecha: Formulario de Cierre de Caja con ayuda compacta de conteo (2 columnas x 3 filas)
        self.grupo_cierre = QGroupBox("Realizar cierre de caja")
        vbox_cie = QVBoxLayout(self.grupo_cierre)
        vbox_cie.setContentsMargins(8, 6, 8, 6)
        vbox_cie.setSpacing(4)

        marco_arqueo = QFrame()
        marco_arqueo.setStyleSheet(
            "QFrame { background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; padding: 2px; }"
            "QLabel { border: none; }"
            "QLineEdit { padding: 2px 6px; min-height: 18px; }"
        )
        grilla_arq = QGridLayout(marco_arqueo)
        grilla_arq.setContentsMargins(6, 3, 6, 3)
        grilla_arq.setHorizontalSpacing(6)
        grilla_arq.setVerticalSpacing(3)

        lbl_tit_arq = QLabel("Conteo de billetes y monedas:")
        lbl_tit_arq.setStyleSheet("color: #1e3a8a; font-weight: bold; font-size: 9pt;")
        lbl_tit_arq.setWordWrap(True)
        grilla_arq.addWidget(lbl_tit_arq, 0, 0, 1, 6)

        self.campos_billetes: dict[int, CampoNumeroReemplazo] = {}
        self.etiquetas_subtotal_billete: dict[int, QLabel] = {}

        # 2 columnas de 3 denominaciones cada una para ahorrar altura en pantallas pequeñas
        for idx, denom in enumerate(DENOMINACIONES_BILLETES):
            fila_g = (idx % 3) + 1
            col_base = 0 if idx < 3 else 3

            lbl_d = QLabel(f"{formatear_pesos(denom)}:")
            lbl_d.setStyleSheet("font-weight: 600; font-size: 9pt;")

            txt_cant = CampoNumeroReemplazo()
            txt_cant.setPlaceholderText("0")
            txt_cant.setMaximumWidth(58)
            activar_formato_miles(txt_cant)
            txt_cant.textChanged.connect(self._recalcular_desde_arqueo)

            lbl_sub = QLabel("$ 0")
            lbl_sub.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl_sub.setStyleSheet("color: #475569; font-weight: 600; font-size: 8.8pt;")

            grilla_arq.addWidget(lbl_d, fila_g, col_base)
            grilla_arq.addWidget(txt_cant, fila_g, col_base + 1)
            grilla_arq.addWidget(lbl_sub, fila_g, col_base + 2)

            self.campos_billetes[denom] = txt_cant
            self.etiquetas_subtotal_billete[denom] = lbl_sub

        fila_mon = 4
        lbl_mon = QLabel("Monedas ($):")
        lbl_mon.setStyleSheet("font-weight: bold; color: #0f172a; font-size: 9pt;")
        self.txt_total_monedas = CampoNumeroReemplazo()
        self.txt_total_monedas.setPlaceholderText("$ 0")
        self.txt_total_monedas.setMaximumWidth(100)
        activar_formato_miles(self.txt_total_monedas)
        self.txt_total_monedas.textChanged.connect(self._recalcular_desde_arqueo)

        btn_limpiar_arqueo = QPushButton("Limpiar")
        btn_limpiar_arqueo.setStyleSheet("QPushButton { padding: 3px 10px; font-size: 9pt; }")
        btn_limpiar_arqueo.clicked.connect(self._limpiar_campos_arqueo)

        grilla_arq.addWidget(lbl_mon, fila_mon, 0)
        grilla_arq.addWidget(self.txt_total_monedas, fila_mon, 1, 1, 2)
        grilla_arq.addWidget(btn_limpiar_arqueo, fila_mon, 3, 1, 3, alignment=Qt.AlignRight)

        vbox_cie.addWidget(marco_arqueo)

        # --- Totales de cierre compactos ---
        fila_res_cie = QHBoxLayout()
        fila_res_cie.addWidget(QLabel("En caja:"))
        self.lbl_esperado_cierre = QLabel("$ 0")
        self.lbl_esperado_cierre.setStyleSheet("font-size: 11.5pt; font-weight: 800; color: #0f172a;")
        fila_res_cie.addWidget(self.lbl_esperado_cierre)
        fila_res_cie.addStretch()
        fila_res_cie.addWidget(QLabel("Diferencia:"))
        self.lbl_diferencia = QLabel("—")
        self.lbl_diferencia.setStyleSheet("font-size: 11.5pt; font-weight: 800;")
        fila_res_cie.addWidget(self.lbl_diferencia)
        vbox_cie.addLayout(fila_res_cie)

        form_cie = QFormLayout()
        form_cie.setVerticalSpacing(3)

        self.txt_contado = CampoNumeroReemplazo()
        self.txt_contado.setPlaceholderText("Se calcula con el conteo o escríbalo directo")
        self.txt_contado.setStyleSheet("font-size: 12pt; font-weight: bold; padding: 3px 8px; min-height: 22px;")
        activar_formato_miles(self.txt_contado)
        self.txt_contado.textChanged.connect(self._recalcular_diferencia_en_vivo)
        form_cie.addRow("Contado ($): *", self.txt_contado)

        self.txt_notas_cierre = QLineEdit()
        self.txt_notas_cierre.setPlaceholderText("Opcional: observaciones del turno...")
        self.txt_notas_cierre.setStyleSheet("padding: 3px 8px; min-height: 20px;")
        form_cie.addRow("Observaciones:", self.txt_notas_cierre)
        vbox_cie.addLayout(form_cie)

        self.btn_cerrar_turno = QPushButton("Cerrar turno y guardar cuadre de caja")
        self.btn_cerrar_turno.setMinimumHeight(34)
        self.btn_cerrar_turno.setStyleSheet(
            "QPushButton { background-color: #dc2626; color: white; font-size: 11pt; "
            "font-weight: bold; border: none; border-radius: 7px; }"
            "QPushButton:hover { background-color: #b91c1c; }"
            "QPushButton:disabled { background-color: #cbd5e1; color: #64748b; }"
        )
        self.btn_cerrar_turno.clicked.connect(self._confirmar_cierre)
        vbox_cie.addWidget(self.btn_cerrar_turno)

        cuerpo.addWidget(self.grupo_cierre)
        cuerpo.setStretchFactor(0, 5)
        cuerpo.setStretchFactor(1, 5)
        vbox_act.addWidget(cuerpo, stretch=1)

        self.sub_pestanas.addTab(pag_actual, "Turno actual y cierre de caja")

        # =====================================================================
        # SUB-PESTAÑA 2: Historial de cierres pasados
        # =====================================================================
        pag_hist = QWidget()
        lay_hist = QHBoxLayout(pag_hist)
        div_hist = QSplitter(Qt.Horizontal)
        lay_hist.addWidget(div_hist)

        grupo_tabla_h = QGroupBox("Turnos cerrados (seleccione uno para ver su detalle)")
        vbox_th = QVBoxLayout(grupo_tabla_h)
        self.tabla_historial = QTableWidget(0, len(_ENC_HISTORIAL))
        self.tabla_historial.setHorizontalHeaderLabels(_ENC_HISTORIAL)
        self.tabla_historial.verticalHeader().setVisible(False)
        self.tabla_historial.setAlternatingRowColors(True)
        self.tabla_historial.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_historial.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla_historial.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla_historial.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_historial.itemSelectionChanged.connect(self._al_seleccionar_cierre_historial)
        vbox_th.addWidget(self.tabla_historial)
        div_hist.addWidget(grupo_tabla_h)

        grupo_det_h = QGroupBox("Detalle del cierre seleccionado")
        vbox_dh = QVBoxLayout(grupo_det_h)
        self.lbl_detalle_historial = QLabel("Seleccione un cierre en la tabla de la izquierda.")
        self.lbl_detalle_historial.setWordWrap(True)
        self.lbl_detalle_historial.setStyleSheet("font-size: 10.5pt;")
        vbox_dh.addWidget(self.lbl_detalle_historial)

        vbox_dh.addWidget(QLabel("Retiros y gastos registrados en ese turno:"))
        self.tabla_movs_hist = QTableWidget(0, len(_ENC_MOVS))
        self.tabla_movs_hist.setHorizontalHeaderLabels(_ENC_MOVS)
        self.tabla_movs_hist.verticalHeader().setVisible(False)
        self.tabla_movs_hist.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_movs_hist.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_movs_hist.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        vbox_dh.addWidget(self.tabla_movs_hist)
        div_hist.addWidget(grupo_det_h)
        div_hist.setStretchFactor(0, 3)
        div_hist.setStretchFactor(1, 2)

        self.sub_pestanas.addTab(pag_hist, "Historial de cierres")

        self.recargar()

    def _acomodar_tarjetas_kpis(self, columnas: int) -> None:
        if columnas == self._cols_kpis_actual:
            return
        self._cols_kpis_actual = columnas
        for card in self._tarjetas_kpis:
            self._grilla_kpis.removeWidget(card)
        for idx, card in enumerate(self._tarjetas_kpis):
            self._grilla_kpis.addWidget(card, idx // columnas, idx % columnas)
        for col in range(6):
            self._grilla_kpis.setColumnStretch(col, 1 if col < columnas else 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._acomodar_tarjetas_kpis(6 if self.width() >= 1020 else 3)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.recargar()

    def enfocar_cierre(self) -> None:
        """Muestra la pestaña de cierre actual y enfoca el conteo de efectivo."""
        self.sub_pestanas.setCurrentIndex(0)
        self.recargar()
        self.txt_contado.setFocus()

    # =====================================================================
    # Calculadora de conteo de billetes y monedas
    # =====================================================================
    def _limpiar_campos_arqueo(self) -> None:
        self._actualizando_conteo = True
        try:
            for denom, campo in self.campos_billetes.items():
                campo.clear()
                self.etiquetas_subtotal_billete[denom].setText("$ 0")
            self.txt_total_monedas.clear()
            self.txt_contado.clear()
        finally:
            self._actualizando_conteo = False
        self._recalcular_diferencia_en_vivo()

    def _recalcular_desde_arqueo(self) -> None:
        if self._actualizando_conteo:
            return
        total_contado = 0
        algun_dato = False

        for denom, campo in self.campos_billetes.items():
            txt = campo.text().replace(".", "").strip()
            if txt and txt.isdigit():
                cant = int(txt)
                algun_dato = True
            else:
                cant = 0
            sub = cant * denom
            total_contado += sub
            self.etiquetas_subtotal_billete[denom].setText(formatear_pesos(sub))

        txt_mon = self.txt_total_monedas.text().replace(".", "").strip()
        if txt_mon and txt_mon.isdigit():
            total_contado += int(txt_mon)
            algun_dato = True

        self._actualizando_conteo = True
        try:
            if algun_dato:
                self.txt_contado.setText(f"{total_contado:,}".replace(",", "."))
            else:
                self.txt_contado.clear()
        finally:
            self._actualizando_conteo = False
        self._recalcular_diferencia_en_vivo()

    # =====================================================================
    # Carga de estado actual e historial
    # =====================================================================
    def recargar(self) -> None:
        self.estado_actual = caja.calcular_estado_turno()
        abierto = self.estado_actual is not None and self.estado_actual["abierto"]

        self.btn_abrir_turno.setVisible(not abierto)
        self.grupo_retiros.setEnabled(abierto)
        self.grupo_cierre.setEnabled(abierto)

        if not abierto:
            self.marco_estado.setStyleSheet(
                "QFrame { background-color: #fff3cd; border: 1px solid #ffeeba; border-radius: 8px; padding: 8px; }"
                "QLabel { color: #856404; border: none; }"
            )
            self.lbl_estado_turno.setText(
                "⚠ CAJA CERRADA — Abra un turno con la base inicial para poder vender."
            )
            for lbl in (self.lbl_fondo, self.lbl_v_efec, self.lbl_v_transf,
                        self.lbl_devs, self.lbl_retiros, self.lbl_esperado):
                lbl.setText("$ 0")
            for sub in (self.lbl_sub_fondo, self.lbl_sub_ventas, self.lbl_sub_transf,
                        self.lbl_sub_devs, self.lbl_sub_retiros, self.lbl_sub_esperado):
                sub.setText("")
            self.tabla_movs.setRowCount(0)
            self.lbl_esperado_cierre.setText("$ 0")
            self.lbl_diferencia.setText("—")
        else:
            est = self.estado_actual
            self.marco_estado.setStyleSheet(
                "QFrame { background-color: #dcfce7; border: 1px solid #86efac; border-radius: 8px; padding: 8px; }"
                "QLabel { color: #166534; border: none; }"
            )
            self.lbl_estado_turno.setText(
                f"✓ TURNO #{est['id']} ABIERTO   ·   Desde: {formatear_fecha_hora_dmy(est['abierto_en'])}"
            )

            self.lbl_fondo.setText(formatear_pesos(est["fondo_inicial"]))
            self.lbl_sub_fondo.setText("Base al abrir turno")

            self.lbl_v_efec.setText(formatear_pesos(est["ventas_efectivo"]))
            self.lbl_sub_ventas.setText(
                f"{est['numero_ventas']} venta(s) · Total general: {formatear_pesos(est['ventas_total'])}"
            )

            self.lbl_v_transf.setText(formatear_pesos(est["ventas_transferencia"]))
            self.lbl_sub_transf.setText("No suma al cajón físico")

            self.lbl_devs.setText(formatear_pesos(est["devoluciones_efectivo"]))
            self.lbl_sub_devs.setText(f"{est['numero_devoluciones']} devolución(es)")

            self.lbl_retiros.setText(formatear_pesos(est["retiros_total"]))
            self.lbl_sub_retiros.setText(f"{len(est['movimientos'])} salida(s) registrada(s)")

            self.lbl_esperado.setText(formatear_pesos(est["efectivo_esperado"]))
            self.lbl_sub_esperado.setText("Base + Ventas Efec. − Dev. − Retiros")

            self.lbl_esperado_cierre.setText(formatear_pesos(est["efectivo_esperado"]))

            # Tabla de retiros/gastos del turno actual (Tipo en MAYÚSCULAS)
            movs = est["movimientos"]
            self.tabla_movs.setRowCount(len(movs))
            for i, m in enumerate(movs):
                valores = [
                    formatear_fecha_hora_dmy(m["fecha"]),
                    "GASTO" if m["tipo"] == "gasto" else "RETIRO",
                    m["motivo"],
                    formatear_pesos(m["monto"]),
                ]
                for col, texto in enumerate(valores):
                    item = QTableWidgetItem(texto)
                    if col == 3:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.tabla_movs.setItem(i, col, item)

            self._recalcular_diferencia_en_vivo()

        self._recargar_historial()

    def _recargar_historial(self) -> None:
        self.cierres_historial = caja.listar_cierres(limite=100)
        self.tabla_historial.setRowCount(len(self.cierres_historial))

        for i, c in enumerate(self.cierres_historial):
            otros = (c["ventas_tarjeta"] or 0) + (c["ventas_transferencia"] or 0)
            dif = c["diferencia"] or 0
            dif_txt, dif_color = _formatear_diferencia(dif)
            valores = [
                f"#{c['id']}",
                formatear_fecha_dmy(c["abierto_en"]),
                formatear_fecha_dmy(c["cerrado_en"]),
                formatear_pesos(c["fondo_inicial"]),
                formatear_pesos(c["ventas_efectivo"] or 0),
                formatear_pesos(otros),
                formatear_pesos(c["devoluciones_efectivo"] or 0),
                formatear_pesos(c["retiros_total"] or 0),
                formatear_pesos(c["efectivo_esperado"] or 0),
                formatear_pesos(c["efectivo_contado"] or 0),
                dif_txt,
            ]
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col >= 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if col == 10:
                    item.setForeground(QBrush(QColor(dif_color)))
                self.tabla_historial.setItem(i, col, item)

        if self.cierres_historial:
            self.tabla_historial.setCurrentCell(0, 0)
            self.tabla_historial.selectRow(0)
        else:
            self.lbl_detalle_historial.setText("Aún no hay cierres de caja registrados.")
            self.tabla_movs_hist.setRowCount(0)

    def _al_seleccionar_cierre_historial(self) -> None:
        fila = self.tabla_historial.currentRow()
        if not (0 <= fila < len(self.cierres_historial)):
            return
        tid = self.cierres_historial[fila]["id"]
        det = caja.calcular_estado_turno(tid)
        if not det:
            return
        dif_txt, _ = _formatear_diferencia(det["diferencia"] or 0)
        self.lbl_detalle_historial.setText(
            f"<b>Turno #{det['id']}</b><br>"
            f"Abierto: {formatear_fecha_hora_dmy(det['abierto_en'])}  ·  "
            f"Cerrado: {formatear_fecha_hora_dmy(det['cerrado_en'])}<br><br>"
            f"• Base: <b>{formatear_pesos(det['fondo_inicial'])}</b><br>"
            f"• Ventas en Efectivo: <b>{formatear_pesos(det['ventas_efectivo'])}</b><br>"
            f"• Ventas por Transferencia: <b>{formatear_pesos(det['ventas_transferencia'])}</b><br>"
            f"• Devoluciones en efectivo: <b>−{formatear_pesos(det['devoluciones_efectivo'])}</b><br>"
            f"• Retiros y gastos: <b>−{formatear_pesos(det['retiros_total'])}</b><br>"
            f"• Efectivo en caja: <b>{formatear_pesos(det['efectivo_esperado'])}</b><br>"
            f"• Efectivo contado: <b>{formatear_pesos(det['efectivo_contado'] or 0)}</b><br>"
            f"• Diferencia: <b>{dif_txt}</b><br>"
            f"• Notas: {det['notas'] or '—'}"
        )
        movs = det["movimientos"]
        self.tabla_movs_hist.setRowCount(len(movs))
        for i, m in enumerate(movs):
            valores = [
                formatear_fecha_hora_dmy(m["fecha"]),
                "GASTO" if m["tipo"] == "gasto" else "RETIRO",
                m["motivo"],
                formatear_pesos(m["monto"]),
            ]
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col == 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla_movs_hist.setItem(i, col, item)

    # =====================================================================
    # Acciones: Abrir turno, Registrar retiro/gasto, Cerrar turno
    # =====================================================================
    def _abrir_turno(self) -> None:
        dlg = DialogoAbrirTurno(self)
        if dlg.exec():
            self._limpiar_campos_arqueo()
            self.txt_notas_cierre.clear()
            self.recargar()
            self.turno_cambiado.emit()

    def _registrar_movimiento(self) -> None:
        try:
            monto = parsear_pesos(self.txt_monto_mov.text())
        except ValueError:
            QMessageBox.warning(
                self,
                "Retiros y gastos",
                "Escriba un monto válido en pesos sin decimales (ej. 15.000).",
            )
            self.txt_monto_mov.setFocus()
            return
        motivo = self.txt_motivo_mov.text().strip()
        if not motivo:
            QMessageBox.warning(self, "Retiros y gastos", "Escriba el motivo de la salida de dinero.")
            self.txt_motivo_mov.setFocus()
            return

        try:
            caja.registrar_movimiento_caja(self.cmb_tipo_mov.currentData(), monto, motivo)
        except caja.ErrorCaja as e:
            QMessageBox.warning(self, "Retiros y gastos", str(e))
            return

        self.txt_monto_mov.clear()
        self.txt_motivo_mov.clear()
        self.recargar()

    def _recalcular_diferencia_en_vivo(self) -> None:
        if not self.estado_actual or not self.estado_actual["abierto"]:
            self.lbl_diferencia.setText("—")
            return
        texto = self.txt_contado.text().strip()
        if not texto:
            self.lbl_diferencia.setText("Ingrese el conteo o el efectivo contado")
            self.lbl_diferencia.setStyleSheet("font-size: 12pt; color: #64748b;")
            return
        try:
            contado = parsear_pesos(texto)
        except ValueError:
            self.lbl_diferencia.setText("Monto no válido")
            self.lbl_diferencia.setStyleSheet("font-size: 13pt; color: #dc2626; font-weight: bold;")
            return

        dif = contado - self.estado_actual["efectivo_esperado"]
        dif_txt, color = _formatear_diferencia(dif)
        self.lbl_diferencia.setText(dif_txt)
        self.lbl_diferencia.setStyleSheet(f"font-size: 14pt; font-weight: 800; color: {color};")

    def _confirmar_cierre(self) -> None:
        if not self.estado_actual or not self.estado_actual["abierto"]:
            return
        try:
            contado = parsear_pesos(self.txt_contado.text())
        except ValueError:
            QMessageBox.warning(
                self,
                "Cierre de caja",
                "Use los espacios de conteo de billetes/monedas o escriba el efectivo físico contado.",
            )
            self.txt_contado.setFocus()
            return

        esperado = self.estado_actual["efectivo_esperado"]
        dif = contado - esperado
        dif_txt, _ = _formatear_diferencia(dif)

        if QMessageBox.question(
            self,
            "Confirmar cierre de caja",
            f"¿Cerrar el Turno #{self.estado_actual['id']}?\n\n"
            f"• Efectivo en caja:   {formatear_pesos(esperado)}\n"
            f"• Efectivo contado:   {formatear_pesos(contado)}\n"
            f"• Diferencia:         {dif_txt}",
        ) != QMessageBox.Yes:
            return

        try:
            cierre = caja.cerrar_turno(contado, self.txt_notas_cierre.text())
        except caja.ErrorCaja as e:
            QMessageBox.warning(self, "Cierre de caja", str(e))
            return

        nota_respaldo = ""
        try:
            info_resp = respaldos.respaldar_por_cierre_caja()
            depurados = info_resp.get("eliminados_dia", 0)
            extra_dep = (
                f" ({depurados} copia(s) automática(s) anterior(es) del día reemplazada(s))"
                if depurados > 0
                else ""
            )
            nota_respaldo = f"\n\nCopia de seguridad guardada: {info_resp['ruta'].name}{extra_dep}"
        except Exception as e:  # noqa: BLE001
            nota_respaldo = f"\n\nAviso: no se pudo crear la copia de seguridad ({e})"

        self._limpiar_campos_arqueo()
        self.txt_notas_cierre.clear()
        dif_final, _ = _formatear_diferencia(cierre["diferencia"])
        QMessageBox.information(
            self,
            "Turno cerrado",
            f"El Turno #{cierre['id']} se cerró correctamente.\n\n"
            f"Efectivo en caja:  {formatear_pesos(cierre['efectivo_esperado'])}\n"
            f"Efectivo contado:  {formatear_pesos(cierre['efectivo_contado'])}\n"
            f"Resultado:         {dif_final}{nota_respaldo}",
        )
        self.recargar()
        self.turno_cambiado.emit()
