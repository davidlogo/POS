"""
Hoja de estilos global del POS (tema moderno, limpio y de alto contraste para caja).

Permite ajustar dinámicamente el tamaño de letra de todas las tablas y listas
(Inventario, Precios, Ventas, Retiros y gastos, Reportes, Devoluciones, etc.).
"""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QTableWidget

from utils.rutas import carpeta_recursos

_RUTA_CHECK_SVG = (carpeta_recursos() / "recursos" / "iconos" / "check.svg").as_posix()

HOJA_ESTILOS_BASE = """
QMainWindow, QDialog, QMessageBox {
    background-color: #f4f6f9;
    color: #0f172a;
}

QWidget {
    color: #0f172a;
    font-family: "Segoe UI", "Ubuntu", sans-serif;
}

/* Pestañas principales */
QTabWidget::pane {
    border: 1px solid #cbd5e1;
    background: #ffffff;
    border-radius: 6px;
}

QTabBar::tab {
    background: #e2e8f0;
    color: #334155;
    padding: 10px 18px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: 600;
}

QTabBar::tab:selected {
    background: #1e40af;
    color: #ffffff;
}

QTabBar::tab:hover:!selected {
    background: #cbd5e1;
}

/* Grupos / tarjetas */
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
    font-weight: bold;
    color: #0f172a;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: #1e3a8a;
}

/* Campos de texto, listas desplegables, selectores numéricos y de fecha */
QLineEdit, QComboBox, QSpinBox, QDateEdit {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #94a3b8;
    border-radius: 5px;
    padding: 6px 9px;
    min-height: 24px;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {
    border: 2px solid #2563eb;
    background-color: #ffffff;
    color: #0f172a;
}

QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDateEdit:disabled {
    background-color: #e2e8f0;
    color: #334155;
}

/* Casillas de verificación (QCheckBox) y botones de opción (QRadioButton) con marco visible */
QCheckBox, QRadioButton {
    color: #0f172a;
    spacing: 8px;
    font-weight: 600;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #1e3a8a;
    border-radius: 4px;
    background-color: #ffffff;
}

QCheckBox::indicator:hover {
    border-color: #2563eb;
    background-color: #eff6ff;
}

QCheckBox::indicator:checked {
    background-color: #ffffff;
    border: 2px solid #1e3a8a;
    image: url(__RUTA_CHECK_SVG__);
}

QCheckBox::indicator:disabled {
    border-color: #94a3b8;
    background-color: #e2e8f0;
}

QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #1e3a8a;
    border-radius: 10px;
    background-color: #ffffff;
}

QRadioButton::indicator:checked {
    background-color: #2563eb;
    border: 4px solid #ffffff;
    outline: 2px solid #1e3a8a;
}

/* Lista emergente de todos los QComboBox y autocompletado (QCompleter) */
QComboBox QAbstractItemView,
QAbstractItemView,
QListView,
QMenu {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #64748b;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
    outline: none;
}

QComboBox QAbstractItemView::item,
QListView::item,
QMenu::item {
    background-color: #ffffff;
    color: #0f172a;
    padding: 6px 10px;
    min-height: 24px;
}

QComboBox QAbstractItemView::item:selected,
QComboBox QAbstractItemView::item:hover,
QListView::item:selected,
QListView::item:hover,
QMenu::item:selected {
    background-color: #2563eb;
    color: #ffffff;
}

/* Calendario desplegable en Reportes */
QCalendarWidget QWidget {
    background-color: #ffffff;
    color: #0f172a;
}

QCalendarWidget QAbstractItemView:enabled {
    background-color: #ffffff;
    color: #0f172a;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}

QToolTip {
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #94a3b8;
}

/* Botones estándar */
QPushButton {
    background-color: #ffffff;
    color: #1e293b;
    border: 1px solid #94a3b8;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #e2e8f0;
    border-color: #64748b;
}

QPushButton:pressed {
    background-color: #cbd5e1;
}

QPushButton:disabled {
    background-color: #f1f5f9;
    color: #94a3b8;
    border-color: #cbd5e1;
}

/* Tablas y listas */
QTableWidget, QListWidget {
    background-color: #ffffff;
    alternate-background-color: #f8fafc;
    color: #0f172a;
    gridline-color: #e2e8f0;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
    outline: none;
}

QTableWidget::item:selected, QTableWidget::item:selected:active, QTableWidget::item:selected:!active,
QListWidget::item:selected, QListWidget::item:selected:active, QListWidget::item:selected:!active {
    background-color: #2563eb;
    color: #ffffff;
}

QHeaderView::section {
    background-color: #1e293b;
    color: #ffffff;
    padding: 8px 10px;
    border: none;
    font-weight: bold;
}

QStatusBar {
    background-color: #1e293b;
    color: #f8fafc;
    font-weight: 600;
}
"""

HOJA_ESTILOS_BASE = HOJA_ESTILOS_BASE.replace("__RUTA_CHECK_SVG__", _RUTA_CHECK_SVG)
HOJA_ESTILOS = HOJA_ESTILOS_BASE


