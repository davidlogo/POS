"""
Utilidades compartidas por las pantallas.

Incluye:
  1. `activar_mayusculas_en_entradas(app)`: convierte a MAYÚSCULAS en vivo lo que se escribe
     en campos de texto (sin afectar la interfaz ni las contraseñas).
  2. `activar_formato_miles(line_edit, permitir_coma_decimal=False)`: agrega automáticamente
     el punto `.` separador de miles mientras el usuario escribe números (ej. 12500 -> 12.500).
"""

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog, QLayout, QLineEdit, QPushButton, QSizePolicy


class FlowLayout(QLayout):
    """Layout responsivo que acomoda botones/controles en filas y salta de línea si falta ancho."""

    def __init__(self, parent=None, margin: int = 0, h_spacing: int = 6, v_spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._h_space = h_spacing
        self._v_space = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = eff.x()
        y = eff.y()
        line_height = 0

        for item in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_space
            if next_x - self._h_space > eff.right() and line_height > 0:
                x = eff.x()
                y = y + line_height + self._v_space
                next_x = x + hint.width() + self._h_space
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + m.bottom()


class CampoNumeroReemplazo(QLineEdit):
    """
    Cuadro numérico que al recibir clic o foco reemplaza automáticamente
    el valor actual por el primer dígito que escriba el usuario, sin obligar
    a borrar primero con Retroceso.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
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
            self.setText(texto_tecla)
            self.textEdited.emit(self.text())
            return
        if event.key() in (Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Left, Qt.Key_Right):
            self._reemplazar_al_escribir = False
        super().keyPressEvent(event)


def enter_pasa_al_siguiente(dialogo: QDialog) -> None:
    """
    En los formularios, Enter NO debe guardar: la pistola lectora envía Enter
    después de cada código y guardaría el formulario a medias.
    Aquí Enter solo pasa al siguiente campo. Para guardar se usa el botón o Ctrl+S.
    """
    for boton in dialogo.findChildren(QPushButton):
        boton.setAutoDefault(False)
        boton.setDefault(False)
    for campo in dialogo.findChildren(QLineEdit):
        campo.returnPressed.connect(dialogo.focusNextChild)


def formatear_texto_miles(texto: str, permitir_coma_decimal: bool = False) -> str:
    """
    Formatea una cadena numérica insertando puntos `.` de miles en la parte entera.
    - Si `permitir_coma_decimal=True`, permite una coma `,` para decimales (ej. "1.250,5").
    - Ignora cualquier carácter que no sea dígito (o coma si está permitida).
    """
    if not texto:
        return ""
    if permitir_coma_decimal:
        # Si el usuario escribió punto pero no coma y hay 1 o 2 dígitos después, sólo quitamos puntos previos
        partes = texto.split(",", 1)
        enteros = "".join(c for c in partes[0] if c.isdigit())
        decimales = "".join(c for c in partes[1] if c.isdigit())[:3] if len(partes) > 1 else None
    else:
        enteros = "".join(c for c in texto if c.isdigit())
        decimales = None

    if not enteros:
        return f"0,{decimales}" if decimales is not None else ""

    # Evitar ceros a la izquierda innecesarios como "0500" -> "500" (pero permitir "0")
    enteros_int = int(enteros)
    enteros_fmt = f"{enteros_int:,}".replace(",", ".")
    if decimales is not None:
        return f"{enteros_fmt},{decimales}"
    return enteros_fmt


def activar_formato_miles(widget: QLineEdit, permitir_coma_decimal: bool = False) -> None:
    """
    Conecta `widget` para que agregue automáticamente el punto `.` de miles
    a medida que se escriben números, conservando la posición natural del cursor.
    """
    if getattr(widget, "_formato_miles_conectado", False):
        widget._permitir_coma_decimal = permitir_coma_decimal
        return
    widget._formato_miles_conectado = True
    widget._permitir_coma_decimal = permitir_coma_decimal

    def _al_editar(texto: str) -> None:
        perm = getattr(widget, "_permitir_coma_decimal", False)
        pos_antes = widget.cursorPosition()
        # Contamos cuántos dígitos (o coma) había a la izquierda del cursor
        izquierda = texto[:pos_antes]
        digitos_izq = sum(1 for c in izquierda if c.isdigit() or (perm and c == ","))

        nuevo = formatear_texto_miles(texto, permitir_coma_decimal=perm)
        if nuevo == texto:
            return

        widget.blockSignals(True)
        widget.setText(nuevo)
        # Ubicamos el cursor después de la misma cantidad de dígitos
        nueva_pos = 0
        contados = 0
        for idx, ch in enumerate(nuevo, start=1):
            if ch.isdigit() or (perm and ch == ","):
                contados += 1
            if contados >= digitos_izq:
                nueva_pos = idx
                break
        if digitos_izq == 0:
            nueva_pos = 0
        elif contados < digitos_izq:
            nueva_pos = len(nuevo)
        widget.setCursorPosition(nueva_pos)
        widget.blockSignals(False)
        widget.textChanged.emit(nuevo)

    widget.textEdited.connect(_al_editar)


class _FiltroMayusculas(QObject):
    """Convierte a mayúsculas en vivo lo que el usuario escribe en cualquier QLineEdit editable."""

    def _conectar_si_aplica(self, widget: QLineEdit) -> None:
        if getattr(widget, "_mayusculas_conectado", False):
            return
        widget._mayusculas_conectado = True
        widget.textEdited.connect(lambda texto, w=widget: self._forzar_mayuscula(w, texto))

    @staticmethod
    def _forzar_mayuscula(widget: QLineEdit, texto: str) -> None:
        if widget.isReadOnly() or widget.echoMode() != QLineEdit.Normal:
            return
        if getattr(widget, "_formato_miles_conectado", False):
            return
        if getattr(widget, "property", lambda *_: None)("permitir_minusculas"):
            return
        mayus = texto.upper()
        if texto != mayus:
            pos = widget.cursorPosition()
            widget.blockSignals(True)
            widget.setText(mayus)
            widget.setCursorPosition(pos)
            widget.blockSignals(False)
            widget.textChanged.emit(mayus)

    def eventFilter(self, obj, event) -> bool:
        if isinstance(obj, QLineEdit) and event.type() in (QEvent.FocusIn, QEvent.Show, QEvent.KeyPress):
            self._conectar_si_aplica(obj)
        return super().eventFilter(obj, event)


_instancia_filtro: _FiltroMayusculas | None = None


def activar_mayusculas_en_entradas(app: QApplication) -> None:
    """Activa el filtro global de mayúsculas en todos los QLineEdit de la aplicación."""
    global _instancia_filtro
    if _instancia_filtro is None:
        _instancia_filtro = _FiltroMayusculas(app)
        app.installEventFilter(_instancia_filtro)
