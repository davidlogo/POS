"""
Importar y exportar productos (Excel .xlsx y CSV).

Flujo de importación:
  1. leer_archivo(ruta)       -> filas "crudas" tal como vienen en el archivo
  2. validar_filas(filas)     -> cada fila con sus datos, errores y acción propuesta
  3. (la pantalla muestra la vista previa y el usuario elige Actualizar/Saltar)
  4. aplicar_importacion(...) -> guarda TODO en una sola transacción

Unidades en el archivo:
  * Productos por unidad: stock en unidades.
  * Productos por peso:   costo por LIBRA y stock en LIBRAS (el sistema lo pasa a gramos).
  * Porcentajes como número: 19 = 19 %  (también se acepta una celda con formato %).
"""

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from database.conexion import transaccion
from modules import inventario
from modules.precios import calcular_precio
from utils.dinero import formatear_pesos, parsear_pesos
from utils.peso import gramos_a_libras, libras_a_gramos
from utils.porcentajes import parsear_porcentaje, porcentaje_a_texto

MOTIVO_IMPORTACION = "Importación desde archivo"

# Columnas oficiales: (clave interna, encabezado que ve el usuario)
COLUMNAS = [
    ("codigo_barras", "Código de barras"),
    ("nombre", "Nombre"),
    ("categoria", "Categoría"),
    ("tipo_venta", "Tipo de venta"),
    ("costo", "Costo"),
    ("ganancia_pct", "% Ganancia"),
    ("iva_pct", "% IVA"),
    ("stock", "Stock"),
    ("stock_minimo", "Stock mínimo"),
]

# Otros nombres de columna que también se aceptan (ya normalizados)
_ALIAS = {
    "codigo_de_barras": "codigo_barras", "codigo_barras": "codigo_barras", "codigo": "codigo_barras",
    "cod": "codigo_barras", "barras": "codigo_barras", "ean": "codigo_barras",
    "nombre": "nombre", "producto": "nombre", "descripcion": "nombre",
    "categoria": "categoria",
    "tipo_de_venta": "tipo_venta", "tipo_venta": "tipo_venta", "tipo": "tipo_venta",
    "costo": "costo", "costo_unitario": "costo",
    "ganancia": "ganancia_pct", "ganancia_pct": "ganancia_pct", "porcentaje_ganancia": "ganancia_pct",
    "iva": "iva_pct", "iva_pct": "iva_pct", "porcentaje_iva": "iva_pct",
    "stock": "stock", "existencias": "stock", "cantidad": "stock",
    "stock_minimo": "stock_minimo", "minimo": "stock_minimo", "stock_min": "stock_minimo",
}

_TIPOS = {"unidad": "unidad", "und": "unidad", "u": "unidad", "unidades": "unidad",
          "peso": "peso", "p": "peso", "libra": "peso", "lb": "peso", "libras": "peso"}

OBLIGATORIAS = ("nombre", "costo")


class ErrorImportacion(Exception):
    """Problema con el archivo completo (no con una fila)."""


@dataclass
class FilaImportacion:
    numero: int                                   # número de fila en el archivo
    datos: dict = field(default_factory=dict)     # valores ya convertidos (None = celda vacía)
    errores: list = field(default_factory=list)
    observaciones: list = field(default_factory=list)
    existente: dict | None = None                 # producto que ya tiene ese código
    accion: str = "nuevo"                         # nuevo | actualizar | saltar | error
    precio: int | None = None                     # precio calculado (vista previa)
    final: dict = field(default_factory=dict)     # datos combinados listos para guardar


# ---------------------------------------------------------------------
# Lectura del archivo
# ---------------------------------------------------------------------
def _normalizar_encabezado(texto) -> str:
    """'% Ganancia' -> 'ganancia'   |   'Código de barras' -> 'codigo_de_barras'"""
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-z0-9]+", "_", texto.lower())
    return texto.strip("_")


def _mapear_encabezados(encabezados) -> dict[int, str]:
    """Devuelve {índice de columna: clave interna} y verifica las obligatorias."""
    mapa = {}
    for i, enc in enumerate(encabezados):
        clave = _ALIAS.get(_normalizar_encabezado(enc))
        if clave and clave not in mapa.values():
            mapa[i] = clave
    faltan = [dict(COLUMNAS)[c] for c in OBLIGATORIAS if c not in mapa.values()]
    if faltan:
        raise ErrorImportacion(
            "Al archivo le faltan columnas obligatorias: " + ", ".join(faltan)
            + ".\nUse la plantilla de ejemplo como guía."
        )
    return mapa


