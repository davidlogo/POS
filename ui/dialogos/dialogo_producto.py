"""
Diálogo para crear o editar un producto.

Reglas para productos POR PESO:
  1.1 Se bloquean los campos de % IVA, % Ganancia y Redondeo; el precio se asume como manual.
  1.2 Muestra el campo obligatorio «Precio de venta por libra: *», y «Costo por libra» es opcional.
  1.3 Si se escribe el costo (> 0), calcula automáticamente el % de ganancia y lo muestra
      en el campo bloqueado de % Ganancia (solo lectura).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget,
)

from modules import inventario, precios
from modules.precios import (
    calcular_ganancia_desde_precio,
    calcular_precio,
    calcular_precio_base,
)
from ui.comun import activar_formato_miles, enter_pasa_al_siguiente
from utils.dinero import formatear_pesos, parsear_pesos
from utils.peso import formatear_libras, libras_a_gramos
from utils.porcentajes import parsear_porcentaje, porcentaje_a_texto


def _cantidad_desde_texto(texto: str, tipo: str) -> int:
    """Unidades enteras (acepta puntos de miles), o libras -> gramos."""
    texto = texto.strip()
    if not texto:
        return 0
    if tipo == "peso":
        return libras_a_gramos(texto)
    limpio = texto.replace(".", "")
    if not limpio.isdigit():
        raise ValueError("Use un número entero de unidades.")
    return int(limpio)


def _cantidad_a_texto(cantidad: int, tipo: str) -> str:
    if tipo == "peso":
        return formatear_libras(cantidad)
    return f"{int(cantidad):,}".replace(",", ".")


class DialogoProducto(QDialog):
    def __init__(self, parent=None, producto: dict | None = None):
        super().__init__(parent)
        self.producto = producto
        self.producto_id = None
        self._actualizando_ui = False
        es_nuevo = producto is None
        self.setWindowTitle("Nuevo producto" if es_nuevo else "Editar producto")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        self.form = QFormLayout()
        layout.addLayout(self.form)

        self.txt_codigo = QLineEdit()
        self.txt_codigo.setPlaceholderText("Opcional: escanee o escriba")
        self.form.addRow("Código de barras:", self.txt_codigo)

        self.txt_nombre = QLineEdit()
        self.txt_nombre.setMaxLength(120)
        self.form.addRow("Nombre: *", self.txt_nombre)

        # Categoría: lista editable; si escribe una nueva, se crea al guardar
        self.cmb_categoria = QComboBox()
        self.cmb_categoria.setEditable(True)
        self.cmb_categoria.addItem("")
        self.cmb_categoria.addItems(inventario.listar_categorias())
        completador = self.cmb_categoria.completer()
        completador.setCaseSensitivity(Qt.CaseInsensitive)
        completador.setFilterMode(Qt.MatchContains)
        completador.setCompletionMode(QCompleter.PopupCompletion)
        completador.popup().setStyleSheet(
            "QAbstractItemView { background-color: #ffffff; color: #0f172a; "
            "border: 1px solid #64748b; selection-background-color: #2563eb; selection-color: #ffffff; }"
        )
        self.cmb_categoria.lineEdit().setPlaceholderText("Opcional: elija o escriba una nueva")
        self.form.addRow("Categoría:", self.cmb_categoria)

        self.cmb_tipo = QComboBox()
        self.cmb_tipo.addItem("Por unidad", "unidad")
        self.cmb_tipo.addItem("Por peso (precio por libra)", "peso")
        self.form.addRow("Tipo de venta:", self.cmb_tipo)

        self.lbl_costo = QLabel()
        self.txt_costo = QLineEdit()
        self.txt_costo.setPlaceholderText("Ej: 2.000")
        activar_formato_miles(self.txt_costo)
        self.form.addRow(self.lbl_costo, self.txt_costo)

        # Campo exclusivo para venta por peso: Precio de venta por libra
        self.lbl_precio_peso = QLabel("Precio de venta por libra: *")
        self.txt_precio_peso = QLineEdit()
        self.txt_precio_peso.setPlaceholderText("Ej: 9.000")
        activar_formato_miles(self.txt_precio_peso)
        self.form.addRow(self.lbl_precio_peso, self.txt_precio_peso)

        self.txt_ganancia = QLineEdit()
        self.txt_ganancia.setPlaceholderText("Ej: 30")
        self.form.addRow("% Ganancia:", self.txt_ganancia)

        self.cmb_iva = QComboBox()
        for valor in inventario.IVAS_PERMITIDOS:
            self.cmb_iva.addItem(porcentaje_a_texto(valor), valor)
        self.form.addRow("% IVA:", self.cmb_iva)

        # Redondeo individual del producto (solo para productos por unidad)
        self.lbl_redondeo = QLabel("Redondear precio:")
        self.contenedor_redondeo = QWidget()
        fila_red = QHBoxLayout(self.contenedor_redondeo)
        fila_red.setContentsMargins(0, 0, 0, 0)
        self.cmb_multiplo = QComboBox()
        for mult, etiqueta in precios.MULTIPLOS_REDONDEO:
            self.cmb_multiplo.addItem(etiqueta, mult)
        self.cmb_modo = QComboBox()
        for codigo, etiqueta in precios.MODOS_REDONDEO:
            self.cmb_modo.addItem(etiqueta, codigo)
        fila_red.addWidget(self.cmb_multiplo, stretch=1)
        fila_red.addWidget(self.cmb_modo, stretch=1)
        self.form.addRow(self.lbl_redondeo, self.contenedor_redondeo)

        self.lbl_tit_precio_calc = QLabel("Precio calculado:")
        self.lbl_precio_calc = QLabel()
        self.form.addRow(self.lbl_tit_precio_calc, self.lbl_precio_calc)

        # Precio manual opcional (para productos por unidad)
        self.contenedor_manual = QWidget()
        fila_manual = QHBoxLayout(self.contenedor_manual)
        fila_manual.setContentsMargins(0, 0, 0, 0)
        self.chk_manual = QCheckBox("Fijar precio manual:")
        self.txt_precio_manual = QLineEdit()
        self.txt_precio_manual.setPlaceholderText("Ej: 3.200")
        self.txt_precio_manual.setEnabled(False)
        activar_formato_miles(self.txt_precio_manual)
        fila_manual.addWidget(self.chk_manual)
        fila_manual.addWidget(self.txt_precio_manual, stretch=1)
        self.form.addRow("", self.contenedor_manual)

        self.lbl_precio = QLabel()
        self.lbl_precio.setStyleSheet("font-size: 14pt; font-weight: bold; color: #15803d;")
        self.form.addRow("Precio final de venta:", self.lbl_precio)

        # Stock
        self.lbl_stock = QLabel()
        if es_nuevo:
            self.txt_stock = QLineEdit()
            self.txt_stock.setPlaceholderText("0")
            activar_formato_miles(self.txt_stock)
            self.form.addRow(self.lbl_stock, self.txt_stock)
        else:
            self.txt_stock = None
            self.lbl_stock_actual = QLabel(
                inventario.formatear_stock(producto["tipo_venta"], producto["stock"])
                + "   (para cambiarlo use «Ajustar stock»)"
            )
            self.form.addRow(self.lbl_stock, self.lbl_stock_actual)

        self.lbl_stock_min = QLabel()
        self.txt_stock_min = QLineEdit()
        self.txt_stock_min.setPlaceholderText("0")
        activar_formato_miles(self.txt_stock_min)
        self.form.addRow(self.lbl_stock_min, self.txt_stock_min)

        self.chk_activo = QCheckBox("Producto activo (visible para vender)")
        self.chk_activo.setChecked(True)
        if not es_nuevo:
            self.form.addRow("", self.chk_activo)

        # Botones
        botones = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Save).setText("Guardar (Ctrl+S)")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar (Esc)")
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        layout.addWidget(botones)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._guardar)

        # Eventos para actualizar etiquetas y precio en vivo
        self.cmb_tipo.currentIndexChanged.connect(self._actualizar_etiquetas)
        for campo in (self.txt_costo, self.txt_ganancia, self.txt_precio_manual, self.txt_precio_peso):
            campo.textChanged.connect(self._actualizar_precio)
        self.cmb_iva.currentIndexChanged.connect(self._actualizar_precio)
        self.cmb_multiplo.currentIndexChanged.connect(self._al_cambiar_redondeo)
        self.cmb_modo.currentIndexChanged.connect(self._actualizar_precio)
        self.chk_manual.toggled.connect(self._al_cambiar_chk_manual)

        if not es_nuevo:
            self._cargar(producto)
            self.cmb_tipo.setEnabled(False)
            self.cmb_tipo.setToolTip("El tipo de venta no se puede cambiar después de crear el producto.")

        self._al_cambiar_redondeo()
        self._actualizar_etiquetas()
        enter_pasa_al_siguiente(self)
        (self.txt_codigo if es_nuevo else self.txt_nombre).setFocus()

    # -----------------------------------------------------------------
    def _tipo(self) -> str:
        return self.cmb_tipo.currentData()

    def _al_cambiar_redondeo(self) -> None:
        es_unidad = self._tipo() == "unidad"
        self.cmb_modo.setEnabled(es_unidad and self.cmb_multiplo.currentData() != 1)
        self._actualizar_precio()

    def _al_cambiar_chk_manual(self, marcado: bool) -> None:
        if self._actualizando_ui:
            return
        self.txt_precio_manual.setEnabled(marcado)
        if marcado and not self.txt_precio_manual.text().strip():
            try:
                costo = parsear_pesos(self.txt_costo.text() or "0")
                ganancia = parsear_porcentaje(self.txt_ganancia.text() or "0")
                iva = self.cmb_iva.currentData()
                mult = self.cmb_multiplo.currentData()
                modo = self.cmb_modo.currentData()
                calc = calcular_precio(costo, ganancia, iva, mult, modo)
                self.txt_precio_manual.setText(formatear_pesos(calc).replace("$ ", ""))
            except ValueError:
                pass
        self._actualizar_precio()

    def _cargar(self, p: dict) -> None:
        self._actualizando_ui = True
        try:
            self.txt_codigo.setText(p["codigo_barras"] or "")
            self.txt_nombre.setText(p["nombre"])
            self.cmb_categoria.setCurrentText(p["categoria"] or "")
            self.cmb_tipo.setCurrentIndex(self.cmb_tipo.findData(p["tipo_venta"]))
            if p["tipo_venta"] == "peso":
                self.txt_costo.setText(
                    formatear_pesos(p["costo"]).replace("$ ", "") if p["costo"] > 0 else ""
                )
                self.txt_precio_peso.setText(formatear_pesos(p["precio_final"]).replace("$ ", ""))
            else:
                self.txt_costo.setText(formatear_pesos(p["costo"]).replace("$ ", ""))
                self.txt_ganancia.setText(porcentaje_a_texto(p["ganancia_pct"]).replace(" %", ""))
                indice = self.cmb_iva.findData(p["iva_pct"])
                self.cmb_iva.setCurrentIndex(indice if indice >= 0 else 0)

                idx_m = self.cmb_multiplo.findData(p.get("redondeo_multiplo", 1))
                self.cmb_multiplo.setCurrentIndex(idx_m if idx_m >= 0 else 0)
                idx_modo = self.cmb_modo.findData(p.get("redondeo_modo", "arriba"))
                self.cmb_modo.setCurrentIndex(idx_modo if idx_modo >= 0 else 0)

                if p.get("precio_manual") is not None:
                    self.chk_manual.setChecked(True)
                    self.txt_precio_manual.setEnabled(True)
                    self.txt_precio_manual.setText(formatear_pesos(p["precio_manual"]).replace("$ ", ""))

            self.txt_stock_min.setText(_cantidad_a_texto(p["stock_minimo"], p["tipo_venta"]))
            self.chk_activo.setChecked(bool(p["activo"]))
        finally:
            self._actualizando_ui = False

    def _actualizar_etiquetas(self) -> None:
        peso = self._tipo() == "peso"
        self.lbl_costo.setText("Costo por libra (opcional):" if peso else "Costo: *")
        self.txt_costo.setPlaceholderText("Opcional: ej. 7.000" if peso else "Ej: 2.000")

        # Mostrar campo de Precio de venta por libra cuando es por peso
        self.lbl_precio_peso.setVisible(peso)
        self.txt_precio_peso.setVisible(peso)

        # Bloquear % Ganancia y % IVA cuando es por peso
        self.txt_ganancia.setReadOnly(peso)
        self.txt_ganancia.setEnabled(not peso)
        self.cmb_iva.setEnabled(not peso)
        if peso:
            self.cmb_iva.setCurrentIndex(self.cmb_iva.findData(0))

        # Ocultar controles de redondeo y de precio manual adicional cuando es por peso
        self.lbl_redondeo.setVisible(not peso)
        self.contenedor_redondeo.setVisible(not peso)
        self.lbl_tit_precio_calc.setVisible(not peso)
        self.lbl_precio_calc.setVisible(not peso)
        self.contenedor_manual.setVisible(not peso)

        self.lbl_stock.setText("Stock inicial (libras):" if peso else "Stock inicial (unidades):")
        if self.txt_stock is None:
            self.lbl_stock.setText("Stock actual:")
        self.lbl_stock_min.setText("Stock mínimo (libras):" if peso else "Stock mínimo (unidades):")
        if self.txt_stock is not None:
            activar_formato_miles(self.txt_stock, permitir_coma_decimal=peso)
        activar_formato_miles(self.txt_stock_min, permitir_coma_decimal=peso)
        if peso:
            ayuda = "Ej: 10,5  (= 5.250 g)"
            if self.txt_stock is not None:
                self.txt_stock.setPlaceholderText(ayuda)
            self.txt_stock_min.setPlaceholderText("Ej: 2")
        self._actualizar_precio()

    def _actualizar_precio(self) -> None:
        if self._actualizando_ui:
            return
        es_peso = self._tipo() == "peso"
        sufijo = " por libra" if es_peso else ""

        if es_peso:
            # En venta por peso: precio es manual, costo es opcional y calcula % ganancia
            try:
                precio_lb = parsear_pesos(self.txt_precio_peso.text())
                self.lbl_precio.setText(formatear_pesos(precio_lb) + sufijo + "  (manual)")
            except ValueError:
                precio_lb = None
                self.lbl_precio.setText("—")

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
            ganancia = parsear_porcentaje(self.txt_ganancia.text() or "0")
            iva = self.cmb_iva.currentData()
            base = calcular_precio_base(costo, ganancia, iva)
            calc = calcular_precio(costo, ganancia, iva, mult, modo)
            if mult > 1 and base != calc:
                self.lbl_precio_calc.setText(
                    f"{formatear_pesos(calc)}{sufijo}  (exacto: {formatear_pesos(base)})"
                )
            else:
                self.lbl_precio_calc.setText(formatear_pesos(calc) + sufijo)
        except ValueError:
            calc = None
            self.lbl_precio_calc.setText("—")

        if self.chk_manual.isChecked():
            try:
                manual = parsear_pesos(self.txt_precio_manual.text())
                self.lbl_precio.setText(formatear_pesos(manual) + sufijo + "  (manual)")
            except ValueError:
                self.lbl_precio.setText("—")
        elif calc is not None:
            self.lbl_precio.setText(formatear_pesos(calc) + sufijo)
        else:
            self.lbl_precio.setText("—")

    # -----------------------------------------------------------------
    def _leer_formulario(self) -> dict:
        """Convierte los campos en datos. Lanza ValueError con mensaje claro."""
        tipo = self._tipo()
        es_peso = tipo == "peso"
        datos = {
            "codigo_barras": self.txt_codigo.text(),
            "nombre": self.txt_nombre.text().strip(),
            "categoria": self.cmb_categoria.currentText().strip(),
            "tipo_venta": tipo,
            "activo": self.chk_activo.isChecked(),
        }

        if es_peso:
            texto_costo = self.txt_costo.text().strip()
            if texto_costo:
                try:
                    datos["costo"] = parsear_pesos(texto_costo)
                except ValueError:
                    raise ValueError("Costo por libra: escriba un valor en pesos sin decimales.")
            else:
                datos["costo"] = 0

            try:
                precio_lb = parsear_pesos(self.txt_precio_peso.text())
            except ValueError:
                raise ValueError(
                    "Precio de venta por libra: es obligatorio (escriba un valor en pesos sin decimales)."
                )
            if precio_lb <= 0:
                raise ValueError("El precio de venta por libra debe ser mayor que $ 0.")

            datos["iva_pct"] = 0
            datos["ganancia_pct"] = calcular_ganancia_desde_precio(datos["costo"], precio_lb)
            datos["redondeo_multiplo"] = 1
            datos["redondeo_modo"] = "arriba"
            datos["precio_manual"] = precio_lb
        else:
            try:
                datos["costo"] = parsear_pesos(self.txt_costo.text())
            except ValueError:
                raise ValueError("Costo: escriba un valor en pesos sin decimales (ej. 2.000).")
            try:
                datos["ganancia_pct"] = parsear_porcentaje(self.txt_ganancia.text() or "0")
            except ValueError as e:
                raise ValueError(f"% Ganancia: {e}")

            datos["iva_pct"] = self.cmb_iva.currentData()
            datos["redondeo_multiplo"] = self.cmb_multiplo.currentData()
            datos["redondeo_modo"] = self.cmb_modo.currentData()

            if self.chk_manual.isChecked():
                try:
                    datos["precio_manual"] = parsear_pesos(self.txt_precio_manual.text())
                except ValueError:
                    raise ValueError("Precio manual: escriba un valor en pesos sin decimales.")
            else:
                datos["precio_manual"] = None

        try:
            datos["stock_minimo"] = _cantidad_desde_texto(self.txt_stock_min.text(), tipo)
            if self.txt_stock is not None:
                datos["stock"] = _cantidad_desde_texto(self.txt_stock.text(), tipo)
        except ValueError as e:
            raise ValueError(f"Stock: {e}")
        return datos

    def _guardar(self) -> None:
        try:
            datos = self._leer_formulario()
            if self.producto is None:
                self.producto_id = inventario.crear(datos)
            else:
                inventario.actualizar(self.producto["id"], datos)
                self.producto_id = self.producto["id"]
        except ValueError as e:
            QMessageBox.warning(self, "Revise los datos", str(e))
            return
        except inventario.ErrorInventario as e:
            QMessageBox.warning(self, "Revise los datos", "\n".join(e.errores))
            return
        self.accept()
