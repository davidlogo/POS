"""
Diálogo de cambio masivo de % de ganancia y/o % de IVA, con vista previa en vivo.

Ajustes solicitados:
  - El campo «Cambiar % Ganancia a:» inicia vacío (sin valor por defecto).
  - Las casillas de selección tienen un marco visible y claro.
  - Los productos de venta por peso tienen ganancia e IVA bloqueados (se muestran
    como omitidos en la vista previa).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from modules import inventario, precios
from ui.comun import enter_pasa_al_siguiente
from utils.dinero import formatear_pesos
from utils.porcentajes import parsear_porcentaje, porcentaje_a_texto

_ENCABEZADOS = [
    "Nombre",
    "Categoría",
    "Costo",
    "Ganancia (antes → después)",
    "IVA (antes → después)",
    "Precio anterior",
    "Precio nuevo",
    "Estado",
]


class DialogoCambioMasivo(QDialog):
    def __init__(self, parent=None, ids_seleccionados: list[int] | None = None):
        super().__init__(parent)
        self.ids_seleccionados = list(ids_seleccionados or [])
        self.resultado: dict | None = None
        self.setWindowTitle("Cambio masivo de ganancia / IVA")
        self.resize(1060, 640)

        layout = QVBoxLayout(self)

        # ---------------- Configuración del cambio (palomilla a la izquierda + etiqueta + cuadro) ----------------
        grupo = QGroupBox("Parámetros del cambio masivo")
        grilla = QGridLayout(grupo)
        grilla.setHorizontalSpacing(12)
        grilla.setVerticalSpacing(10)

        lbl_aplicar = QLabel("Aplicar a:")
        lbl_aplicar.setStyleSheet("font-weight: 600;")
        self.cmb_alcance = QComboBox()
        if self.ids_seleccionados:
            self.cmb_alcance.addItem(
                f"Productos seleccionados en la tabla ({len(self.ids_seleccionados)})",
                ("__seleccion__", None),
            )
        self.cmb_alcance.addItem("Todos los productos activos", ("__todos__", None))
        for cat in inventario.listar_categorias():
            self.cmb_alcance.addItem(f"Categoría: {cat}", ("__categoria__", cat))
        self.cmb_alcance.addItem("Productos sin categoría", ("__sin_categoria__", None))
        grilla.addWidget(lbl_aplicar, 0, 0)
        grilla.addWidget(self.cmb_alcance, 0, 1, 1, 2)

        # Fila 1: [✓] % Ganancia:   [ cuadro para escribir ]
        self.chk_ganancia = QCheckBox("% Ganancia:")
        self.chk_ganancia.setChecked(True)
        self.txt_ganancia = QLineEdit("")
        self.txt_ganancia.setPlaceholderText("Escriba el % (ej. 30)")
        self.txt_ganancia.setFixedWidth(200)
        grilla.addWidget(self.chk_ganancia, 1, 0)
        grilla.addWidget(self.txt_ganancia, 1, 1, alignment=Qt.AlignLeft)

        # Fila 2: [ ] % IVA:        [ desplegable ]
        self.chk_iva = QCheckBox("% IVA:")
        self.cmb_iva = QComboBox()
        for v in inventario.IVAS_PERMITIDOS:
            self.cmb_iva.addItem(porcentaje_a_texto(v), v)
        self.cmb_iva.setEnabled(False)
        self.cmb_iva.setFixedWidth(200)
        grilla.addWidget(self.chk_iva, 2, 0)
        grilla.addWidget(self.cmb_iva, 2, 1, alignment=Qt.AlignLeft)

        # Fila 3: [ ] Aplicar a productos con precios manuales...
        self.chk_aplicar_manuales = QCheckBox(
            "Aplicar a productos con precios manuales (quitar precio manual y usar el nuevo cálculo)"
        )
        self.chk_aplicar_manuales.setChecked(False)
        grilla.addWidget(self.chk_aplicar_manuales, 3, 0, 1, 3)
        grilla.setColumnStretch(2, 1)

        layout.addWidget(grupo)

        # ---------------- Resumen y tabla de vista previa ----------------
        self.lbl_resumen = QLabel()
        self.lbl_resumen.setStyleSheet("font-size: 11pt;")
        self.lbl_resumen.setWordWrap(True)
        layout.addWidget(self.lbl_resumen)

        self.tabla = QTableWidget(0, len(_ENCABEZADOS))
        self.tabla.setHorizontalHeaderLabels(_ENCABEZADOS)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionMode(QTableWidget.NoSelection)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.tabla)

        # ---------------- Botones inferiores ----------------
        abajo = QHBoxLayout()
        abajo.addStretch()
        self.btn_aplicar = QPushButton("Aplicar cambios")
        self.btn_aplicar.setMinimumHeight(36)
        self.btn_aplicar.setStyleSheet(
            "QPushButton { background-color: #15803d; color: white; font-weight: bold; padding: 6px 14px; }"
            "QPushButton:hover { background-color: #166534; }"
            "QPushButton:disabled { background-color: #cbd5e1; color: #64748b; }"
        )
        self.btn_aplicar.clicked.connect(self._aplicar)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.setMinimumHeight(36)
        btn_cancelar.clicked.connect(self.reject)
        abajo.addWidget(self.btn_aplicar)
        abajo.addWidget(btn_cancelar)
        layout.addLayout(abajo)

        # Conexiones para vista previa en vivo
        self.cmb_alcance.currentIndexChanged.connect(self._actualizar_vista_previa)
        self.chk_ganancia.toggled.connect(self._al_cambiar_switches)
        self.chk_iva.toggled.connect(self._al_cambiar_switches)
        self.txt_ganancia.textChanged.connect(self._actualizar_vista_previa)
        self.cmb_iva.currentIndexChanged.connect(self._actualizar_vista_previa)
        self.chk_aplicar_manuales.toggled.connect(self._al_cambiar_switches)

        enter_pasa_al_siguiente(self)
        self._al_cambiar_switches()
        self.txt_ganancia.setFocus()

    # -----------------------------------------------------------------
    def _al_cambiar_switches(self) -> None:
        self.txt_ganancia.setEnabled(self.chk_ganancia.isChecked())
        self.cmb_iva.setEnabled(self.chk_iva.isChecked())
        self._actualizar_vista_previa()

    def _ids_objetivo(self) -> list[int]:
        tipo, valor = self.cmb_alcance.currentData()
        if tipo == "__seleccion__":
            return self.ids_seleccionados
        todos = inventario.buscar(incluir_inactivos=False)
        if tipo == "__todos__":
            return [p["id"] for p in todos]
        if tipo == "__categoria__":
            return [p["id"] for p in todos if (p["categoria"] or "").lower() == valor.lower()]
        return [p["id"] for p in todos if not p["categoria"]]

    def _parametros(self) -> tuple[int | None, int | None]:
        """Devuelve (nueva_ganancia_pct, nuevo_iva_pct). Lanza ValueError si hay error."""
        if not self.chk_ganancia.isChecked() and not self.chk_iva.isChecked():
            raise ValueError("Marque al menos una opción: cambiar % Ganancia o cambiar % IVA.")
        nueva_gan = None
        if self.chk_ganancia.isChecked():
            texto = self.txt_ganancia.text().strip()
            if not texto:
                raise ValueError("Escriba el nuevo porcentaje de ganancia para ver la vista previa.")
            nueva_gan = parsear_porcentaje(texto)
        nuevo_iva = self.cmb_iva.currentData() if self.chk_iva.isChecked() else None
        return nueva_gan, nuevo_iva

    def _actualizar_vista_previa(self) -> None:
        try:
            nueva_gan, nuevo_iva = self._parametros()
        except ValueError as e:
            self.tabla.setRowCount(0)
            self.lbl_resumen.setText(f"<span style='color:#1e3a8a'><b>{e}</b></span>")
            self.btn_aplicar.setText("Aplicar cambios (0 productos)")
            self.btn_aplicar.setEnabled(False)
            return

        ids = self._ids_objetivo()
        vista = precios.previsualizar_cambio_masivo(
            ids,
            nueva_ganancia_pct=nueva_gan,
            nuevo_iva_pct=nuevo_iva,
            aplicar_a_manuales=self.chk_aplicar_manuales.isChecked(),
        )

        self.tabla.setRowCount(len(vista))
        cambian = 0
        omitidos = 0

        for i, item in enumerate(vista):
            es_peso = item["tipo_venta"] == "peso"
            sufijo = " / lb" if es_peso else ""
            if item["omitido_por_manual"]:
                omitidos += 1
                estado = "Omitido (venta por peso)" if es_peso else "Omitido (tiene precio manual)"
                fondo, letra = "#fff3cd", "#856404"
            elif item["cambia"]:
                cambian += 1
                estado = "Se actualizará (quita manual)" if item["tenia_manual"] else "Se actualizará"
                fondo, letra = "#d4edda", "#155724"
            else:
                estado = "Sin cambios"
                fondo, letra = None, None

            valores = [
                item["nombre"],
                item["categoria"] or "—",
                formatear_pesos(item["costo"]) + sufijo,
                f"{porcentaje_a_texto(item['ganancia_anterior'])} → {porcentaje_a_texto(item['ganancia_nueva'])}",
                f"{porcentaje_a_texto(item['iva_anterior'])} → {porcentaje_a_texto(item['iva_nuevo'])}",
                formatear_pesos(item["precio_anterior"]) + sufijo,
                formatear_pesos(item["precio_nuevo"]) + sufijo,
                estado,
            ]
            for col, texto in enumerate(valores):
                celda = QTableWidgetItem(texto)
                if col in (2, 5, 6):
                    celda.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if fondo:
                    celda.setBackground(QBrush(QColor(fondo)))
                    celda.setForeground(QBrush(QColor(letra)))
                self.tabla.setItem(i, col, celda)

        self.lbl_resumen.setText(
            f"Vista previa: <b>{len(vista)}</b> productos en el grupo · "
            f"<span style='color:#28a745'><b>{cambian}</b> se actualizarán</span> · "
            f"<span style='color:#d39e00'><b>{omitidos}</b> omitidos (precio manual / peso)</span>"
        )
        self.btn_aplicar.setText(f"Aplicar cambios ({cambian} productos)")
        self.btn_aplicar.setEnabled(cambian > 0)

    def _aplicar(self) -> None:
        try:
            nueva_gan, nuevo_iva = self._parametros()
        except ValueError as e:
            QMessageBox.warning(self, "Cambio masivo", str(e))
            return

        ids = self._ids_objetivo()
        if QMessageBox.question(
            self,
            "Confirmar cambio masivo",
            "¿Aplicar los nuevos porcentajes y precios mostrados en la vista previa?",
        ) != QMessageBox.Yes:
            return

        self.resultado = precios.aplicar_cambio_masivo(
            ids,
            nueva_ganancia_pct=nueva_gan,
            nuevo_iva_pct=nuevo_iva,
            aplicar_a_manuales=self.chk_aplicar_manuales.isChecked(),
        )
        self.accept()