def _leer_xlsx(ruta: Path) -> list[tuple[int, dict]]:
    try:
        libro = load_workbook(ruta, data_only=True)
    except Exception as e:  # noqa: BLE001
        raise ErrorImportacion(f"No se pudo abrir el archivo de Excel:\n{e}")
    hoja = libro["Productos"] if "Productos" in libro.sheetnames else libro.worksheets[0]

    filas, mapa = [], None
    for fila in hoja.iter_rows():
        valores = [c.value for c in fila]
        if all(v is None or str(v).strip() == "" for v in valores):
            continue  # fila vacía
        if mapa is None:
            mapa = _mapear_encabezados(valores)  # la primera fila con datos son los encabezados
            continue
        crudo = {}
        for i, clave in mapa.items():
            if i >= len(fila):
                continue
            celda = fila[i]
            valor = celda.value
            # Celda con formato de porcentaje: Excel guarda 19 % como 0,19
            if clave in ("ganancia_pct", "iva_pct") and isinstance(valor, (int, float)) \
                    and "%" in (celda.number_format or ""):
                valor = round(valor * 100, 4)
            crudo[clave] = valor
        filas.append((fila[0].row, crudo))
    if mapa is None:
        raise ErrorImportacion("El archivo está vacío.")
    return filas


def _leer_csv(ruta: Path) -> list[tuple[int, dict]]:
    contenido = ruta.read_bytes()
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            texto = contenido.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ErrorImportacion("No se pudo leer el archivo CSV (codificación desconocida).")

    lineas = texto.splitlines()
    primera = next((l for l in lineas if l.strip()), "")
    if not primera:
        raise ErrorImportacion("El archivo está vacío.")
    # Detección automática del separador: el que más aparezca en los encabezados
    separador = max((";", ",", "\t"), key=primera.count)

    filas, mapa = [], None
    for numero, valores in enumerate(csv.reader(lineas, delimiter=separador), start=1):
        if all(not v.strip() for v in valores):
            continue
        if mapa is None:
            mapa = _mapear_encabezados(valores)
            continue
        crudo = {clave: valores[i] for i, clave in mapa.items() if i < len(valores)}
        filas.append((numero, crudo))
    return filas


def leer_archivo(ruta) -> list[tuple[int, dict]]:
    """Lee un .xlsx o .csv y devuelve [(número de fila, {clave: valor crudo})]."""
    ruta = Path(ruta)
    extension = ruta.suffix.lower()
    if extension in (".xlsx", ".xlsm"):
        return _leer_xlsx(ruta)
    if extension in (".csv", ".txt"):
        return _leer_csv(ruta)
    raise ErrorImportacion("Formato no soportado. Use un archivo .xlsx o .csv")


# ---------------------------------------------------------------------
# Conversión de cada celda
# ---------------------------------------------------------------------
def _vacio(valor) -> bool:
    return valor is None or str(valor).strip() == ""


def _texto_numero(valor) -> str:
    """Convierte un número de Excel a texto sin '.0' sobrante (2000.0 -> '2000')."""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def _a_codigo(valor) -> str | None:
    if _vacio(valor):
        return None
    texto = _texto_numero(valor)
    if re.search(r"[eE][+-]?\d+$", texto) and re.match(r"^[\d.,]+[eE]", texto):
        raise ValueError("Código en notación científica (ej. 7,7E+12). "
                         "Formatee la columna como Texto en Excel.")
    return texto


def _a_pesos(valor) -> int:
    if isinstance(valor, float) and not valor.is_integer():
        raise ValueError("no debe tener decimales")
    return parsear_pesos(_texto_numero(valor))


def _a_cantidad(valor, tipo: str) -> int:
    """Unidades (entero) o libras -> gramos."""
    texto = _texto_numero(valor)
    if tipo == "peso":
        return libras_a_gramos(texto)
    if not re.fullmatch(r"\d+", texto):
        raise ValueError("debe ser un número entero de unidades")
    return int(texto)


