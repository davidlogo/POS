"""
Pantalla de Ajustes (organizada según indicaciones del usuario).

Estructura ordenada:
  - Columna izquierda:
      1. General y Ventas (nombre de la tienda, política de stock insuficiente).
      2. Cambiar contraseña.
      3. Cajón monedero (RJ11 a convertidor USB) -> como último grupo de ajustes.
  - Columna derecha:
      * Respaldos de la base de datos (organizado en dos secciones claras:
        Parámetros de respaldo automático arriba y Lista + barra uniforme de
        acciones manuales/restauración abajo).
"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from hardware import cajon
from modules import ajustes, auth, respaldos
from ui.comun import FlowLayout
from ui.estilos import aplicar_tamano_texto_listas

_ENC_RESPALDOS = ["Sel.", "Fecha y hora", "Archivo", "Tamaño"]


def _formatear_tamano(tam_bytes: int) -> str:
    if tam_bytes < 1024:
        return f"{tam_bytes} B"
    kb = tam_bytes / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    return f"{kb / 1024:.2f} MB"


class PantallaAjustes(QWidget):
    nombre_tienda_cambiado = Signal(str)
    base_datos_restaurada = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lista_archivos_respaldo: list[dict] = []
        self.casillas_respaldo: list[QCheckBox] = []

        layout_raiz = QVBoxLayout(self)
        layout_raiz.setContentsMargins(8, 8, 8, 8)

        self.sub_pestanas = QTabWidget()
        layout_raiz.addWidget(self.sub_pestanas)

        # =====================================================================
        # SUB-PESTAÑA 1: General, Contraseña y Cajón monedero (2 columnas responsivas)
        # =====================================================================
        pag_config = QWidget()
        lay_cfg = QHBoxLayout(pag_config)
        div_cfg = QSplitter(Qt.Horizontal)
        lay_cfg.addWidget(div_cfg)

        panel_izq = QWidget()
        col_izq = QVBoxLayout(panel_izq)
        col_izq.setContentsMargins(0, 0, 6, 0)
        col_izq.setSpacing(10)

        # ---------------- 1. General y Ventas ----------------
        grupo_general = QGroupBox("1. General y Ventas")
        form_general = QFormLayout(grupo_general)
        form_general.setVerticalSpacing(6)

        self.txt_nombre_tienda = QLineEdit()
        self.txt_nombre_tienda.setMaxLength(60)
        form_general.addRow("Nombre de la tienda:", self.txt_nombre_tienda)

        self.cmb_politica_stock = QComboBox()
        self.cmb_politica_stock.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_politica_stock.setMinimumContentsLength(18)
        self.cmb_politica_stock.addItem(
            "Avisar pero permitir vender (el stock puede quedar negativo)", "avisar"
        )
        self.cmb_politica_stock.addItem(
            "Bloquear la venta cuando no alcance el stock", "bloquear"
        )
        form_general.addRow("Si el stock no alcanza:", self.cmb_politica_stock)

        fila_tam = QHBoxLayout()
        self.spin_tamano_listas = QSpinBox()
        self.spin_tamano_listas.setMinimum(10)
        self.spin_tamano_listas.setMaximum(20)
        self.spin_tamano_listas.setSuffix(" pt")
        self.spin_tamano_listas.valueChanged.connect(aplicar_tamano_texto_listas)
        fila_tam.addWidget(self.spin_tamano_listas)
        lbl_ayuda_tam = QLabel("(en tablas y listas)")
        lbl_ayuda_tam.setStyleSheet("color: #64748b;")
        fila_tam.addWidget(lbl_ayuda_tam)
        fila_tam.addStretch()
        form_general.addRow("Tamaño de texto:", fila_tam)

        self.chk_proteger_precios = QCheckBox("Proteger la sección Precios con contraseña")
        form_general.addRow("Seguridad:", self.chk_proteger_precios)

        btn_guardar_general = QPushButton("Guardar ajustes generales")
        btn_guardar_general.setMinimumHeight(34)
        btn_guardar_general.setStyleSheet(
            "QPushButton { background-color: #1e40af; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        btn_guardar_general.clicked.connect(self._guardar_general)
        fila_g = QHBoxLayout()
        fila_g.addStretch()
        fila_g.addWidget(btn_guardar_general)
        form_general.addRow(fila_g)
        col_izq.addWidget(grupo_general)

        # ---------------- 2. Cambiar contraseña ----------------
        grupo_clave = QGroupBox("2. Cambiar contraseña")
        form_clave = QFormLayout(grupo_clave)
        form_clave.setVerticalSpacing(6)

        self.txt_clave_actual = QLineEdit()
        self.txt_clave_actual.setEchoMode(QLineEdit.Password)
        self.txt_clave_nueva = QLineEdit()
        self.txt_clave_nueva.setEchoMode(QLineEdit.Password)
        self.txt_clave_confirmar = QLineEdit()
        self.txt_clave_confirmar.setEchoMode(QLineEdit.Password)

        form_clave.addRow("Contraseña actual:", self.txt_clave_actual)
        form_clave.addRow("Nueva contraseña:", self.txt_clave_nueva)
        form_clave.addRow("Confirmar nueva:", self.txt_clave_confirmar)

        ayuda = QLabel(f"Mínimo {auth.LONGITUD_MINIMA} caracteres.")
        ayuda.setStyleSheet("color: gray;")
        form_clave.addRow("", ayuda)

        btn_cambiar = QPushButton("Actualizar contraseña")
        btn_cambiar.setMinimumHeight(34)
        btn_cambiar.clicked.connect(self._cambiar_clave)
        self.txt_clave_confirmar.returnPressed.connect(self._cambiar_clave)
        fila_c = QHBoxLayout()
        fila_c.addStretch()
        fila_c.addWidget(btn_cambiar)
        form_clave.addRow(fila_c)
        col_izq.addWidget(grupo_clave)
        col_izq.addStretch()
        div_cfg.addWidget(panel_izq)

        # ---------------- 3. Cajón monedero ----------------
        panel_der = QWidget()
        col_der = QVBoxLayout(panel_der)
        col_der.setContentsMargins(6, 0, 0, 0)
        grupo_cajon = QGroupBox("3. Cajón monedero (RJ11 a convertidor USB)")
        form_cajon = QFormLayout(grupo_cajon)
        form_cajon.setVerticalSpacing(6)

        self.chk_cajon_activo = QCheckBox("Activar apertura automática al cobrar")
        form_cajon.addRow("", self.chk_cajon_activo)

        self.chk_cajon_otros_medios = QCheckBox("Abrir también en Transferencia")
        self.chk_cajon_otros_medios.setToolTip("Si no se marca, abre solo en Efectivo")
        form_cajon.addRow("", self.chk_cajon_otros_medios)

        self.cmb_cajon_modo = QComboBox()
        self.cmb_cajon_modo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_cajon_modo.setMinimumContentsLength(18)
        for codigo, texto in cajon.MODOS_CONEXION:
            self.cmb_cajon_modo.addItem(texto, codigo)
        self.cmb_cajon_modo.currentIndexChanged.connect(self._actualizar_campos_cajon)
        form_cajon.addRow("Tipo de conexión:", self.cmb_cajon_modo)

        fila_puerto = QHBoxLayout()
        self.cmb_cajon_puerto = QComboBox()
        self.cmb_cajon_puerto.setEditable(True)
        self.cmb_cajon_puerto.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_cajon_puerto.setMinimumContentsLength(12)
        btn_detectar = QPushButton("Detectar")
        btn_detectar.clicked.connect(self._detectar_puertos_cajon)
        fila_puerto.addWidget(self.cmb_cajon_puerto, stretch=1)
        fila_puerto.addWidget(btn_detectar)
        form_cajon.addRow("Puerto USB / COM:", fila_puerto)

        self.cmb_cajon_baudios = QComboBox()
        for b in cajon.VELOCIDADES_BAUDIOS:
            self.cmb_cajon_baudios.addItem(f"{b} baudios", str(b))
        form_cajon.addRow("Velocidad (serial):", self.cmb_cajon_baudios)

        self.cmb_cajon_comando = QComboBox()
        self.cmb_cajon_comando.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_cajon_comando.setMinimumContentsLength(18)
        for codigo, texto in cajon.COMANDOS_CAJON:
            self.cmb_cajon_comando.addItem(texto, codigo)
        self.cmb_cajon_comando.currentIndexChanged.connect(self._actualizar_campos_cajon)
        form_cajon.addRow("Pulso / Comando:", self.cmb_cajon_comando)

        self.txt_cajon_hex = QLineEdit()
        self.txt_cajon_hex.setPlaceholderText("Ej: 1B 70 00 19 FA")
        form_cajon.addRow("Bytes HEX:", self.txt_cajon_hex)

        fila_btn_cajon = FlowLayout(margin=0, h_spacing=8, v_spacing=6)
        self.btn_probar_cajon = QPushButton("Probar cajón")
        self.btn_probar_cajon.setMinimumHeight(34)
        self.btn_probar_cajon.setStyleSheet(
            "QPushButton { background-color: #0891b2; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #0e7490; }"
        )
        self.btn_probar_cajon.clicked.connect(self._probar_cajon)

        btn_guardar_cajon = QPushButton("Guardar configuración del cajón")
        btn_guardar_cajon.setMinimumHeight(34)
        btn_guardar_cajon.setStyleSheet(
            "QPushButton { background-color: #1e40af; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        btn_guardar_cajon.clicked.connect(self._guardar_cajon)

        fila_btn_cajon.addWidget(self.btn_probar_cajon)
        fila_btn_cajon.addWidget(btn_guardar_cajon)
        form_cajon.addRow(fila_btn_cajon)

        col_der.addWidget(grupo_cajon)
        col_der.addStretch()
        div_cfg.addWidget(panel_der)
        div_cfg.setStretchFactor(0, 1)
        div_cfg.setStretchFactor(1, 1)

        self.sub_pestanas.addTab(pag_config, "General, contraseña y cajón")

        # =====================================================================
        # SUB-PESTAÑA 2: Respaldos de la base de datos (ancho completo)
        # =====================================================================
        pag_resp = QWidget()
        vbox_resp = QVBoxLayout(pag_resp)
        vbox_resp.setSpacing(8)

        # --- Sub-bloque A: Configuración automática ---
        marco_cfg_resp = QFrame()
        marco_cfg_resp.setStyleSheet(
            "QFrame { background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 6px; }"
            "QLabel { border: none; }"
        )
        form_resp = QFormLayout(marco_cfg_resp)
        form_resp.setVerticalSpacing(5)

        fila_carpeta = QHBoxLayout()
        self.txt_carpeta_respaldo = QLineEdit()
        self.txt_carpeta_respaldo.setReadOnly(True)
        btn_elegir_carpeta = QPushButton("Cambiar carpeta / USB...")
        btn_elegir_carpeta.setMinimumHeight(30)
        btn_elegir_carpeta.clicked.connect(self._elegir_carpeta_respaldo)
        btn_carpeta_defecto = QPushButton("Por defecto")
        btn_carpeta_defecto.setMinimumHeight(30)
        btn_carpeta_defecto.setToolTip("Usar la carpeta pos/datos/respaldos")
        btn_carpeta_defecto.clicked.connect(self._usar_carpeta_por_defecto)
        fila_carpeta.addWidget(self.txt_carpeta_respaldo, stretch=1)
        fila_carpeta.addWidget(btn_elegir_carpeta)
        fila_carpeta.addWidget(btn_carpeta_defecto)
        form_resp.addRow("Carpeta destino:", fila_carpeta)

        fila_chks_resp = FlowLayout(margin=0, h_spacing=16, v_spacing=4)
        self.chk_resp_cerrar = QCheckBox("Respaldo automático al cerrar el programa")
        self.chk_resp_abrir = QCheckBox("Respaldo automático al abrir el programa")
        fila_chks_resp.addWidget(self.chk_resp_cerrar)
        fila_chks_resp.addWidget(self.chk_resp_abrir)
        form_resp.addRow("Automáticos:", fila_chks_resp)

        fila_max = FlowLayout(margin=0, h_spacing=8, v_spacing=4)
        self.spin_max_respaldos = QSpinBox()
        self.spin_max_respaldos.setMinimum(3)
        self.spin_max_respaldos.setMaximum(500)
        self.spin_max_respaldos.setSuffix(" respaldos")
        fila_max.addWidget(self.spin_max_respaldos)
        lbl_nota_rot = QLabel("(los más antiguos se eliminan solos)")
        lbl_nota_rot.setStyleSheet("color: #64748b;")
        fila_max.addWidget(lbl_nota_rot)

        btn_guardar_cfg_resp = QPushButton("Guardar configuración de respaldos")
        btn_guardar_cfg_resp.setMinimumHeight(32)
        btn_guardar_cfg_resp.setStyleSheet(
            "QPushButton { background-color: #1e40af; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        btn_guardar_cfg_resp.clicked.connect(self._guardar_config_respaldos)
        fila_max.addWidget(btn_guardar_cfg_resp)
        form_resp.addRow("Conservar últimos:", fila_max)

        vbox_resp.addWidget(marco_cfg_resp)

        # --- Sub-bloque B: Tabla de respaldos con casillas y barra responsiva de acciones ---
        fila_tit_lista = QHBoxLayout()
        lbl_lista = QLabel("Copias de seguridad disponibles:")
        lbl_lista.setStyleSheet("font-weight: bold; color: #1e3a8a;")
        fila_tit_lista.addWidget(lbl_lista)
        fila_tit_lista.addStretch()

        self.btn_marcar_todos_resp = QPushButton("Marcar / Desmarcar todos")
        self.btn_marcar_todos_resp.setMinimumHeight(28)
        self.btn_marcar_todos_resp.clicked.connect(self._alternar_marcar_todos_respaldos)
        fila_tit_lista.addWidget(self.btn_marcar_todos_resp)
        vbox_resp.addLayout(fila_tit_lista)

        self.tabla_respaldos = QTableWidget(0, len(_ENC_RESPALDOS))
        self.tabla_respaldos.setObjectName("tabla_respaldos_ajustes")
        self.tabla_respaldos.setHorizontalHeaderLabels(_ENC_RESPALDOS)
        self.tabla_respaldos.verticalHeader().setVisible(False)
        self.tabla_respaldos.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.tabla_respaldos.setAlternatingRowColors(True)
        self.tabla_respaldos.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_respaldos.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla_respaldos.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla_respaldos.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla_respaldos.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.tabla_respaldos.setColumnWidth(0, 72)
        self.tabla_respaldos.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        vbox_resp.addWidget(self.tabla_respaldos, stretch=1)

        fila_acc_resp = FlowLayout(margin=0, h_spacing=8, v_spacing=6)

        self.btn_respaldar_ahora = QPushButton("+ Crear respaldo manual")
        self.btn_respaldar_ahora.setMinimumHeight(34)
        self.btn_respaldar_ahora.setStyleSheet(
            "QPushButton { background-color: #15803d; color: white; font-weight: bold; padding: 5px 12px; }"
            "QPushButton:hover { background-color: #166534; }"
        )
        self.btn_respaldar_ahora.clicked.connect(self._crear_respaldo_manual)
        fila_acc_resp.addWidget(self.btn_respaldar_ahora)

        self.btn_restaurar_sel = QPushButton("Restaurar seleccionado")
        self.btn_restaurar_sel.setMinimumHeight(34)
        self.btn_restaurar_sel.setStyleSheet(
            "QPushButton { background-color: #d97706; color: white; font-weight: bold; padding: 5px 12px; }"
            "QPushButton:hover { background-color: #b45309; }"
        )
        self.btn_restaurar_sel.clicked.connect(self._restaurar_seleccionado)
        fila_acc_resp.addWidget(self.btn_restaurar_sel)

        btn_restaurar_archivo = QPushButton("Restaurar otro archivo...")
        btn_restaurar_archivo.setMinimumHeight(34)
        btn_restaurar_archivo.clicked.connect(self._restaurar_desde_archivo)
        fila_acc_resp.addWidget(btn_restaurar_archivo)

        self.btn_eliminar_resp = QPushButton("Eliminar marcados (0)")
        self.btn_eliminar_resp.setMinimumHeight(34)
        self.btn_eliminar_resp.setStyleSheet(
            "QPushButton { background-color: #dc2626; color: white; font-weight: bold; padding: 5px 12px; }"
            "QPushButton:hover { background-color: #b91c1c; }"
            "QPushButton:disabled { background-color: #cbd5e1; color: #64748b; }"
        )
        self.btn_eliminar_resp.clicked.connect(self._eliminar_respaldo_seleccionado)
        fila_acc_resp.addWidget(self.btn_eliminar_resp)

        vbox_resp.addLayout(fila_acc_resp)

        nota_resp = QLabel(
            "Seguridad al restaurar: antes de restaurar cualquier respaldo, el sistema guarda "
            "automáticamente una copia de seguridad de los datos actuales."
        )
        nota_resp.setStyleSheet("color: #64748b; font-size: 9pt;")
        nota_resp.setWordWrap(True)
        vbox_resp.addWidget(nota_resp)

        self.sub_pestanas.addTab(pag_resp, "Respaldos de la base de datos")

        self.cargar()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.cargar()

    def cargar(self) -> None:
        """Carga los valores guardados en los campos y refresca la tabla de respaldos."""
        self.txt_nombre_tienda.setText(ajustes.obtener("nombre_tienda"))
        pol = ajustes.obtener("politica_stock")
        idx = self.cmb_politica_stock.findData(pol)
        self.cmb_politica_stock.setCurrentIndex(idx if idx >= 0 else 0)
        self.spin_tamano_listas.blockSignals(True)
        self.spin_tamano_listas.setValue(max(10, min(20, ajustes.obtener_entero("tamano_texto_listas"))))
        self.spin_tamano_listas.blockSignals(False)
        self.chk_proteger_precios.setChecked(ajustes.obtener_booleano("proteger_precios"))

        # Cajón monedero
        self.chk_cajon_activo.setChecked(ajustes.obtener_booleano("cajon_activo"))
        self.chk_cajon_otros_medios.setChecked(ajustes.obtener_booleano("cajon_abrir_otros_medios"))
        idx_modo = self.cmb_cajon_modo.findData(ajustes.obtener("cajon_modo"))
        self.cmb_cajon_modo.setCurrentIndex(idx_modo if idx_modo >= 0 else 0)
        self._detectar_puertos_cajon(conservar_texto=ajustes.obtener("cajon_puerto"))
        idx_baud = self.cmb_cajon_baudios.findData(ajustes.obtener("cajon_baudios"))
        self.cmb_cajon_baudios.setCurrentIndex(idx_baud if idx_baud >= 0 else 0)
        idx_cmd = self.cmb_cajon_comando.findData(ajustes.obtener("cajon_comando"))
        self.cmb_cajon_comando.setCurrentIndex(idx_cmd if idx_cmd >= 0 else 0)
        self.txt_cajon_hex.setText(ajustes.obtener("cajon_hex_personalizado"))
        self._actualizar_campos_cajon()

        # Respaldos
        carpeta_cfg = str(respaldos.obtener_carpeta_configurada())
        self.txt_carpeta_respaldo.setText(carpeta_cfg)
        self.chk_resp_cerrar.setChecked(ajustes.obtener_booleano("respaldo_al_cerrar"))
        self.chk_resp_abrir.setChecked(ajustes.obtener_booleano("respaldo_al_abrir"))
        self.spin_max_respaldos.setValue(max(3, ajustes.obtener_entero("respaldo_max_archivos")))

        self.recargar_lista_respaldos()

    def recargar_lista_respaldos(self) -> None:
        self.lista_archivos_respaldo = respaldos.listar_respaldos()
        self.casillas_respaldo.clear()
        self.tabla_respaldos.setRowCount(0)
        self.tabla_respaldos.setRowCount(len(self.lista_archivos_respaldo))
        tam_pt = ajustes.obtener_entero("tamano_texto_listas")
        altura_fila = max(40, int(tam_pt * 2.8) + 8)
        self.tabla_respaldos.verticalHeader().setMinimumSectionSize(altura_fila)
        self.tabla_respaldos.verticalHeader().setDefaultSectionSize(altura_fila)
        self.tabla_respaldos.setColumnWidth(0, 72)
        for i, item in enumerate(self.lista_archivos_respaldo):
            self.tabla_respaldos.setRowHeight(i, altura_fila)
            # Columna 0: Casilla de selección con tamaño fijo amplio para que nunca se corte
            contenedor = QWidget()
            contenedor.setStyleSheet("background: transparent;")
            lay_chk = QHBoxLayout(contenedor)
            lay_chk.setContentsMargins(0, 0, 0, 0)
            lay_chk.setAlignment(Qt.AlignCenter)
            chk = QCheckBox()
            chk.setFixedSize(24, 24)
            chk.toggled.connect(self._actualizar_boton_eliminar_respaldos)
            lay_chk.addWidget(chk)
            self.tabla_respaldos.setCellWidget(i, 0, contenedor)
            self.casillas_respaldo.append(chk)

            valores = [
                item["fecha_modificacion"],
                item["nombre"],
                _formatear_tamano(item["tamano_bytes"]),
            ]
            for idx_val, texto in enumerate(valores, start=1):
                celda = QTableWidgetItem(texto)
                if idx_val == 3:
                    celda.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla_respaldos.setItem(i, idx_val, celda)

        if self.lista_archivos_respaldo:
            self.tabla_respaldos.setCurrentCell(0, 1)
            self.tabla_respaldos.selectRow(0)
        hay_resp = bool(self.lista_archivos_respaldo)
        self.btn_restaurar_sel.setEnabled(hay_resp)
        self.btn_marcar_todos_resp.setEnabled(hay_resp)
        self._actualizar_boton_eliminar_respaldos()

    def _indices_respaldos_marcados(self) -> list[int]:
        return [i for i, chk in enumerate(self.casillas_respaldo) if chk.isChecked()]

    def _alternar_marcar_todos_respaldos(self) -> None:
        if not self.casillas_respaldo:
            return
        marcar = not all(chk.isChecked() for chk in self.casillas_respaldo)
        for chk in self.casillas_respaldo:
            chk.blockSignals(True)
            chk.setChecked(marcar)
            chk.blockSignals(False)
        self._actualizar_boton_eliminar_respaldos()

    def _actualizar_boton_eliminar_respaldos(self) -> None:
        n = len(self._indices_respaldos_marcados())
        self.btn_eliminar_resp.setText(f"Eliminar marcados ({n})")
        self.btn_eliminar_resp.setEnabled(n > 0)

    # =====================================================================
    # Acciones Generales y Contraseña
    # =====================================================================
    def _guardar_general(self) -> None:
        nombre = self.txt_nombre_tienda.text().strip().upper()
        if not nombre:
            QMessageBox.warning(self, "Ajustes", "El nombre de la tienda no puede estar vacío.")
            return

        proteger_antes = ajustes.obtener_booleano("proteger_precios")
        proteger_ahora = self.chk_proteger_precios.isChecked()
        if proteger_antes and not proteger_ahora:
            clave, ok = QInputDialog.getText(
                self,
                "Autorizar cambio de seguridad",
                "Ingrese la contraseña del sistema para desactivar la protección de Precios:",
                QLineEdit.Password,
            )
            if not ok:
                self.chk_proteger_precios.setChecked(True)
                return
            if not auth.verificar_clave(clave):
                QMessageBox.warning(self, "Ajustes", "Contraseña incorrecta. No se desactivó la protección.")
                self.chk_proteger_precios.setChecked(True)
                return

        self.txt_nombre_tienda.setText(nombre)
        tam_listas = self.spin_tamano_listas.value()
        ajustes.guardar_varios({
            "nombre_tienda": nombre,
            "politica_stock": self.cmb_politica_stock.currentData(),
            "tamano_texto_listas": str(tam_listas),
            "proteger_precios": proteger_ahora,
        })
        aplicar_tamano_texto_listas(tam_listas)
        self.nombre_tienda_cambiado.emit(nombre)
        QMessageBox.information(self, "Ajustes", "Ajustes guardados.")

    def _cambiar_clave(self) -> None:
        error = auth.cambiar_clave(
            self.txt_clave_actual.text(),
            self.txt_clave_nueva.text(),
            self.txt_clave_confirmar.text(),
        )
        if error:
            QMessageBox.warning(self, "Cambiar contraseña", error)
            return
        for campo in (self.txt_clave_actual, self.txt_clave_nueva, self.txt_clave_confirmar):
            campo.clear()
        QMessageBox.information(self, "Cambiar contraseña", "Contraseña cambiada correctamente.")

    # =====================================================================
    # Acciones de Cajón Monedero
    # =====================================================================
    def _detectar_puertos_cajon(self, conservar_texto: str | None = None) -> None:
        actual = conservar_texto if isinstance(conservar_texto, str) else self._puerto_cajon_elegido()
        self.cmb_cajon_puerto.clear()
        puertos = cajon.listar_puertos_disponibles()
        for p in puertos:
            self.cmb_cajon_puerto.addItem(p["descripcion"], p["dispositivo"])
        if actual:
            idx = self.cmb_cajon_puerto.findData(actual)
            if idx >= 0:
                self.cmb_cajon_puerto.setCurrentIndex(idx)
            else:
                self.cmb_cajon_puerto.setCurrentText(actual)

    def _puerto_cajon_elegido(self) -> str:
        dato = self.cmb_cajon_puerto.currentData()
        texto = self.cmb_cajon_puerto.currentText().strip()
        if dato and texto.startswith(str(dato)):
            return str(dato)
        return texto.split("—")[0].strip()

    def _actualizar_campos_cajon(self) -> None:
        es_serial = self.cmb_cajon_modo.currentData() == "serial"
        self.cmb_cajon_baudios.setEnabled(es_serial)
        es_hex = self.cmb_cajon_comando.currentData() == "personalizado"
        self.txt_cajon_hex.setEnabled(es_hex)

    def _config_cajon_en_pantalla(self) -> dict:
        return {
            "activo": self.chk_cajon_activo.isChecked(),
            "modo": self.cmb_cajon_modo.currentData(),
            "puerto": self._puerto_cajon_elegido(),
            "baudios": int(self.cmb_cajon_baudios.currentData() or 9600),
            "comando": self.cmb_cajon_comando.currentData(),
            "hex_personalizado": self.txt_cajon_hex.text().strip(),
        }

    def _guardar_cajon(self) -> None:
        cfg = self._config_cajon_en_pantalla()
        if cfg["comando"] == "personalizado":
            try:
                cajon.parsear_hex(cfg["hex_personalizado"])
            except ValueError as e:
                QMessageBox.warning(self, "Cajón monedero", str(e))
                return

        ajustes.guardar_varios({
            "cajon_activo": cfg["activo"],
            "cajon_abrir_otros_medios": self.chk_cajon_otros_medios.isChecked(),
            "cajon_modo": cfg["modo"],
            "cajon_puerto": cfg["puerto"],
            "cajon_baudios": str(cfg["baudios"]),
            "cajon_comando": cfg["comando"],
            "cajon_hex_personalizado": cfg["hex_personalizado"] or "1B 70 00 19 FA",
        })
        QMessageBox.information(
            self, "Cajón monedero", "Configuración del cajón guardada correctamente."
        )

    def _probar_cajon(self) -> None:
        cfg = self._config_cajon_en_pantalla()
        ok, msg = cajon.abrir_cajon(config_override=cfg, forzar=True)
        if ok:
            QMessageBox.information(self, "Probar cajón", f"✓ {msg}")
        else:
            QMessageBox.warning(
                self,
                "Probar cajón",
                f"{msg}\n\n"
                "Sugerencia: cuando conecte el convertidor RJ11-USB, pulse "
                "«Detectar puertos» o ejecute scripts\\probar_cajon.py para diagnosticar.",
            )

    # =====================================================================
    # Acciones de Respaldos y Restauración
    # =====================================================================
    def _elegir_carpeta_respaldo(self) -> None:
        actual = self.txt_carpeta_respaldo.text() or str(Path.home())
        carpeta = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar carpeta para guardar los respaldos (ej. memoria USB)",
            actual,
        )
        if carpeta:
            self.txt_carpeta_respaldo.setText(str(Path(carpeta)))
            self._guardar_config_respaldos(mostrar_mensaje=False)
            self.recargar_lista_respaldos()

    def _usar_carpeta_por_defecto(self) -> None:
        defecto = str(respaldos.carpeta_respaldos_por_defecto())
        self.txt_carpeta_respaldo.setText(defecto)
        ajustes.guardar("respaldo_carpeta", "")
        self.recargar_lista_respaldos()

    def _guardar_config_respaldos(self, mostrar_mensaje: bool = True) -> None:
        ruta_txt = self.txt_carpeta_respaldo.text().strip()
        defecto = str(respaldos.carpeta_respaldos_por_defecto())
        valor_carpeta = "" if ruta_txt == defecto else ruta_txt

        ajustes.guardar_varios({
            "respaldo_carpeta": valor_carpeta,
            "respaldo_al_cerrar": self.chk_resp_cerrar.isChecked(),
            "respaldo_al_abrir": self.chk_resp_abrir.isChecked(),
            "respaldo_max_archivos": str(self.spin_max_respaldos.value()),
        })
        respaldos.rotar_respaldos()
        self.recargar_lista_respaldos()
        if mostrar_mensaje:
            QMessageBox.information(
                self, "Respaldos", "Configuración de respaldos guardada correctamente."
            )

    def _crear_respaldo_manual(self) -> None:
        try:
            info = respaldos.crear_respaldo(etiqueta="manual", usar_alternativa_local=False)
        except respaldos.ErrorRespaldo as e:
            QMessageBox.critical(self, "Error al crear respaldo", str(e))
            return

        self.recargar_lista_respaldos()
        QMessageBox.information(
            self,
            "Respaldo creado",
            f"Respaldo creado correctamente en:\n{info['ruta']}",
        )

    def _restaurar_seleccionado(self) -> None:
        fila = self.tabla_respaldos.currentRow()
        if not (0 <= fila < len(self.lista_archivos_respaldo)):
            return
        ruta = self.lista_archivos_respaldo[fila]["ruta"]
        self._ejecutar_restauracion(ruta)

    def _restaurar_desde_archivo(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar archivo de respaldo (.db)",
            self.txt_carpeta_respaldo.text() or str(Path.home()),
            "Base de datos SQLite (*.db)",
        )
        if ruta:
            self._ejecutar_restauracion(Path(ruta))

    def _eliminar_respaldo_seleccionado(self) -> None:
        indices = self._indices_respaldos_marcados()
        if not indices:
            QMessageBox.information(
                self,
                "Eliminar respaldos",
                "Marque la casilla de uno o varios respaldos en la tabla para eliminarlos.",
            )
            return

        seleccionados = [self.lista_archivos_respaldo[i] for i in indices]
        nombres = "\n".join(f"• {it['nombre']}" for it in seleccionados[:6])
        if len(seleccionados) > 6:
            nombres += f"\n... y {len(seleccionados) - 6} más."

        clave, ok = QInputDialog.getText(
            self,
            "Confirmar eliminación de respaldos",
            f"Se eliminarán {len(seleccionados)} copia(s) de seguridad:\n{nombres}\n\n"
            "Ingrese la contraseña del sistema:",
            QLineEdit.Password,
        )
        if not ok:
            return
        if not auth.verificar_clave(clave):
            QMessageBox.warning(
                self, "Eliminar respaldos", "Contraseña incorrecta. No se eliminó ningún respaldo."
            )
            return

        eliminados = 0
        errores = []
        for it in seleccionados:
            try:
                respaldos.eliminar_respaldo(it["ruta"])
                eliminados += 1
            except respaldos.ErrorRespaldo as e:
                errores.append(str(e))

        self.recargar_lista_respaldos()
        if errores:
            QMessageBox.warning(
                self,
                "Eliminación parcial",
                f"Se eliminaron {eliminados} respaldo(s).\nErrores:\n" + "\n".join(errores),
            )
        else:
            QMessageBox.information(
                self,
                "Respaldos eliminados",
                f"Se eliminaron {eliminados} copia(s) de seguridad correctamente.",
            )

    def _ejecutar_restauracion(self, ruta: Path) -> None:
        try:
            respaldos.validar_archivo_respaldo(ruta)
        except respaldos.ErrorRespaldo as e:
            QMessageBox.warning(self, "Archivo no válido", str(e))
            return

        resp = QMessageBox.question(
            self,
            "Confirmar restauración de respaldo",
            f"¿Está seguro de restaurar la base de datos desde:\n{ruta.name}?\n\n"
            "• Antes de restaurar se creará automáticamente una copia de seguridad de los datos actuales.\n"
            "• Todos los productos, ventas y cierres volverán al estado de ese respaldo.",
        )
        if resp != QMessageBox.Yes:
            return

        try:
            copia_previa = respaldos.restaurar_respaldo(ruta)
        except respaldos.ErrorRespaldo as e:
            QMessageBox.critical(self, "No se pudo restaurar", str(e))
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error inesperado", str(e))
            return

        self.cargar()
        self.nombre_tienda_cambiado.emit(ajustes.obtener("nombre_tienda"))
        self.base_datos_restaurada.emit()
        QMessageBox.information(
            self,
            "Base de datos restaurada",
            f"El respaldo '{ruta.name}' fue restaurado correctamente.\n\n"
            f"Se guardó una copia de seguridad previa de sus datos anteriores en:\n{copia_previa}",
        )
