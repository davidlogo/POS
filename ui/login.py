"""
Pantalla de acceso.

- Primera ejecución: pide crear la contraseña (y confirmarla).
- Ejecuciones siguientes: pide la contraseña para entrar.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from modules import auth, ajustes


class DialogoLogin(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.modo_crear = not auth.existe_clave()

        self.setWindowTitle("POS - Acceso")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        # Título
        titulo = QLabel(ajustes.obtener("nombre_tienda"))
        titulo.setAlignment(Qt.AlignCenter)
        titulo.setStyleSheet("font-size: 20pt; font-weight: bold; margin: 8px;")
        layout.addWidget(titulo)

        subtitulo = QLabel(
            "Bienvenido. Cree la contraseña de acceso al sistema."
            if self.modo_crear else "Ingrese su contraseña"
        )
        subtitulo.setAlignment(Qt.AlignCenter)
        subtitulo.setWordWrap(True)
        layout.addWidget(subtitulo)

        # Campos
        formulario = QFormLayout()
        self.txt_clave = QLineEdit()
        self.txt_clave.setEchoMode(QLineEdit.Password)
        formulario.addRow("Contraseña:", self.txt_clave)

        self.txt_confirmar = None
        if self.modo_crear:
            self.txt_confirmar = QLineEdit()
            self.txt_confirmar.setEchoMode(QLineEdit.Password)
            formulario.addRow("Confirmar:", self.txt_confirmar)
            ayuda = QLabel(f"Mínimo {auth.LONGITUD_MINIMA} caracteres. Guárdela en un lugar seguro.")
            ayuda.setStyleSheet("color: gray;")
            ayuda.setWordWrap(True)
            formulario.addRow("", ayuda)
        layout.addLayout(formulario)

        # Mensaje de error (oculto hasta que haga falta)
        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("color: #c0392b; font-weight: bold;")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_error)

        # Botón
        self.btn_aceptar = QPushButton("Crear contraseña y entrar" if self.modo_crear else "Entrar")
        self.btn_aceptar.setDefault(True)  # Enter = Aceptar
        self.btn_aceptar.setMinimumHeight(36)
        self.btn_aceptar.clicked.connect(self._aceptar)
        layout.addWidget(self.btn_aceptar)

        # Enter en el primer campo: pasa al siguiente (si hay) o acepta
        if self.txt_confirmar is not None:
            self.txt_clave.returnPressed.connect(self.txt_confirmar.setFocus)
            self.txt_confirmar.returnPressed.connect(self._aceptar)
        else:
            self.txt_clave.returnPressed.connect(self._aceptar)

        self.txt_clave.setFocus()

    def _mostrar_error(self, mensaje: str) -> None:
        self.lbl_error.setText(mensaje)

    def _aceptar(self) -> None:
        clave = self.txt_clave.text()

        if self.modo_crear:
            error = auth.validar_clave_nueva(clave, self.txt_confirmar.text())
            if error:
                self._mostrar_error(error)
                return
            auth.establecer_clave(clave)
            self.accept()
            return

        if auth.verificar_clave(clave):
            self.accept()
        else:
            self._mostrar_error("Contraseña incorrecta.")
            self.txt_clave.clear()
            self.txt_clave.setFocus()