# ---------------------------------------------------------------------
# Validación (vista previa)
# ---------------------------------------------------------------------
def validar_filas(filas_crudas: list[tuple[int, dict]]) -> list[FilaImportacion]:
    """
    Convierte y revisa cada fila. No guarda nada.
    Los productos cuyo código ya existe quedan con acción 'saltar' por defecto;
    el usuario decide en la vista previa si actualizarlos.
    """
    resultado = []
    codigos_vistos: dict[str, int] = {}

    for numero, crudo in filas_crudas:
        f = FilaImportacion(numero=numero)
        d = f.datos

        # --- Código y búsqueda de existente ---
        try:
            d["codigo_barras"] = _a_codigo(crudo.get("codigo_barras"))
        except ValueError as e:
            f.errores.append(str(e))
            d["codigo_barras"] = None
        codigo = d["codigo_barras"]
        if codigo:
            if codigo in codigos_vistos:
                f.errores.append(f"Código repetido (ya aparece en la fila {codigos_vistos[codigo]}).")
            else:
                codigos_vistos[codigo] = numero
            f.existente = inventario.obtener_por_codigo(codigo)
        ex = f.existente

        # --- Textos (siempre en MAYÚSCULAS) ---
        d["codigo_barras"] = d["codigo_barras"].upper() if d["codigo_barras"] else None
        d["nombre"] = None if _vacio(crudo.get("nombre")) else str(crudo["nombre"]).strip().upper()
        d["categoria"] = None if _vacio(crudo.get("categoria")) else str(crudo["categoria"]).strip().upper()

        # --- Tipo de venta ---
        d["tipo_venta"] = None
        if not _vacio(crudo.get("tipo_venta")):
            tipo = _TIPOS.get(str(crudo["tipo_venta"]).strip().lower())
            if tipo is None:
                f.errores.append("Tipo de venta no válido (use 'unidad' o 'peso').")
            d["tipo_venta"] = tipo
        if ex and d["tipo_venta"] and d["tipo_venta"] != ex["tipo_venta"]:
            f.errores.append(f"No se puede cambiar el tipo de venta (el producto es por {ex['tipo_venta']}).")
        tipo_efectivo = d["tipo_venta"] or (ex["tipo_venta"] if ex else "unidad")

        # --- Números ---
        conversiones = (
            ("costo", "Costo", lambda v: _a_pesos(v)),
            ("ganancia_pct", "% Ganancia", lambda v: parsear_porcentaje(_texto_numero(v))),
            ("iva_pct", "% IVA", lambda v: parsear_porcentaje(_texto_numero(v))),
            ("stock", "Stock", lambda v: _a_cantidad(v, tipo_efectivo)),
            ("stock_minimo", "Stock mínimo", lambda v: _a_cantidad(v, tipo_efectivo)),
        )
        for clave, etiqueta, convertir in conversiones:
            valor = crudo.get(clave)
            d[clave] = None
            if _vacio(valor):
                continue
            try:
                d[clave] = convertir(valor)
            except (ValueError, ArithmeticError) as e:
                f.errores.append(f"{etiqueta}: {e}")
        if d["iva_pct"] is not None and d["iva_pct"] not in inventario.IVAS_PERMITIDOS:
            f.errores.append("% IVA debe ser 0, 5 o 19.")

        # --- Obligatorios ---
        if not d["nombre"]:
            f.errores.append("Falta el nombre.")
        if d["costo"] is None and not any("Costo" in e for e in f.errores):
            f.errores.append("Falta el costo.")

        # --- Datos finales (lo vacío conserva el valor actual o toma el valor por defecto) ---
        if ex:
            base = {"codigo_barras": ex["codigo_barras"], "nombre": ex["nombre"],
                    "categoria": ex["categoria"], "tipo_venta": ex["tipo_venta"], "costo": ex["costo"],
                    "ganancia_pct": ex["ganancia_pct"], "iva_pct": ex["iva_pct"],
                    "stock": ex["stock"], "stock_minimo": ex["stock_minimo"]}
        else:
            base = {"codigo_barras": None, "nombre": None, "categoria": None, "tipo_venta": "unidad",
                    "costo": 0, "ganancia_pct": 0, "iva_pct": 0, "stock": 0, "stock_minimo": 0}
        f.final = {k: (v if d.get(k) is not None else base[k]) for k, v in {**base, **d}.items()}

        if not f.errores:
            f.precio = calcular_precio(f.final["costo"], f.final["ganancia_pct"], f.final["iva_pct"])

        # --- Acción y observaciones ---
        if f.errores:
            f.accion = "error"
        elif ex:
            f.accion = "saltar"
            f.observaciones = _describir_cambios(ex, f.final)
            if not ex["activo"]:
                f.observaciones.insert(0, "Producto desactivado (seguirá desactivado)")
        else:
            f.accion = "nuevo"
            if not codigo:
                f.observaciones.append("Sin código: se crea como producto nuevo")
        resultado.append(f)
    return resultado