def aplicar_tema_claro(app: QApplication) -> None:
    """
    Fuerza el estilo 'Fusion' y una paleta clara completa para que el modo oscuro
    de Windows o Linux nunca pinte cuadros desplegables ni autocompletados en negro.
    """
    app.setStyle("Fusion")
    paleta = QPalette()
    blanco = QColor("#ffffff")
    fondo_ventana = QColor("#f4f6f9")
    texto_negro = QColor("#0f172a")
    gris_deshabilitado = QColor("#64748b")
    azul_seleccion = QColor("#2563eb")

    paleta.setColor(QPalette.Window, fondo_ventana)
    paleta.setColor(QPalette.WindowText, texto_negro)
    paleta.setColor(QPalette.Base, blanco)
    paleta.setColor(QPalette.AlternateBase, QColor("#f8fafc"))
    paleta.setColor(QPalette.ToolTipBase, blanco)
    paleta.setColor(QPalette.ToolTipText, texto_negro)
    paleta.setColor(QPalette.Text, texto_negro)
    paleta.setColor(QPalette.Button, blanco)
    paleta.setColor(QPalette.ButtonText, texto_negro)
    paleta.setColor(QPalette.BrightText, blanco)
    paleta.setColor(QPalette.Highlight, azul_seleccion)
    paleta.setColor(QPalette.HighlightedText, blanco)
    paleta.setColor(QPalette.PlaceholderText, QColor("#94a3b8"))
    paleta.setColor(QPalette.Disabled, QPalette.Text, gris_deshabilitado)
    paleta.setColor(QPalette.Disabled, QPalette.WindowText, gris_deshabilitado)
    paleta.setColor(QPalette.Disabled, QPalette.ButtonText, gris_deshabilitado)
    app.setPalette(paleta)


def construir_hoja_estilos(tamano_listas_pt: int = 12) -> str:
    """Devuelve la hoja de estilos con el tamaño de letra indicado para tablas y listas."""
    tam = max(9, min(24, int(tamano_listas_pt)))
    tam_enc = max(9, tam - 1)
    extra = f"""
QTableWidget, QTableView, QListWidget {{
    font-size: {tam}pt;
}}
QTableWidget QFrame#caja_cantidad_carrito,
QTableWidget QFrame#caja_cantidad_devolucion {{
    background-color: #ffffff;
    border: 1px solid #64748b;
    border-radius: 5px;
}}
QTableWidget QLineEdit#campo_cantidad_carrito {{
    font-size: {tam}pt;
    font-weight: bold;
    color: #0f172a;
    background-color: #ffffff;
    border: none;
    border-top-left-radius: 4px;
    border-bottom-left-radius: 4px;
    padding: 0px 8px;
    min-height: 20px;
}}
QTableWidget QLineEdit#campo_cantidad_carrito:focus {{
    background-color: #f0fdf4;
    color: #0f172a;
}}
QTableWidget QLineEdit#campo_cantidad_carrito:disabled {{
    background-color: #e2e8f0;
    color: #64748b;
}}
QTableWidget QLabel#unidad_cantidad_carrito,
QTableWidget QLabel#unidad_cantidad_devolucion {{
    font-size: {tam_enc}pt;
    font-weight: bold;
    color: #1e293b;
    background-color: #e2e8f0;
    border-left: 1px solid #94a3b8;
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
    padding: 0px 4px;
}}
QTableWidget::item, QListWidget::item {{
    padding: 4px 6px;
}}
QHeaderView::section {{
    font-size: {tam_enc}pt;
}}
"""
    return HOJA_ESTILOS_BASE + extra


def aplicar_tamano_texto_listas(tamano_pt: int) -> None:
    """
    Aplica en vivo el tamaño de letra a todas las tablas y listas abiertas en la aplicación
    y ajusta la altura uniforme de las filas para que los cuadros y casillas nunca se corten.
    """
    from PySide6.QtWidgets import QFrame, QHeaderView

    app = QApplication.instance()
    if app is None:
        return
    tam = max(9, min(24, int(tamano_pt)))
    app.setStyleSheet(construir_hoja_estilos(tam))

    altura_fila = max(42, int(tam * 2.9) + 8)
    alto_caja = max(30, int(tam * 2.1) + 4)
    ancho_lbl_unid = max(58, int(tam * 4.2))
    ancho_caja = max(175, int(tam * 12.2))
    ancho_col_cant = ancho_caja + 28
    ancho_lbl_unid_dev = max(44, int(tam * 3.5))
    ancho_caja_dev = max(118, int(tam * 9.2))
    ancho_col_dev = max(138, ancho_caja_dev + 16)

    for widget in app.allWidgets():
        if isinstance(widget, QTableWidget):
            vh = widget.verticalHeader()
            vh.setSectionResizeMode(QHeaderView.Fixed)
            vh.setMinimumSectionSize(altura_fila)
            vh.setDefaultSectionSize(altura_fila)
            for fila in range(widget.rowCount()):
                widget.setRowHeight(fila, altura_fila)
            widget.resizeColumnsToContents()
            if widget.objectName() == "tabla_carrito_ventas":
                widget.setColumnWidth(2, ancho_col_cant)
            elif widget.objectName() == "tabla_items_devoluciones":
                widget.setColumnWidth(0, max(170, widget.columnWidth(0)))
                widget.setColumnWidth(4, ancho_col_dev)
            elif widget.objectName() == "tabla_respaldos_ajustes":
                widget.setColumnWidth(0, max(68, int(tam * 4.5)))
        elif isinstance(widget, QFrame) and widget.objectName() == "caja_cantidad_carrito":
            widget.setFixedSize(ancho_caja, alto_caja)
        elif isinstance(widget, QFrame) and widget.objectName() == "caja_cantidad_devolucion":
            widget.setFixedSize(ancho_caja_dev, alto_caja)
        elif widget.objectName() == "unidad_cantidad_carrito":
            widget.setFixedWidth(ancho_lbl_unid)
        elif widget.objectName() == "unidad_cantidad_devolucion":
            widget.setFixedWidth(ancho_lbl_unid_dev)
