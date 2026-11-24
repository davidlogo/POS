"""
Pantalla de Costos y Precios.

Reglas para productos POR UNIDAD:
  - Se edita Costo, % Ganancia, % IVA, Redondeo individual (Sin redondeo, $50, $100, arriba/abajo)
    y opcionalmente Precio manual.

Reglas para productos POR PESO (punto 2.3):
  - Se bloquean % Ganancia, % IVA y Redondeo.
  - El Costo por libra es opcional.
  - Se edita directamente el «Precio de venta por libra» (asumido como manual).
  - Si hay Costo por libra (> 0), se calcula y muestra automáticamente el % de ganancia
    en el campo bloqueado de % Ganancia (solo lectura).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from modules import inventario, precios
from modules.precios import calcular_ganancia_desde_precio
from ui.comun import activar_formato_miles
from ui.dialogos.dialogo_cambio_masivo import DialogoCambioMasivo
from utils.dinero import formatear_pesos, parsear_pesos
from utils.porcentajes import parsear_porcentaje, porcentaje_a_texto

_ENCABEZADOS = [
    "Código",
    "Nombre",
    "Categoría",
    "Tipo",
    "Costo",
    "% Ganancia",
    "% IVA",
    "Redondeo",
    "Precio calculado",
    "Precio manual",
    "Precio final (venta)",
]


def _texto_redondeo(p: dict) -> str:
    if p["tipo_venta"] == "peso":
        return "Manual (peso)"
    mult = int(p.get("redondeo_multiplo") or 1)
    if mult <= 1:
        return "Sin redondeo"
    flecha = "↓" if p.get("redondeo_modo") == "abajo" else "↑"
    return f"$ {mult} {flecha}"


class PantallaPrecios(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.productos: list[dict] = []
        self._cargando_formulario = False

        layout = QVBoxLayout(self)

        # ---------------- Barra superior: Filtros de búsqueda + Cambio masivo ----------------
        fila_filtros = QHBoxLayout()
        fila_filtros.addWidget(QLabel("Buscar:"))
        self.txt_buscar = QLineEdit()
        self.txt_buscar.setPlaceholderText("Nombre o código de barras...")
        self.txt_buscar.setClearButtonEnabled(True)
        self.txt_buscar.textChanged.connect(self.recargar)
        fila_filtros.addWidget(self.txt_buscar, stretch=1)

        fila_filtros.addWidget(QLabel("Categoría:"))
        self.cmb_filtro_categoria = QComboBox()
        self.cmb_filtro_categoria.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_filtro_categoria.setMinimumContentsLength(12)
        self.cmb_filtro_categoria.currentIndexChanged.connect(self.recargar)
        fila_filtros.addWidget(self.cmb_filtro_categoria)

        self.chk_solo_manuales = QCheckBox("Solo manuales")
        self.chk_solo_manuales.toggled.connect(self.recargar)
        fila_filtros.addWidget(self.chk_solo_manuales)

        self.btn_masivo = QPushButton("Cambio masivo...")
        self.btn_masivo.setMinimumHeight(32)
        self.btn_masivo.setStyleSheet(
            "QPushButton { background-color: #1e40af; color: white; font-weight: bold; padding: 4px 12px; }"
            "QPushButton:hover { background-color: #1d4ed8; }"
        )
        self.btn_masivo.clicked.connect(self._abrir_cambio_masivo)
        fila_filtros.addWidget(self.btn_masivo)

        layout.addLayout(fila_filtros)

        # ---------------- Cuerpo: Tabla (izquierda) + Editor por producto (derecha) ----------------
        cuerpo = QSplitter(Qt.Horizontal)

        self.tabla = QTableWidget(0, len(_ENCABEZADOS))
        self.tabla.setHorizontalHeaderLabels(_ENCABEZADOS)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.ExtendedSelection)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.itemSelectionChanged.connect(self._al_seleccionar_fila)
        cuerpo.addWidget(self.tabla)

        # Panel lateral de edición rápida del producto seleccionado
        self.grupo_editor = QGroupBox("Editar costo, redondeo y precio")
        self.grupo_editor.setMinimumWidth(290)
        self.grupo_editor.setMaximumWidth(400)
        form = QFormLayout(self.grupo_editor)
        form.setVerticalSpacing(4)

        self.lbl_prod_nombre = QLabel("Seleccione un producto")
        self.lbl_prod_nombre.setStyleSheet("font-size: 13pt; font-weight: bold; color: #1e3a8a;")
        self.lbl_prod_nombre.setWordWrap(True)
        form.addRow(self.lbl_prod_nombre)

        self.lbl_prod_tipo = QLabel("—")
        self.lbl_prod_tipo.setStyleSheet("color: gray;")
        form.addRow("Unidad de precio:", self.lbl_prod_tipo)

        self.lbl_etiqueta_costo = QLabel("Costo:")
        self.txt_costo = QLineEdit()
        activar_formato_miles(self.txt_costo)
        form.addRow(self.lbl_etiqueta_costo, self.txt_costo)

        self.txt_ganancia = QLineEdit()
        form.addRow("% Ganancia:", self.txt_ganancia)

        self.cmb_iva = QComboBox()
        for v in inventario.IVAS_PERMITIDOS:
            self.cmb_iva.addItem(porcentaje_a_texto(v), v)
        form.addRow("% IVA:", self.cmb_iva)

        # Redondeo individual para este producto
        self.lbl_etiqueta_redondeo = QLabel("Redondear precio:")
        self.cmb_multiplo = QComboBox()
        for mult, etiqueta in precios.MULTIPLOS_REDONDEO:
            self.cmb_multiplo.addItem(etiqueta, mult)
        form.addRow(self.lbl_etiqueta_redondeo, self.cmb_multiplo)

        self.lbl_etiqueta_modo = QLabel("Dirección redondeo:")
        self.cmb_modo = QComboBox()
        for codigo, etiqueta in precios.MODOS_REDONDEO:
            self.cmb_modo.addItem(etiqueta, codigo)
        form.addRow(self.lbl_etiqueta_modo, self.cmb_modo)

        self.lbl_tit_exacta = QLabel("Fórmula exacta:")
        self.lbl_sin_redondear = QLabel("—")
        self.lbl_sin_redondear.setStyleSheet("color: gray;")
        form.addRow(self.lbl_tit_exacta, self.lbl_sin_redondear)

        self.lbl_tit_calculado = QLabel("Precio calculado:")
        self.lbl_calculado = QLabel("—")
        self.lbl_calculado.setStyleSheet("font-weight: bold;")
        form.addRow(self.lbl_tit_calculado, self.lbl_calculado)

        self.chk_manual = QCheckBox("Fijar un precio manual (ignora el cálculo)")
        form.addRow(self.chk_manual)

        self.lbl_etiqueta_manual = QLabel("Precio manual:")
        self.txt_manual = QLineEdit()
        self.txt_manual.setPlaceholderText("Ej: 3.200")
        self.txt_manual.setEnabled(False)
        activar_formato_miles(self.txt_manual)
        form.addRow(self.lbl_etiqueta_manual, self.txt_manual)

        self.lbl_final = QLabel("—")
        self.lbl_final.setStyleSheet("font-size: 15pt; font-weight: bold; color: #15803d;")
        form.addRow("Precio final:", self.lbl_final)

        self.btn_guardar_prod = QPushButton("Guardar precio del producto (Ctrl+S)")
        self.btn_guardar_prod.setMinimumHeight(36)
        self.btn_guardar_prod.setStyleSheet(
            "QPushButton { background-color: #15803d; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #166534; }"
        )
        self.btn_guardar_prod.clicked.connect(self._guardar_producto_actual)
        form.addRow(self.btn_guardar_prod)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._guardar_producto_actual)

        nota = QLabel(
            "• Productos por unidad: precio = costo × (1 + ganancia%) × (1 + IVA%).\n"
            "• Productos por peso: se escribe directamente el precio por libra "
            "(costo opcional para calcular % de ganancia)."
        )
        nota.setStyleSheet("color: gray; font-size: 9.5pt;")
        nota.setWordWrap(True)
        form.addRow(nota)

        cuerpo.addWidget(self.grupo_editor)
        cuerpo.setStretchFactor(0, 3)
        cuerpo.setStretchFactor(1, 1)
        layout.addWidget(cuerpo, stretch=1)

        # Eventos del editor rápido
        for campo in (self.txt_costo, self.txt_ganancia, self.txt_manual):
            campo.textChanged.connect(self._recalcular_en_vivo)
            campo.returnPressed.connect(self._guardar_producto_actual)
        self.cmb_iva.currentIndexChanged.connect(self._recalcular_en_vivo)
        self.cmb_multiplo.currentIndexChanged.connect(self._al_cambiar_redondeo_producto)
        self.cmb_modo.currentIndexChanged.connect(self._recalcular_en_vivo)
        self.chk_manual.toggled.connect(self._al_marcar_manual)

        self._recargar_combo_categorias()
        self.recargar()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._recargar_combo_categorias()
        self.recargar()

    def cargar_configuracion_redondeo(self) -> None:
        """Mantenido por compatibilidad con llamadas desde ventana_principal."""

    # -----------------------------------------------------------------
    # Tabla y filtros
    # -----------------------------------------------------------------
    def _recargar_combo_categorias(self) -> None:
        actual = self.cmb_filtro_categoria.currentData()
        self.cmb_filtro_categoria.blockSignals(True)
        self.cmb_filtro_categoria.clear()
        self.cmb_filtro_categoria.addItem("Todas las categorías", None)
        for cat in inventario.listar_categorias():
            self.cmb_filtro_categoria.addItem(cat, cat)
        idx = self.cmb_filtro_categoria.findData(actual)
        self.cmb_filtro_categoria.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_filtro_categoria.blockSignals(False)

    def _producto_actual(self) -> dict | None:
        fila = self.tabla.currentRow()
        if 0 <= fila < len(self.productos):
            return self.productos[fila]
        return None

    def _ids_seleccionados_tabla(self) -> list[int]:
        filas = sorted({idx.row() for idx in self.tabla.selectedIndexes()})
        return [self.productos[f]["id"] for f in filas if 0 <= f < len(self.productos)]

    def recargar(self, seleccionar_id: int | None = None) -> None:
        if not isinstance(seleccionar_id, int):
            actual = self._producto_actual()
            seleccionar_id = actual["id"] if actual else None

        lista = inventario.buscar(texto=self.txt_buscar.text(), incluir_inactivos=False)
        cat_filtro = self.cmb_filtro_categoria.currentData()
        if cat_filtro:
            lista = [p for p in lista if (p["categoria"] or "").lower() == cat_filtro.lower()]
        if self.chk_solo_manuales.isChecked():
            lista = [p for p in lista if p["precio_manual"] is not None or p["tipo_venta"] == "peso"]

        self.productos = lista
        self.tabla.setRowCount(len(lista))
        fila_sel = -1

        for i, p in enumerate(lista):
            if p["id"] == seleccionar_id:
                fila_sel = i
            es_peso = p["tipo_venta"] == "peso"
            sufijo = " / lb" if es_peso else ""
            tiene_manual = p["precio_manual"] is not None

            valores = [
                p["codigo_barras"] or "—",
                p["nombre"],
                p["categoria"] or "—",
                "Peso (lb)" if es_peso else "Unidad",
                formatear_pesos(p["costo"]) + sufijo,
                porcentaje_a_texto(p["ganancia_pct"]),
                porcentaje_a_texto(p["iva_pct"]),
                _texto_redondeo(p),
                formatear_pesos(p["precio_calculado"]) + sufijo,
                (formatear_pesos(p["precio_manual"]) + sufijo) if tiene_manual else "—",
                formatear_pesos(p["precio_final"]) + sufijo,
            ]
            for col, texto in enumerate(valores):
                item = QTableWidgetItem(texto)
                if col in (4, 5, 6, 7, 8, 9, 10):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if tiene_manual and col in (9, 10):
                    item.setForeground(QBrush(QColor("#b45309")))
                self.tabla.setItem(i, col, item)

        if fila_sel >= 0:
            self.tabla.setCurrentCell(fila_sel, 0)
            self.tabla.selectRow(fila_sel)
        elif lista:
            self.tabla.setCurrentCell(0, 0)
            self.tabla.selectRow(0)
        else:
            self._al_seleccionar_fila()

    # -----------------------------------------------------------------
    # Editor rápido lateral por producto
    # -----------------------------------------------------------------
    def _al_seleccionar_fila(self) -> None:
        p = self._producto_actual()
        self._cargando_formulario = True
        try:
            if not p:
                for w in (self.txt_costo, self.txt_ganancia, self.cmb_iva,
                          self.cmb_multiplo, self.cmb_modo,
                          self.chk_manual, self.txt_manual, self.btn_guardar_prod):
                    w.setEnabled(False)
                self.lbl_prod_nombre.setText("Seleccione un producto")
                self.lbl_prod_tipo.setText("—")
                self.txt_costo.clear()
                self.txt_ganancia.clear()
                self.chk_manual.setChecked(False)
                self.txt_manual.clear()
                self.lbl_sin_redondear.setText("—")
                self.lbl_calculado.setText("—")
                self.lbl_final.setText("—")
                return

            es_peso = p["tipo_venta"] == "peso"
            self.lbl_prod_nombre.setText(p["nombre"])
            self.lbl_prod_tipo.setText(
                "Venta por peso (precio manual por libra)" if es_peso else "Venta por unidad"
            )
            self.lbl_etiqueta_costo.setText("Costo por libra (opcional):" if es_peso else "Costo: *")
            self.txt_costo.setPlaceholderText("Opcional: ej. 7.000" if es_peso else "Ej: 2.000")
            self.txt_costo.setEnabled(True)
            self.btn_guardar_prod.setEnabled(True)

            if es_peso:
                self.txt_costo.setText(
                    formatear_pesos(p["costo"]).replace("$ ", "") if p["costo"] > 0 else ""
                )
                # En productos por peso: Ganancia, IVA y Redondeo bloqueados; precio siempre manual
                self.txt_ganancia.setReadOnly(True)
                self.txt_ganancia.setEnabled(False)
                self.cmb_iva.setCurrentIndex(self.cmb_iva.findData(0))
                self.cmb_iva.setEnabled(False)
                self.cmb_multiplo.setCurrentIndex(self.cmb_multiplo.findData(1))
                self.cmb_multiplo.setEnabled(False)
                self.cmb_modo.setEnabled(False)

                self.chk_manual.setChecked(True)
                self.chk_manual.setEnabled(False)
                self.lbl_etiqueta_manual.setText("Precio venta / lb: *")
                self.txt_manual.setEnabled(True)
                self.txt_manual.setText(formatear_pesos(p["precio_final"]).replace("$ ", ""))
            else:
                self.txt_costo.setText(formatear_pesos(p["costo"]).replace("$ ", ""))
                self.txt_ganancia.setReadOnly(False)
                self.txt_ganancia.setEnabled(True)
                self.txt_ganancia.setText(porcentaje_a_texto(p["ganancia_pct"]).replace(" %", ""))
                idx_iva = self.cmb_iva.findData(p["iva_pct"])
                self.cmb_iva.setCurrentIndex(idx_iva if idx_iva >= 0 else 0)
                self.cmb_iva.setEnabled(True)

                mult = int(p.get("redondeo_multiplo") or 1)
                modo = p.get("redondeo_modo") or "arriba"
                idx_m = self.cmb_multiplo.findData(mult)
                self.cmb_multiplo.setCurrentIndex(idx_m if idx_m >= 0 else 0)
                self.cmb_multiplo.setEnabled(True)
                idx_modo = self.cmb_modo.findData(modo)
                self.cmb_modo.setCurrentIndex(idx_modo if idx_modo >= 0 else 0)
                self.cmb_modo.setEnabled(mult != 1)

                tiene_manual = p["precio_manual"] is not None
                self.chk_manual.setEnabled(True)
                self.chk_manual.setChecked(tiene_manual)
                self.lbl_etiqueta_manual.setText("Precio manual:")
                self.txt_manual.setEnabled(tiene_manual)
                self.txt_manual.setText(
                    formatear_pesos(p["precio_manual"]).replace("$ ", "") if tiene_manual else ""
                )
        finally:
            self._cargando_formulario = False
        self._recalcular_en_vivo()

    def _al_cambiar_redondeo_producto(self) -> None:
        if self._cargando_formulario:
            return
        p = self._producto_actual()
        es_unidad = p is not None and p["tipo_venta"] == "unidad"
        self.cmb_modo.setEnabled(es_unidad and self.cmb_multiplo.currentData() != 1)
        self._recalcular_en_vivo()

    def _al_marcar_manual(self, marcado: bool) -> None:
        if self._cargando_formulario:
            return
        self.txt_manual.setEnabled(marcado)
        if marcado and not self.txt_manual.text().strip():
            try:
                costo = parsear_pesos(self.txt_costo.text() or "0")
                gan = parsear_porcentaje(self.txt_ganancia.text() or "0")
                iva = self.cmb_iva.currentData()
                mult = self.cmb_multiplo.currentData()
                modo = self.cmb_modo.currentData()
                calc = precios.calcular_precio(costo, gan, iva, mult, modo)
                self.txt_manual.setText(formatear_pesos(calc).replace("$ ", ""))
            except ValueError:
                pass
        self._recalcular_en_vivo()

    def _recalcular_en_vivo(self) -> None:
        if self._cargando_formulario:
            return
        p = self._producto_actual()
        if not p:
            return
        es_peso = p["tipo_venta"] == "peso"
        sufijo = " / lb" if es_peso else ""

        if es_peso:
            try:
                precio_lb = parsear_pesos(self.txt_manual.text())
                self.lbl_final.setText(formatear_pesos(precio_lb) + sufijo + " (manual)")
                self.lbl_sin_redondear.setText(formatear_pesos(precio_lb) + sufijo)
                self.lbl_calculado.setText(formatear_pesos(precio_lb) + sufijo)
            except ValueError:
                precio_lb = None
                self.lbl_final.setText("—")
                self.lbl_sin_redondear.setText("—")
                self.lbl_calculado.setText("—")

            texto_costo = self.txt_costo.text().strip()
            try:
                costo_lb = parsear_pesos(texto_costo) if texto_costo else 0
            except ValueError:
                costo_lb = 0

            self.txt_ganancia.blockSignals(True)
            if costo_lb > 0 and precio_lb is not None:
                gan_pct = calcular_ganancia_desde_precio(costo_lb, precio_lb)
                self.txt_ganancia.setText(porcentaje_a_texto(gan_pct).replace(" %", ""))
            else:
                self.txt_ganancia.setText("0")
            self.txt_ganancia.blockSignals(False)
            return

        # Producto por unidad
        mult = self.cmb_multiplo.currentData()
        modo = self.cmb_modo.currentData()
        try:
            costo = parsear_pesos(self.txt_costo.text() or "0")
            gan = parsear_porcentaje(self.txt_ganancia.text() or "0")
            iva = self.cmb_iva.currentData()
            exacto = precios.calcular_precio_base(costo, gan, iva)
            calc = precios.calcular_precio(costo, gan, iva, mult, modo)
            self.lbl_sin_redondear.setText(formatear_pesos(exacto) + sufijo)
            self.lbl_calculado.setText(formatear_pesos(calc) + sufijo)
        except ValueError:
            calc = None
            self.lbl_sin_redondear.setText("—")
            self.lbl_calculado.setText("—")

        if self.chk_manual.isChecked():
            try:
                manual = parsear_pesos(self.txt_manual.text())
                self.lbl_final.setText(formatear_pesos(manual) + sufijo + " (manual)")
            except ValueError:
                self.lbl_final.setText("—")
        elif calc is not None:
            self.lbl_final.setText(formatear_pesos(calc) + sufijo)
        else:
            self.lbl_final.setText("—")

    def _guardar_producto_actual(self) -> None:
        p = self._producto_actual()
        if not p:
            return
        es_peso = p["tipo_venta"] == "peso"

        if es_peso:
            texto_costo = self.txt_costo.text().strip()
            if texto_costo:
                try:
                    costo = parsear_pesos(texto_costo)
                except ValueError:
                    QMessageBox.warning(
                        self, "Costos y precios", "Costo por libra: escriba un valor en pesos sin decimales."
                    )
                    return
            else:
                costo = 0

            try:
                precio_lb = parsear_pesos(self.txt_manual.text())
            except ValueError:
                QMessageBox.warning(
                    self, "Costos y precios", "Precio venta / lb: escriba un valor en pesos sin decimales."
                )
                return
            if precio_lb <= 0:
                QMessageBox.warning(
                    self, "Costos y precios", "El precio de venta por libra debe ser mayor que $ 0."
                )
                return

            gan = calcular_ganancia_desde_precio(costo, precio_lb)
            precios.actualizar_precios_producto(
                p["id"],
                costo=costo,
                ganancia_pct=gan,
                iva_pct=0,
                precio_manual=precio_lb,
                redondeo_multiplo=1,
                redondeo_modo="arriba",
            )
            self.recargar(seleccionar_id=p["id"])
            return

        # Producto por unidad
        try:
            costo = parsear_pesos(self.txt_costo.text())
        except ValueError:
            QMessageBox.warning(self, "Costos y precios", "Costo: escriba un valor en pesos sin decimales.")
            return
        try:
            gan = parsear_porcentaje(self.txt_ganancia.text() or "0")
        except ValueError as e:
            QMessageBox.warning(self, "Costos y precios", f"% Ganancia: {e}")
            return
        iva = self.cmb_iva.currentData()
        mult = self.cmb_multiplo.currentData()
        modo = self.cmb_modo.currentData()

        manual = None
        if self.chk_manual.isChecked():
            try:
                manual = parsear_pesos(self.txt_manual.text())
            except ValueError:
                QMessageBox.warning(
                    self, "Costos y precios", "Precio manual: escriba un valor en pesos sin decimales."
                )
                return

        precios.actualizar_precios_producto(p["id"], costo, gan, iva, manual, mult, modo)
        self.recargar(seleccionar_id=p["id"])

    # -----------------------------------------------------------------
    # Cambio masivo
    # -----------------------------------------------------------------
    def _abrir_cambio_masivo(self) -> None:
        ids_sel = self._ids_seleccionados_tabla()
        dlg = DialogoCambioMasivo(self, ids_seleccionados=ids_sel if len(ids_sel) > 1 else None)
        if dlg.exec() and dlg.resultado:
            r = dlg.resultado
            QMessageBox.information(
                self,
                "Cambio masivo aplicado",
                f"Productos actualizados: {r['actualizados']}\n"
                f"Omitidos (precio manual / peso): {r['omitidos_manual']}\n"
                f"Sin cambios: {r['sin_cambios']}",
            )
            self.recargar()