def _describir_cambios(actual: dict, nuevo: dict) -> list[str]:
    """Texto corto con lo que cambiaría al actualizar un producto existente."""
    cambios = []
    tipo = actual["tipo_venta"]

    def cantidad(v):
        return inventario.formatear_stock(tipo, v)

    reglas = (
        ("nombre", "Nombre", str),
        ("categoria", "Categoría", lambda v: v or "(sin categoría)"),
        ("costo", "Costo", formatear_pesos),
        ("ganancia_pct", "Ganancia", porcentaje_a_texto),
        ("iva_pct", "IVA", porcentaje_a_texto),
        ("stock", "Stock", cantidad),
        ("stock_minimo", "Stock mín.", cantidad),
    )
    for clave, etiqueta, fmt in reglas:
        a, b = actual[clave], nuevo[clave]
        if clave == "categoria":
            iguales = (a or "").lower() == (b or "").lower()
        else:
            iguales = a == b
        if not iguales:
            cambios.append(f"{etiqueta}: {fmt(a)} → {fmt(b)}")
    if not cambios:
        cambios.append("Sin cambios")
    return cambios


def resumen(filas: list[FilaImportacion]) -> dict:
    """Cuenta cuántas filas hay de cada tipo (para mostrar en la vista previa)."""
    r = {"nuevo": 0, "existente": 0, "actualizar": 0, "saltar": 0, "error": 0}
    for f in filas:
        if f.accion == "error":
            r["error"] += 1
        elif f.existente:
            r["existente"] += 1
            r[f.accion] += 1
        else:
            r["nuevo"] += 1
    return r


def aplicar_importacion(filas: list[FilaImportacion]) -> dict:
    """
    Guarda las filas válidas en UNA transacción (si algo falla, no se guarda nada).
    Devuelve el conteo de creados, actualizados, saltados y con error.
    """
    conteo = {"creados": 0, "actualizados": 0, "saltados": 0, "errores": 0}
    with transaccion() as con:
        for f in filas:
            if f.accion == "error":
                conteo["errores"] += 1
            elif f.accion == "saltar":
                conteo["saltados"] += 1
            elif f.accion == "nuevo":
                inventario.crear_en(con, f.final, "importacion", MOTIVO_IMPORTACION)
                conteo["creados"] += 1
            elif f.accion == "actualizar":
                pid = f.existente["id"]
                inventario.actualizar_en(con, pid, f.final)
                stock_actual = con.execute("SELECT stock FROM productos WHERE id = ?", (pid,)).fetchone()[0]
                diferencia = f.final["stock"] - stock_actual
                if diferencia:
                    inventario.registrar_movimiento(con, pid, "importacion", diferencia, MOTIVO_IMPORTACION)
                conteo["actualizados"] += 1
    return conteo


# ---------------------------------------------------------------------
# Plantilla y exportación
# ---------------------------------------------------------------------
_RELLENO_ENCABEZADO = PatternFill("solid", fgColor="1F4E78")
_FUENTE_ENCABEZADO = Font(bold=True, color="FFFFFF")


def _escribir_encabezados(hoja, encabezados) -> None:
    hoja.append(encabezados)
    for celda in hoja[1]:
        celda.fill = _RELLENO_ENCABEZADO
        celda.font = _FUENTE_ENCABEZADO
        celda.alignment = Alignment(horizontal="center")
    hoja.freeze_panes = "A2"


def _ajustar_anchos(hoja, anchos) -> None:
    for i, ancho in enumerate(anchos):
        hoja.column_dimensions[chr(ord("A") + i)].width = ancho


