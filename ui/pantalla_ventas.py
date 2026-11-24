"""
Pantalla principal de Ventas.

Características:
  - Campo de código/búsqueda siempre enfocado para la pistola lectora.
  - Despliega en vivo la lista de productos a medida que se escribe.
  - Sin cuadros de diálogo para productos por peso: al agregar un producto por peso,
    se inserta en la tabla y el cursor salta directamente a su campo «Cantidad (g)»
    obligando a escribir los gramos y presionar Enter.
  - Medios de pago: Efectivo y Transferencia.
  - Tarjeta fija de «Última venta cobrada» con el CAMBIO A ENTREGAR en la interfaz.
"""

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from hardware.cajon import abrir_cajon
from modules import ajustes, caja, inventario, ventas
from ui.comun import FlowLayout, activar_formato_miles
from ui.dialogos.dialogo_abrir_turno import DialogoAbrirTurno
from ui.dialogos.dialogo_buscar_producto import DialogoBuscarProducto
from ui.dialogos.dialogo_ventas_espera import DialogoVentasEspera
from utils.dinero import formatear_pesos, parsear_pesos

_ENCABEZADOS_CARRITO = ["Código", "Producto", "Cantidad", "Precio unit.", "Subtotal"]


class _CampoCantidadCarrito(QLineEdit):
    """
    Cuadro de cantidad del carrito:
      - Su tamaño y fuente se adaptan dinámicamente al tamaño de texto de listas configurado.
      - Al hacer clic con el mouse o entrar al cuadro, la primera tecla numérica que se escriba
        reemplaza automáticamente el valor anterior sin tener que borrarlo primero.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("campo_cantidad_carrito")
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._reemplazar_al_escribir = False

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._reemplazar_al_escribir = True
        QTimer.singleShot(0, self.selectAll)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        self._reemplazar_al_escribir = True
        QTimer.singleShot(0, self.selectAll)

    def keyPressEvent(self, event) -> None:
        texto_tecla = event.text()
        if self._reemplazar_al_escribir and texto_tecla and texto_tecla.isdigit():
            self._reemplazar_al_escribir = False
            # Reemplazamos de inmediato el valor anterior por el nuevo dígito escrito
            self.setText(texto_tecla)
            self.textEdited.emit(self.text())
            return
        if event.key() in (Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Left, Qt.Key_Right):
            self._reemplazar_al_escribir = False
        super().keyPressEvent(event)


class PantallaVentas(QWidget):
    venta_registrada = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.carrito = ventas.Carrito()
        self.espera = ventas.GestorVentasEnEspera()
        self.medio_pago: str = "efectivo"
        self.sugerencias_actuales: list[dict] = []
        self.campos_cantidad: list[QLineEdit] = []
        self.etiquetas_unidad: list[QLabel] = []
        self.cajas_cantidad: list[QFrame] = []

        layout_raiz = QHBoxLayout(self)
        layout_raiz.setContentsMargins(8, 8, 8, 8)
        layout_raiz.setSpacing(10)

        # =====================================================================
        # COLUMNA IZQUIERDA: Lector con lista desplegable en vivo + Carrito + Acciones
        # =====================================================================
        col_izq = QVBoxLayout()
        col_izq.setSpacing(6)

        # --- Barra superior: Lector de código de barras + Búsqueda + Espera + Cajón ---
        marco_lector = QFrame()
        marco_lector.setStyleSheet(
            "QFrame { background-color: #1e293b; border-radius: 8px; padding: 4px; }"
            "QLabel { color: #e2e8f0; font-weight: bold; }"
        )
        vbox_lector = QVBoxLayout(marco_lector)
        vbox_lector.setContentsMargins(6, 6, 6, 6)
        vbox_lector.setSpacing(6)

        fila_lector = QHBoxLayout()
        fila_lector.setSpacing(6)

        lbl_icono = QLabel("🔍 Código o nombre:")
        lbl_icono.setStyleSheet("font-size: 11pt; color: #f8fafc;")
        fila_lector.addWidget(lbl_icono)

        self.txt_lector = QLineEdit()
        self.txt_lector.setPlaceholderText(
            "Escanee el código o escriba el nombre para buscar..."
        )
        self.txt_lector.setClearButtonEnabled(True)
        self.txt_lector.setMinimumHeight(36)
        self.txt_lector.setStyleSheet(
            "QLineEdit { font-size: 12.5pt; font-weight: 600; background-color: #ffffff; "
            "color: #0f172a; border: 2px solid #38bdf8; border-radius: 6px; padding: 3px 8px; }"
            "QLineEdit:focus { border: 2px solid #22c55e; background-color: #ffffff; }"
        )
        self.txt_lector.textChanged.connect(self._al_escribir_en_lector)
        self.txt_lector.returnPressed.connect(self._procesar_entrada_lector)
        self.txt_lector.installEventFilter(self)
        fila_lector.addWidget(self.txt_lector, stretch=1)
        vbox_lector.addLayout(fila_lector)

        fila_btns_lector = FlowLayout(margin=0, h_spacing=6, v_spacing=4)

        self.btn_buscar = QPushButton("Catálogo (F2)")
        self.btn_buscar.setMinimumHeight(32)
        self.btn_buscar.setStyleSheet(
            "QPushButton { background-color: #2563eb; color: white; border: none; padding: 4px 10px; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        self.btn_buscar.clicked.connect(lambda: self._abrir_buscador(""))
        fila_btns_lector.addWidget(self.btn_buscar)

        self.btn_poner_espera = QPushButton("Poner en espera (F4)")
        self.btn_poner_espera.setMinimumHeight(32)
        self.btn_poner_espera.setStyleSheet(
            "QPushButton { background-color: #475569; color: white; border: none; padding: 4px 10px; }"
            "QPushButton:hover { background-color: #334155; }"
        )
        self.btn_poner_espera.clicked.connect(self._poner_en_espera)
        fila_btns_lector.addWidget(self.btn_poner_espera)

        self.btn_ver_espera = QPushButton("En espera: 0 (F5)")
        self.btn_ver_espera.setMinimumHeight(32)
        self.btn_ver_espera.setStyleSheet(
            "QPushButton { background-color: #d97706; color: white; border: none; padding: 4px 10px; }"
            "QPushButton:hover { background-color: #b45309; }"
        )
        self.btn_ver_espera.clicked.connect(self._recuperar_en_espera)
        fila_btns_lector.addWidget(self.btn_ver_espera)

        self.btn_abrir_cajon = QPushButton("Abrir cajón (Ctrl+J)")
        self.btn_abrir_cajon.setMinimumHeight(32)
        self.btn_abrir_cajon.setStyleSheet(
            "QPushButton { background-color: #0891b2; color: white; border: none; padding: 4px 10px; }"
            "QPushButton:hover { background-color: #0e7490; }"
        )
        self.btn_abrir_cajon.clicked.connect(self._abrir_cajon_manual)
        fila_btns_lector.addWidget(self.btn_abrir_cajon)

        self.btn_cancelar = QPushButton("Cancelar venta")
        self.btn_cancelar.setMinimumHeight(32)
        self.btn_cancelar.setStyleSheet(
            "QPushButton { background-color: #fee2e2; color: #991b1b; border: 1px solid #f87171; padding: 4px 10px; }"
            "QPushButton:hover { background-color: #fecaca; }"
            "QPushButton:disabled { background-color: #334155; color: #94a3b8; border: 1px solid #475569; }"
        )
        self.btn_cancelar.clicked.connect(self._cancelar_venta)

        fila_inferior_lector = QHBoxLayout()
        fila_inferior_lector.setSpacing(8)
        fila_inferior_lector.addLayout(fila_btns_lector, stretch=1)
        fila_inferior_lector.addWidget(self.btn_cancelar, alignment=Qt.AlignRight | Qt.AlignTop)

        vbox_lector.addLayout(fila_inferior_lector)
        col_izq.addWidget(marco_lector)

        # --- Lista desplegable en vivo a medida que se escribe (altura dinámica según resultados) ---
        self.lista_sugerencias = QListWidget()
        self.lista_sugerencias.setVisible(False)
        self.lista_sugerencias.setStyleSheet(
            "QListWidget { background-color: #ffffff; color: #0f172a; border: 2px solid #2563eb; "
            "border-radius: 6px; padding: 2px; }"
            "QListWidget::item { color: #0f172a; padding: 6px 10px; border-bottom: 1px solid #f1f5f9; }"
            "QListWidget::item:selected { background-color: #dbeafe; color: #1e3a8a; font-weight: bold; }"
            "QListWidget::item:hover { background-color: #dbeafe; color: #0f172a; }"
            "QListWidget::item:selected:hover { background-color: #bfdbfe; color: #1e3a8a; font-weight: bold; }"
        )
        self.lista_sugerencias.itemClicked.connect(self._al_clic_sugerencia)
        col_izq.addWidget(self.lista_sugerencias)

        # --- Tabla del carrito ---
        self.tabla = QTableWidget(0, len(_ENCABEZADOS_CARRITO))
        self.tabla.setObjectName("tabla_carrito_ventas")
        self.tabla.setHorizontalHeaderLabels(_ENCABEZADOS_CARRITO)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.tabla.itemSelectionChanged.connect(self._actualizar_estado_botones)
        self.tabla.cellDoubleClicked.connect(lambda *_: self._cambiar_cantidad_actual())
        self.tabla.installEventFilter(self)
        col_izq.addWidget(self.tabla, stretch=1)

        layout_raiz.addLayout(col_izq, stretch=3)

        # =====================================================================
        # COLUMNA DERECHA (ancho estable fijo para que nunca salte al agregar productos)
        # =====================================================================
        panel_der = QWidget()
        panel_der.setFixedWidth(360)
        col_der = QVBoxLayout(panel_der)
        col_der.setContentsMargins(0, 0, 0, 0)
        col_der.setSpacing(6)

        # --- Tarjeta de TOTAL A COBRAR ---
        marco_total = QFrame()
        marco_total.setStyleSheet(
            "QFrame { background-color: #0f172a; border-radius: 10px; padding: 6px; }"
        )
        vbox_total = QVBoxLayout(marco_total)
        vbox_total.setContentsMargins(8, 4, 8, 4)
        vbox_total.setSpacing(2)
        lbl_tit_total = QLabel("TOTAL A COBRAR")
        lbl_tit_total.setAlignment(Qt.AlignCenter)
        lbl_tit_total.setStyleSheet("color: #94a3b8; font-size: 10pt; font-weight: bold;")
        vbox_total.addWidget(lbl_tit_total)

        self.lbl_total_grande = QLabel("$ 0")
        self.lbl_total_grande.setAlignment(Qt.AlignCenter)
        self.lbl_total_grande.setStyleSheet(
            "color: #4ade80; font-size: 26pt; font-weight: 800; margin: 0;"
        )
        vbox_total.addWidget(self.lbl_total_grande)

        self.lbl_resumen_items = QLabel("0 productos · IVA incluido: $ 0")
        self.lbl_resumen_items.setAlignment(Qt.AlignCenter)
        self.lbl_resumen_items.setStyleSheet("color: #cbd5e1; font-size: 9.5pt;")
        vbox_total.addWidget(self.lbl_resumen_items)
        col_der.addWidget(marco_total)

        # --- Grupo: Medio de pago y efectivo recibido ---
        grupo_pago = QGroupBox("Pago y cambio")
        vbox_pago = QVBoxLayout(grupo_pago)
        vbox_pago.setContentsMargins(8, 6, 8, 6)
        vbox_pago.setSpacing(5)

        fila_medios = QHBoxLayout()
        self.grupo_medios = QButtonGroup(self)
        self.grupo_medios.setExclusive(True)
        self.botones_medio: dict[str, QPushButton] = {}
        estilo_medio = (
            "QPushButton { padding: 6px 6px; font-size: 10.5pt; border: 2px solid #cbd5e1; "
            "border-radius: 6px; background: #f8fafc; }"
            "QPushButton:checked { background-color: #1e40af; color: white; border-color: #1e3a8a; }"
        )
        for codigo, texto in ventas.MEDIOS_PAGO:
            btn = QPushButton(texto)
            btn.setCheckable(True)
            btn.setStyleSheet(estilo_medio)
            btn.clicked.connect(lambda _, c=codigo: self._cambiar_medio_pago(c))
            self.grupo_medios.addButton(btn)
            self.botones_medio[codigo] = btn
            fila_medios.addWidget(btn)
        self.botones_medio["efectivo"].setChecked(True)
        vbox_pago.addLayout(fila_medios)

        # Monto recibido
        self.lbl_recibido = QLabel("Monto recibido del cliente:")
        vbox_pago.addWidget(self.lbl_recibido)

        self.txt_recibido = QLineEdit()
        self.txt_recibido.setPlaceholderText("Vacío = pago exacto")
        self.txt_recibido.setMinimumHeight(34)
        self.txt_recibido.setAlignment(Qt.AlignRight)
        self.txt_recibido.setStyleSheet(
            "QLineEdit { font-size: 14pt; font-weight: bold; color: #0f172a; }"
        )
        activar_formato_miles(self.txt_recibido)
        self.txt_recibido.textChanged.connect(self._recalcular_cambio_en_vivo)
        self.txt_recibido.returnPressed.connect(self._cobrar)
        self.txt_recibido.installEventFilter(self)
        vbox_pago.addWidget(self.txt_recibido)

        # Billetes rápidos (5 botones grandes y simétricos, sin "Exacto")
        self.marco_billetes = QWidget()
        grilla_billetes = QGridLayout(self.marco_billetes)
        grilla_billetes.setContentsMargins(0, 2, 0, 2)
        grilla_billetes.setSpacing(6)
        billetes = [
            ("$ 5.000", 5_000, 0, 0, 2),
            ("$ 10.000", 10_000, 0, 2, 2),
            ("$ 20.000", 20_000, 0, 4, 2),
            ("$ 50.000", 50_000, 1, 0, 3),
            ("$ 100.000", 100_000, 1, 3, 3),
        ]
        for etiqueta, valor, fila_b, col_b, span_b in billetes:
            b = QPushButton(etiqueta)
            b.setMinimumHeight(40)
            b.setStyleSheet(
                "QPushButton { background-color: #f1f5f9; border: 1px solid #94a3b8; "
                "font-size: 11.5pt; font-weight: bold; padding: 6px 8px; }"
                "QPushButton:hover { background-color: #e2e8f0; }"
            )
            b.clicked.connect(lambda _, v=valor: self._usar_billete_rapido(v))
            grilla_billetes.addWidget(b, fila_b, col_b, 1, span_b)
        vbox_pago.addWidget(self.marco_billetes)

        # Recuadro de CAMBIO A ENTREGAR (compacto en una fila)
        marco_cambio = QFrame()
        marco_cambio.setStyleSheet(
            "QFrame { background-color: #ecfdf5; border: 2px solid #10b981; border-radius: 8px; padding: 4px; }"
        )
        fila_cambio = QHBoxLayout(marco_cambio)
        fila_cambio.setContentsMargins(8, 3, 8, 3)
        self.lbl_titulo_cambio = QLabel("CAMBIO A ENTREGAR:")
        self.lbl_titulo_cambio.setStyleSheet("color: #065f46; font-size: 10pt; font-weight: bold; border: none;")
        fila_cambio.addWidget(self.lbl_titulo_cambio)

        self.lbl_cambio_vivo = QLabel("$ 0")
        self.lbl_cambio_vivo.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_cambio_vivo.setStyleSheet(
            "color: #047857; font-size: 18pt; font-weight: 800; border: none;"
        )
        fila_cambio.addWidget(self.lbl_cambio_vivo, stretch=1)
        vbox_pago.addWidget(marco_cambio)

        # Botón grande COBRAR (Espacio / F12)
        self.btn_cobrar = QPushButton("COBRAR VENTA  (Espacio / F12)")
        self.btn_cobrar.setMinimumHeight(44)
        self.btn_cobrar.setStyleSheet(
            "QPushButton { background-color: #16a34a; color: white; font-size: 13pt; "
            "font-weight: 800; border: none; border-radius: 8px; }"
            "QPushButton:hover { background-color: #15803d; }"
            "QPushButton:disabled { background-color: #cbd5e1; color: #64748b; }"
        )
        self.btn_cobrar.clicked.connect(self._cobrar)
        vbox_pago.addWidget(self.btn_cobrar)

        col_der.addWidget(grupo_pago)
        col_der.addStretch()

        layout_raiz.addWidget(panel_der)

        self._registrar_atajos()
        self._refrescar_vista()

    def _registrar_atajos(self) -> None:
        atajos = [
            ("F2", lambda: self._abrir_buscador(self.txt_lector.text().strip())),
            ("F3", self._cambiar_cantidad_actual),
            ("F4", self._poner_en_espera),
            ("F5", self._recuperar_en_espera),
            ("F8", self._quitar_actual),
            ("F12", self._cobrar),
            ("Ctrl+J", self._abrir_cajon_manual),
            ("Escape", self._escape_al_lector),
        ]
        for tecla, funcion in atajos:
            sc = QShortcut(QKeySequence(tecla), self)
            sc.setContext(Qt.WindowShortcut)
            sc.activated.connect(funcion)

    def _mover_seleccion_carrito(self, delta: int) -> bool:
        total_filas = self.tabla.rowCount()
        if total_filas <= 0:
            return False
        actual = self.tabla.currentRow()
        if actual < 0:
            nueva = total_filas - 1 if delta < 0 else 0
        else:
            nueva = max(0, min(total_filas - 1, actual + delta))
        self.tabla.setCurrentCell(nueva, 0)
        self.tabla.selectRow(nueva)
        self._actualizar_estado_botones()
        return True

    def eventFilter(self, obj, event) -> bool:
        """
        Navegación fluida con teclado:
          - Flechas ↑/↓ mueven la lista desplegable si está visible; si no, mueven la selección del carrito.
          - Barra espaciadora concluye la venta (excepto cuando se está escribiendo texto en el buscador).
        """
        if event.type() == QEvent.KeyPress:
            tecla = event.key()

            if obj is self.txt_lector:
                if tecla == Qt.Key_Space and not self.txt_lector.text().strip():
                    if not self.carrito.esta_vacio():
                        self._cobrar()
                    return True
                if tecla == Qt.Key_Delete and not self.txt_lector.text():
                    if self.tabla.currentRow() >= 0:
                        self._quitar_actual()
                    return True
                if tecla in (Qt.Key_Down, Qt.Key_Up):
                    delta = 1 if tecla == Qt.Key_Down else -1
                    if self.lista_sugerencias.isVisible() and self.lista_sugerencias.count() > 0:
                        actual = max(0, self.lista_sugerencias.currentRow())
                        nueva = max(0, min(self.lista_sugerencias.count() - 1, actual + delta))
                        self.lista_sugerencias.setCurrentRow(nueva)
                        return True
                    if self._mover_seleccion_carrito(delta):
                        return True

            elif obj is self.tabla:
                if tecla == Qt.Key_Space and not self.carrito.esta_vacio():
                    self._cobrar()
                    return True
                if tecla == Qt.Key_Delete and self.tabla.currentRow() >= 0:
                    self._quitar_actual()
                    return True

            elif obj is self.txt_recibido:
                if tecla == Qt.Key_Space and not self.carrito.esta_vacio():
                    self._cobrar()
                    return True

            elif isinstance(obj, _CampoCantidadCarrito):
                if tecla == Qt.Key_Space and not self.carrito.esta_vacio():
                    self._cobrar()
                    return True
                if tecla in (Qt.Key_Down, Qt.Key_Up) and self._fila_pendiente_de_gramos() < 0:
                    delta = 1 if tecla == Qt.Key_Down else -1
                    if self._mover_seleccion_carrito(delta):
                        self.enfocar_lector()
                        return True

        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Delete and self.tabla.currentRow() >= 0:
            self._quitar_actual()
            return
        if event.key() == Qt.Key_Space and not self.carrito.esta_vacio():
            self._cobrar()
            return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.enfocar_lector()

    def _fila_pendiente_de_gramos(self) -> int:
        """Si hay un producto en el carrito con cantidad <= 0 (pendiente de escribir gramos), devuelve su fila."""
        for idx, it in enumerate(self.carrito.items):
            if it.cantidad <= 0:
                return idx
        return -1

    def enfocar_lector(self) -> None:
        """
        Si algún producto por peso está pendiente de que le escriban los gramos,
        enfoca su campo Cantidad; si no, devuelve el foco al lector de códigos.
        """
        fila_pend = self._fila_pendiente_de_gramos()
        if fila_pend >= 0:
            self.enfocar_cantidad_fila(fila_pend)
        else:
            QTimer.singleShot(0, self.txt_lector.setFocus)

    def enfocar_cantidad_fila(self, fila: int) -> None:
        if 0 <= fila < len(self.campos_cantidad):
            self.tabla.selectRow(fila)
            campo = self.campos_cantidad[fila]
            QTimer.singleShot(0, lambda c=campo: (c.setFocus(), c.selectAll()))

    def _escape_al_lector(self) -> None:
        self.lista_sugerencias.setVisible(False)
        if self.txt_lector.text():
            self.txt_lector.clear()
        self.enfocar_lector()

    def _abrir_cajon_manual(self) -> None:
        ok, msg = abrir_cajon(forzar=True)
        if not ok:
            QMessageBox.warning(self, "Cajón monedero", msg)
        self.enfocar_lector()

    # =====================================================================
    # Desplegable en vivo a medida que se escribe + Lectura de código
    # =====================================================================
    def _al_escribir_en_lector(self, texto: str) -> None:
        limpio = (texto or "").strip()
        if not limpio:
            self.sugerencias_actuales = []
            self.lista_sugerencias.clear()
            self.lista_sugerencias.setVisible(False)
            return

        resultados = inventario.buscar(texto=limpio, incluir_inactivos=False)[:25]
        self.sugerencias_actuales = resultados
        self.lista_sugerencias.clear()

        if not resultados:
            self.lista_sugerencias.setVisible(False)
            return

        for p in resultados:
            es_peso = p["tipo_venta"] == "peso"
            suf = " / lb" if es_peso else ""
            cod = f"  [{p['codigo_barras']}]" if p["codigo_barras"] else ""
            stock_txt = inventario.formatear_stock(p["tipo_venta"], p["stock"])
            etiqueta = (
                f"{p['nombre']}{cod}   —   {formatear_pesos(p['precio_final'])}{suf}   "
                f"(Stock: {stock_txt})"
            )
            item = QListWidgetItem(etiqueta)
            self.lista_sugerencias.addItem(item)

        self.lista_sugerencias.setCurrentRow(0)
        filas_visibles = min(len(resultados), 6)
        alto_fila = self.lista_sugerencias.sizeHintForRow(0)
        if alto_fila <= 0:
            alto_fila = 34
        alto_total = filas_visibles * alto_fila + self.lista_sugerencias.frameWidth() * 2 + 8
        self.lista_sugerencias.setFixedHeight(alto_total)
        self.lista_sugerencias.setVisible(True)

    def _al_clic_sugerencia(self, item: QListWidgetItem) -> None:
        fila = self.lista_sugerencias.row(item)
        if 0 <= fila < len(self.sugerencias_actuales):
            prod = self.sugerencias_actuales[fila]
            self.txt_lector.clear()
            self.lista_sugerencias.setVisible(False)
            self._agregar_producto_seleccionado(prod)

    def _procesar_entrada_lector(self) -> None:
        texto = self.txt_lector.text().strip()
        if not texto:
            self.enfocar_lector()
            return

        # 1. ¿Coincide exactamente con un código de barras?
        prod = inventario.obtener_por_codigo(texto)
        if prod is not None:
            self.txt_lector.clear()
            self.lista_sugerencias.setVisible(False)
            if not prod["activo"]:
                QMessageBox.warning(
                    self,
                    "Producto desactivado",
                    f"El producto '{prod['nombre']}' está desactivado en el inventario.",
                )
                self.enfocar_lector()
                return
            self._agregar_producto_seleccionado(prod)
            return

        # 2. Si la lista desplegable en vivo está visible y tiene un producto seleccionado, lo agregamos
        if self.lista_sugerencias.isVisible() and self.sugerencias_actuales:
            fila = max(0, self.lista_sugerencias.currentRow())
            if 0 <= fila < len(self.sugerencias_actuales):
                elegido = self.sugerencias_actuales[fila]
                self.txt_lector.clear()
                self.lista_sugerencias.setVisible(False)
                self._agregar_producto_seleccionado(elegido)
                return

        # 3. Si no hubo sugerencias en vivo, abrimos el buscador completo
        self._abrir_buscador(texto)

    def _abrir_buscador(self, texto_inicial: str = "") -> None:
        self.lista_sugerencias.setVisible(False)
        dlg = DialogoBuscarProducto(self, texto_inicial=texto_inicial)
        if dlg.exec() and dlg.producto_elegido:
            self.txt_lector.clear()
            self._agregar_producto_seleccionado(dlg.producto_elegido)
        else:
            self.enfocar_lector()

    def _agregar_producto_seleccionado(self, producto: dict) -> None:
        # Si ya había un producto por peso sin gramos escritos, obligamos primero a escribirlos
        fila_pend = self._fila_pendiente_de_gramos()
        if fila_pend >= 0 and self.carrito.items[fila_pend].producto_id != producto["id"]:
            QMessageBox.warning(
                self,
                "Falta cantidad en gramos",
                f"Escriba primero los gramos de '{self.carrito.items[fila_pend].nombre}' en la columna Cantidad.",
            )
            self.enfocar_cantidad_fila(fila_pend)
            return

        es_peso = producto["tipo_venta"] == "peso"
        if es_peso:
            # No se abre diálogo: se agrega con 0 g (o se mantiene la fila) y se obliga a escribir los gramos en Cantidad
            idx_existente = self.carrito.buscar_indice(producto["id"])
            if idx_existente >= 0:
                fila = idx_existente
            else:
                fila = self.carrito.agregar_producto(producto, 0)
            self._refrescar_vista(seleccionar_fila=fila)
            self.enfocar_cantidad_fila(fila)
            return

        cantidad = 1
        idx_existente = self.carrito.buscar_indice(producto["id"])
        acumulado = (self.carrito.items[idx_existente].cantidad if idx_existente >= 0 else 0) + cantidad
        if acumulado > producto["stock"]:
            politica = ajustes.obtener("politica_stock")
            disp_txt = inventario.formatear_stock(producto["tipo_venta"], producto["stock"])
            ped_txt = inventario.formatear_stock(producto["tipo_venta"], acumulado)
            if politica == "bloquear":
                QMessageBox.warning(
                    self,
                    "Stock insuficiente",
                    f"No hay suficiente stock de '{producto['nombre']}'.\n"
                    f"Disponible: {disp_txt}  |  Solicitado: {ped_txt}",
                )
                self.enfocar_lector()
                return

        fila = self.carrito.agregar_producto(producto, cantidad)
        self._refrescar_vista(seleccionar_fila=fila)
        self.enfocar_lector()

    # =====================================================================
    # Edición directa de la columna Cantidad en la tabla
    # =====================================================================
    def _fila_actual(self) -> int:
        return self.tabla.currentRow()

    def _al_editar_cantidad_celda(self, fila: int, texto: str) -> None:
        if not (0 <= fila < len(self.carrito.items)):
            return
        limpio = (texto or "").replace(".", "").strip()
        nueva = int(limpio) if limpio.isdigit() else 0
        item = self.carrito.items[fila]
        if item.tipo_venta == "unidad" and nueva <= 0:
            item.cantidad = 0
            item.subtotal = 0
            item.iva_valor = 0
            item.costo_total = 0
        else:
            self.carrito.cambiar_cantidad(fila, nueva)

        # Actualizamos solo la celda de subtotal y los totales para no recrear el QLineEdit mientras escribe
        celda_sub = self.tabla.item(fila, 4)
        if celda_sub is not None:
            celda_sub.setText(formatear_pesos(item.subtotal))
        self._actualizar_totales_panel()

    def _al_confirmar_cantidad_celda(self, fila: int) -> None:
        if not (0 <= fila < len(self.carrito.items)):
            self.enfocar_lector()
            return
        item = self.carrito.items[fila]
        if item.cantidad <= 0:
            unidad_txt = "los gramos" if item.tipo_venta == "peso" else "la cantidad"
            QMessageBox.warning(
                self,
                "Cantidad requerida",
                f"Escriba {unidad_txt} de '{item.nombre}' (mayor que 0).",
            )
            self.enfocar_cantidad_fila(fila)
            return
        self.enfocar_lector()

    def _sumar_a_linea(self, delta: int) -> None:
        fila = self._fila_actual()
        if not (0 <= fila < len(self.carrito.items)):
            self.enfocar_lector()
            return
        item = self.carrito.items[fila]
        paso = 100 * delta if item.tipo_venta == "peso" else delta
        nueva = item.cantidad + paso
        if nueva <= 0:
            self._quitar_actual()
            return
        self.carrito.cambiar_cantidad(fila, nueva)
        self._refrescar_vista(seleccionar_fila=fila)
        self.enfocar_lector()

    def _cambiar_cantidad_actual(self) -> None:
        """Enfoca directamente la celda de Cantidad de la fila seleccionada."""
        fila = self._fila_actual()
        if 0 <= fila < len(self.carrito.items):
            self.enfocar_cantidad_fila(fila)
        else:
            self.enfocar_lector()

    def _quitar_actual(self) -> None:
        fila = self._fila_actual()
        if 0 <= fila < len(self.carrito.items):
            self.carrito.quitar_item(fila)
            self._refrescar_vista(seleccionar_fila=min(fila, len(self.carrito.items) - 1))
        self.enfocar_lector()

    def _cancelar_venta(self) -> None:
        if self.carrito.esta_vacio():
            self.enfocar_lector()
            return
        if QMessageBox.question(
            self,
            "Cancelar venta",
            "¿Vaciar todos los productos del carrito actual?",
        ) == QMessageBox.Yes:
            self.carrito.limpiar()
            self.txt_recibido.clear()
            self._refrescar_vista()
        self.enfocar_lector()

    # =====================================================================
    # Ventas en espera (F4 / F5)
    # =====================================================================
    def _poner_en_espera(self) -> None:
        if self.carrito.esta_vacio():
            QMessageBox.information(self, "Venta en espera", "El carrito está vacío.")
            self.enfocar_lector()
            return
        fila_pend = self._fila_pendiente_de_gramos()
        if fila_pend >= 0:
            QMessageBox.warning(
                self,
                "Falta cantidad",
                f"Escriba primero los gramos de '{self.carrito.items[fila_pend].nombre}'.",
            )
            self.enfocar_cantidad_fila(fila_pend)
            return
        nota, ok = QInputDialog.getText(
            self,
            "Poner venta en espera (F4)",
            "Nota opcional (ej. nombre del cliente):",
        )
        if not ok:
            self.enfocar_lector()
            return
        self.espera.poner_en_espera(self.carrito, nota)
        self.carrito.limpiar()
        self.txt_recibido.clear()
        self._refrescar_vista()
        self.enfocar_lector()

    def _recuperar_en_espera(self) -> None:
        if self.espera.cantidad() == 0:
            QMessageBox.information(self, "Ventas en espera", "No hay ventas en espera.")
            self.enfocar_lector()
            return
        dlg = DialogoVentasEspera(self, self.espera)
        if dlg.exec() and dlg.venta_recuperada:
            if not self.carrito.esta_vacio():
                self.espera.poner_en_espera(self.carrito, "PAUSADA AUTOMÁTICAMENTE")
            self.carrito = dlg.venta_recuperada.carrito
        self._refrescar_vista()
        self.enfocar_lector()

    # =====================================================================
    # Medio de pago, billetes rápidos y cálculo de cambio
    # =====================================================================
    def _cambiar_medio_pago(self, codigo: str) -> None:
        self.medio_pago = codigo
        if codigo in self.botones_medio:
            self.botones_medio[codigo].setChecked(True)
        es_efectivo = codigo == "efectivo"
        self.txt_recibido.setEnabled(es_efectivo)
        self.marco_billetes.setEnabled(es_efectivo)
        if not es_efectivo:
            self.txt_recibido.clear()
        self._recalcular_cambio_en_vivo()
        self.enfocar_lector()

    def _usar_billete_rapido(self, valor: int) -> None:
        total = self.carrito.total()
        if valor == 0:
            self.txt_recibido.setText(formatear_pesos(total).replace("$ ", ""))
        else:
            self.txt_recibido.setText(formatear_pesos(valor).replace("$ ", ""))
        self.enfocar_lector()

    def _leer_monto_recibido(self) -> int | None:
        total = self.carrito.total()
        if self.medio_pago != "efectivo":
            return total
        texto = self.txt_recibido.text().strip()
        if not texto:
            return total
        return parsear_pesos(texto)

    def _recalcular_cambio_en_vivo(self) -> None:
        total = self.carrito.total()
        if total == 0 or self.medio_pago != "efectivo":
            self.lbl_titulo_cambio.setText("CAMBIO A ENTREGAR:")
            self.lbl_cambio_vivo.setText("$ 0")
            self.lbl_cambio_vivo.setStyleSheet(
                "color: #047857; font-size: 18pt; font-weight: 800; border: none;"
            )
            return

        texto = self.txt_recibido.text().strip()
        if not texto:
            self.lbl_titulo_cambio.setText("CAMBIO (exacto):")
            self.lbl_cambio_vivo.setText("$ 0")
            self.lbl_cambio_vivo.setStyleSheet(
                "color: #047857; font-size: 18pt; font-weight: 800; border: none;"
            )
            return

        try:
            recibido = parsear_pesos(texto)
        except ValueError:
            self.lbl_titulo_cambio.setText("MONTO NO VÁLIDO:")
            self.lbl_cambio_vivo.setText("—")
            self.lbl_cambio_vivo.setStyleSheet(
                "color: #dc2626; font-size: 18pt; font-weight: 800; border: none;"
            )
            return

        diferencia = recibido - total
        if diferencia < 0:
            self.lbl_titulo_cambio.setText("FALTA POR RECIBIR:")
            self.lbl_cambio_vivo.setText(formatear_pesos(abs(diferencia)))
            self.lbl_cambio_vivo.setStyleSheet(
                "color: #dc2626; font-size: 18pt; font-weight: 800; border: none;"
            )
        else:
            self.lbl_titulo_cambio.setText("CAMBIO A ENTREGAR:")
            self.lbl_cambio_vivo.setText(formatear_pesos(diferencia))
            self.lbl_cambio_vivo.setStyleSheet(
                "color: #047857; font-size: 18pt; font-weight: 800; border: none;"
            )

    # =====================================================================
    # Cobro de la venta (F12)
    # =====================================================================
    def _cobrar(self) -> None:
        if self.carrito.esta_vacio():
            self.enfocar_lector()
            return

        # Verificar que todos los productos por peso tengan sus gramos escritos
        fila_pend = self._fila_pendiente_de_gramos()
        if fila_pend >= 0:
            it_pend = self.carrito.items[fila_pend]
            QMessageBox.warning(
                self,
                "Falta cantidad en gramos",
                f"Escriba la cantidad en gramos para '{it_pend.nombre}' en la columna Cantidad.",
            )
            self.enfocar_cantidad_fila(fila_pend)
            return

        if not caja.hay_turno_abierto():
            dlg_turno = DialogoAbrirTurno(
                self,
                mensaje_extra="Para cobrar una venta primero debe abrir el turno de caja:",
            )
            if not dlg_turno.exec():
                self.enfocar_lector()
                return

        try:
            recibido = self._leer_monto_recibido()
        except ValueError:
            QMessageBox.warning(
                self,
                "Monto recibido",
                "Escriba un monto recibido válido en pesos sin decimales (ej. 50.000).",
            )
            self.txt_recibido.setFocus()
            return

        if self.medio_pago == "efectivo" and recibido < self.carrito.total():
            QMessageBox.warning(
                self,
                "Monto insuficiente",
                f"El monto recibido ({formatear_pesos(recibido)}) es menor que el total "
                f"a cobrar ({formatear_pesos(self.carrito.total())}).",
            )
            self.txt_recibido.setFocus()
            return

        faltantes = ventas.verificar_stock_carrito(self.carrito)
        if faltantes:
            politica = ajustes.obtener("politica_stock")
            lineas = [
                f"• {f['nombre']}: pide {inventario.formatear_stock(f['tipo_venta'], f['pedido'])}, "
                f"disponible {inventario.formatear_stock(f['tipo_venta'], f['disponible'])}"
                for f in faltantes
            ]
            detalle = "\n".join(lineas)
            if politica == "bloquear":
                QMessageBox.warning(
                    self,
                    "Stock insuficiente",
                    f"No se puede completar la venta por falta de stock:\n\n{detalle}",
                )
                self.enfocar_lector()
                return
            resp = QMessageBox.question(
                self,
                "Aviso de stock insuficiente",
                f"Los siguientes productos no tienen stock suficiente:\n\n{detalle}\n\n"
                "¿Desea completar la venta de todas formas? (el stock quedará negativo)",
            )
            if resp != QMessageBox.Yes:
                self.enfocar_lector()
                return

        try:
            resultado = ventas.registrar_venta(
                self.carrito,
                medio_pago=self.medio_pago,
                monto_recibido=recibido,
                permitir_sin_stock=True,
            )
        except ventas.ErrorVenta as e:
            QMessageBox.warning(self, "No se pudo cobrar", str(e))
            self.enfocar_lector()
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "Error al guardar la venta",
                f"Ocurrió un error y la venta NO se guardó:\n\n{e}",
            )
            self.enfocar_lector()
            return

        self.carrito.limpiar()
        self.txt_recibido.clear()
        self.lista_sugerencias.setVisible(False)
        self._cambiar_medio_pago("efectivo")
        self._refrescar_vista()
        self.venta_registrada.emit()
        self.enfocar_lector()

    # =====================================================================
    # Refresco de tabla y totales
    # =====================================================================
    def _refrescar_vista(self, seleccionar_fila: int | None = None) -> None:
        items = self.carrito.items
        self.campos_cantidad.clear()
        self.etiquetas_unidad.clear()
        self.cajas_cantidad.clear()
        self.tabla.setRowCount(0)
        self.tabla.setRowCount(len(items))

        tam_pt = ajustes.obtener_entero("tamano_texto_listas")
        altura_fila = max(42, int(tam_pt * 2.9) + 8)
        alto_caja = max(30, int(tam_pt * 2.1) + 4)
        ancho_unid = max(58, int(tam_pt * 4.2))
        ancho_caja = max(175, int(tam_pt * 12.2))
        ancho_col = ancho_caja + 28

        self.tabla.verticalHeader().setMinimumSectionSize(altura_fila)
        self.tabla.verticalHeader().setDefaultSectionSize(altura_fila)
        self.tabla.setColumnWidth(2, ancho_col)

        for i, it in enumerate(items):
            self.tabla.setRowHeight(i, altura_fila)
            es_peso = it.tipo_venta == "peso"
            sufijo = " / lb" if es_peso else ""

            c_cod = QTableWidgetItem(it.codigo_barras or "—")
            c_nom = QTableWidgetItem(it.nombre)
            c_pre = QTableWidgetItem(formatear_pesos(it.precio_unitario) + sufijo)
            c_pre.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            c_sub = QTableWidgetItem(formatear_pesos(it.subtotal))
            c_sub.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            self.tabla.setItem(i, 0, c_cod)
            self.tabla.setItem(i, 1, c_nom)
            self.tabla.setItem(i, 3, c_pre)
            self.tabla.setItem(i, 4, c_sub)

            # Columna 2: Caja integrada [ número | UND/G ] con texto blanco cuando la fila está seleccionada
            contenedor = QWidget()
            contenedor.setStyleSheet("background: transparent;")
            lay_ext = QHBoxLayout(contenedor)
            lay_ext.setContentsMargins(6, 2, 6, 2)
            lay_ext.setAlignment(Qt.AlignCenter)

            caja_blanca = QFrame()
            caja_blanca.setObjectName("caja_cantidad_carrito")
            caja_blanca.setFixedSize(ancho_caja, alto_caja)
            lay_int = QHBoxLayout(caja_blanca)
            lay_int.setContentsMargins(1, 1, 1, 1)
            lay_int.setSpacing(0)

            txt_cant = _CampoCantidadCarrito()
            txt_cant.installEventFilter(self)
            activar_formato_miles(txt_cant)
            if it.cantidad > 0:
                txt_cant.setText(f"{it.cantidad:,}".replace(",", "."))
            else:
                txt_cant.setText("")
            txt_cant.setPlaceholderText("GRAMOS" if es_peso else "CANT.")
            txt_cant.textChanged.connect(lambda t, fila=i: self._al_editar_cantidad_celda(fila, t))
            txt_cant.returnPressed.connect(lambda fila=i: self._al_confirmar_cantidad_celda(fila))

            lbl_unid = QLabel("G" if es_peso else "UND")
            lbl_unid.setObjectName("unidad_cantidad_carrito")
            lbl_unid.setFixedWidth(ancho_unid)
            lbl_unid.setAlignment(Qt.AlignCenter)

            lay_int.addWidget(txt_cant, stretch=1)
            lay_int.addWidget(lbl_unid)
            lay_ext.addWidget(caja_blanca)
            self.tabla.setCellWidget(i, 2, contenedor)
            self.campos_cantidad.append(txt_cant)
            self.etiquetas_unidad.append(lbl_unid)
            self.cajas_cantidad.append(caja_blanca)

        if seleccionar_fila is not None and 0 <= seleccionar_fila < len(items):
            self.tabla.setCurrentCell(seleccionar_fila, 0)
            self.tabla.selectRow(seleccionar_fila)
        elif items:
            self.tabla.setCurrentCell(len(items) - 1, 0)
            self.tabla.selectRow(len(items) - 1)

        self._actualizar_totales_panel()

    def _actualizar_totales_panel(self) -> None:
        items = self.carrito.items
        total = self.carrito.total()
        self.lbl_total_grande.setText(formatear_pesos(total))
        self.lbl_resumen_items.setText(
            f"{len(items)} línea(s) en el carrito · IVA incluido: {formatear_pesos(self.carrito.total_iva())}"
        )
        self.btn_ver_espera.setText(f"En espera: {self.espera.cantidad()} (F5)")
        self._recalcular_cambio_en_vivo()
        self._actualizar_estado_botones()

    def _actualizar_estado_botones(self) -> None:
        hay_items = not self.carrito.esta_vacio()
        fila_sel = self._fila_actual()
        self.btn_cancelar.setEnabled(hay_items)
        self.btn_poner_espera.setEnabled(hay_items)
        self.btn_cobrar.setEnabled(hay_items)

        # Texto de cantidad y unidad en BLANCO cuando la fila está seleccionada, y negro cuando no
        for idx in range(len(self.campos_cantidad)):
            seleccionada = idx == fila_sel
            txt = self.campos_cantidad[idx]
            lbl = self.etiquetas_unidad[idx]
            caja_f = self.cajas_cantidad[idx]
            if seleccionada:
                caja_f.setStyleSheet(
                    "QFrame#caja_cantidad_carrito { background-color: #1d4ed8; "
                    "border: 1px solid #93c5fd; border-radius: 5px; }"
                )
                txt.setStyleSheet(
                    "QLineEdit#campo_cantidad_carrito { color: #ffffff; background-color: transparent; "
                    "font-weight: bold; border: none; padding: 0px 8px; }"
                )
                lbl.setStyleSheet(
                    "QLabel#unidad_cantidad_carrito { color: #ffffff; background-color: #1e3a8a; "
                    "font-weight: bold; border-left: 1px solid #93c5fd; "
                    "border-top-right-radius: 4px; border-bottom-right-radius: 4px; }"
                )
            else:
                caja_f.setStyleSheet("")
                txt.setStyleSheet("")
                lbl.setStyleSheet("")