def generar_plantilla(ruta) -> None:
    """Crea un Excel de ejemplo con las columnas correctas e instrucciones."""
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Productos"
    _escribir_encabezados(hoja, [enc for _, enc in COLUMNAS])
    ejemplos = [
        ["7701234567890", "Arroz Diana 500 g", "Granos", "unidad", 2000, 30, 0, 24, 6],
        ["7702001000123", "Gaseosa 400 ml", "Bebidas", "unidad", 1500, 35, 19, 48, 12],
        ["", "Queso campesino", "Lácteos", "peso", 9000, 25, 0, 10.5, 2],
    ]
    for fila in ejemplos:
        hoja.append(fila)
    # La columna de código como texto, para que Excel no lo convierta en 7,7E+12
    for fila in hoja.iter_rows(min_row=2, max_row=500, min_col=1, max_col=1):
        fila[0].number_format = "@"
    for fila in hoja.iter_rows(min_row=2, max_row=500, min_col=5, max_col=5):
        fila[0].number_format = "#,##0"

    # Listas desplegables
    dv_tipo = DataValidation(type="list", formula1='"unidad,peso"', allow_blank=True)
    dv_iva = DataValidation(type="list", formula1='"0,5,19"', allow_blank=True)
    hoja.add_data_validation(dv_tipo)
    hoja.add_data_validation(dv_iva)
    dv_tipo.add("D2:D500")
    dv_iva.add("G2:G500")
    _ajustar_anchos(hoja, [18, 30, 16, 14, 12, 12, 8, 10, 13])

    ayuda = libro.create_sheet("Instrucciones")
    instrucciones = [
        "INSTRUCCIONES PARA IMPORTAR PRODUCTOS",
        "",
        "1. Llene la hoja 'Productos'. Puede borrar las filas de ejemplo.",
        "2. Columnas obligatorias: Nombre y Costo.",
        "3. Código de barras: opcional. Si ya existe en el sistema, el programa preguntará si actualizar o saltar.",
        "4. Tipo de venta: 'unidad' o 'peso'. Si se deja vacío se toma 'unidad'.",
        "5. Costo: en pesos, sin decimales. Para productos por PESO es el costo de UNA LIBRA (500 g).",
        "6. % Ganancia y % IVA: escriba el número (30 = 30 %). IVA permitido: 0, 5 o 19.",
        "7. Stock y Stock mínimo: unidades para productos por unidad; LIBRAS para productos por peso (ej. 10,5).",
        "8. El precio final se calcula solo: costo × (1 + ganancia) × (1 + IVA).",
        "9. Al actualizar un producto existente, las celdas vacías conservan el valor actual.",
        "10. También puede guardar como CSV (separado por ; o por ,).",
    ]
    for linea in instrucciones:
        ayuda.append([linea])
    ayuda["A1"].font = Font(bold=True, size=14)
    ayuda.column_dimensions["A"].width = 110
    libro.save(ruta)


def exportar_inventario(ruta, incluir_inactivos: bool = True) -> int:
    """
    Exporta el inventario a Excel con las mismas columnas de la plantilla
    (se puede editar y volver a importar). Devuelve cuántos productos exportó.
    """
    productos = inventario.buscar(incluir_inactivos=incluir_inactivos)
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Productos"
    _escribir_encabezados(hoja, [enc for _, enc in COLUMNAS] + ["Precio final", "Activo", "Stock bajo"])

    def cantidad(p, clave):
        if p["tipo_venta"] == "peso":
            return float(gramos_a_libras(p[clave]))  # en libras, como la plantilla
        return p[clave]

    def porcentaje(v):
        n = v / 100
        return int(n) if n == int(n) else n

    for p in productos:
        hoja.append([
            p["codigo_barras"] or "", p["nombre"], p["categoria"] or "", p["tipo_venta"],
            p["costo"], porcentaje(p["ganancia_pct"]), porcentaje(p["iva_pct"]),
            cantidad(p, "stock"), cantidad(p, "stock_minimo"), p["precio_final"],
            "Sí" if p["activo"] else "No",
            "Sí" if p["activo"] and p["stock"] <= p["stock_minimo"] else "",
        ])
    for fila in hoja.iter_rows(min_row=2, min_col=1, max_col=1):
        fila[0].number_format = "@"
    for col in (5, 10):
        for fila in hoja.iter_rows(min_row=2, min_col=col, max_col=col):
            fila[0].number_format = "#,##0"
    _ajustar_anchos(hoja, [18, 30, 16, 14, 12, 12, 8, 10, 13, 13, 8, 11])

    info = libro.create_sheet("Info")
    info.append(["Exportado el", datetime.now().strftime("%d-%m-%Y %H:%M")])
    info.append(["Productos", len(productos)])
    info.append(["Nota", "Stock de productos por peso expresado en libras (1 lb = 500 g)."])
    libro.save(ruta)
    return len(productos)
