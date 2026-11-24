"""
Inventario: productos, categorías y movimientos de stock.

Recordatorio de unidades:
  * Productos por unidad: stock en unidades, costo y precio por unidad.
  * Productos por peso:   stock en GRAMOS, costo y precio por LIBRA (500 g).
  * Los productos nunca se borran: se desactivan (activo = 0).
  * Todo cambio de stock queda registrado en movimientos_stock.
"""

from database.conexion import ahora, obtener_conexion, transaccion
from modules.precios import calcular_precio
from utils.peso import formatear_peso

TIPOS_VENTA = ("unidad", "peso")

# IVA permitido (centésimas): 0 %, 5 %, 19 %
IVAS_PERMITIDOS = (0, 500, 1900)

# Tipos de ajuste manual de stock y su descripción para la pantalla
TIPOS_AJUSTE = {
    "ingreso": "Ingreso de mercancía (suma)",
    "merma": "Merma / daño (resta)",
    "correccion": "Corrección por conteo (queda exactamente esta cantidad)",
}

_SQL_BASE = """
    SELECT p.*, c.nombre AS categoria
    FROM productos p
    LEFT JOIN categorias c ON c.id = p.categoria_id
"""


class ErrorInventario(Exception):
    """Error de validación. `errores` es una lista de mensajes para el usuario."""

    def __init__(self, errores):
        if isinstance(errores, str):
            errores = [errores]
        self.errores = list(errores)
        super().__init__("\n".join(self.errores))


# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------
def normalizar_codigo(codigo) -> str | None:
    """Quita espacios y pasa a MAYÚSCULAS. Un código vacío se guarda como NULL."""
    if codigo is None:
        return None
    codigo = str(codigo).strip().upper()
    return codigo or None


def formatear_stock(tipo_venta: str, cantidad: int) -> str:
    """12 -> "12"   |   peso 625 -> "625 g (1,25 lb)" """
    if tipo_venta == "peso":
        return formatear_peso(cantidad)
    return f"{int(cantidad):,}".replace(",", ".")


# ---------------------------------------------------------------------
# Categorías
# ---------------------------------------------------------------------
def listar_categorias() -> list[str]:
    filas = obtener_conexion().execute(
        "SELECT nombre FROM categorias WHERE activo = 1 ORDER BY nombre COLLATE NOCASE"
    ).fetchall()
    return [f["nombre"] for f in filas]


def _obtener_o_crear_categoria(con, nombre) -> int | None:
    """Devuelve el id de la categoría (siempre en MAYÚSCULAS); si no existe la crea. Vacío -> None."""
    nombre = (nombre or "").strip().upper()
    if not nombre:
        return None
    # La columna nombre es COLLATE NOCASE: "LÁCTEOS" y "lácteos" son la misma
    fila = con.execute("SELECT id, activo FROM categorias WHERE nombre = ?", (nombre,)).fetchone()
    if fila:
        con.execute("UPDATE categorias SET nombre = ?, activo = 1 WHERE id = ?", (nombre, fila["id"]))
        return fila["id"]
    return con.execute("INSERT INTO categorias (nombre) VALUES (?)", (nombre,)).lastrowid


# ---------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------
def buscar(texto: str = "", incluir_inactivos: bool = False, solo_stock_bajo: bool = False) -> list[dict]:
    """Busca productos por nombre o código (búsqueda parcial)."""
    condiciones, parametros = [], []
    if not incluir_inactivos:
        condiciones.append("p.activo = 1")
    if solo_stock_bajo:
        condiciones.append("p.activo = 1 AND p.stock <= p.stock_minimo")
    texto = (texto or "").strip()
    if texto:
        condiciones.append("(p.nombre LIKE ? OR p.codigo_barras LIKE ?)")
        parametros += [f"%{texto}%", f"%{texto}%"]
    sql = _SQL_BASE
    if condiciones:
        sql += " WHERE " + " AND ".join(condiciones)
    sql += " ORDER BY p.nombre COLLATE NOCASE"
    return [dict(f) for f in obtener_conexion().execute(sql, parametros).fetchall()]


def obtener(producto_id: int) -> dict | None:
    fila = obtener_conexion().execute(_SQL_BASE + " WHERE p.id = ?", (producto_id,)).fetchone()
    return dict(fila) if fila else None


def obtener_por_codigo(codigo) -> dict | None:
    """Busca por código exacto (activos e inactivos)."""
    codigo = normalizar_codigo(codigo)
    if codigo is None:
        return None
    fila = obtener_conexion().execute(
        _SQL_BASE + " WHERE p.codigo_barras = ?", (codigo,)
    ).fetchone()
    return dict(fila) if fila else None


def contar_stock_bajo() -> int:
    """Productos activos con stock <= stock mínimo."""
    return obtener_conexion().execute(
        "SELECT COUNT(*) FROM productos WHERE activo = 1 AND stock <= stock_minimo"
    ).fetchone()[0]


# ---------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------
def validar(datos: dict, producto_id: int | None = None) -> list[str]:
    """
    Revisa los datos de un producto. Devuelve la lista de errores (vacía = todo bien).
    `producto_id` se usa al editar, para no chocar consigo mismo en el código.
    """
    errores = []
    nombre = (datos.get("nombre") or "").strip()
    if not nombre:
        errores.append("El nombre es obligatorio.")
    elif len(nombre) > 120:
        errores.append("El nombre es demasiado largo (máximo 120 caracteres).")

    if datos.get("tipo_venta") not in TIPOS_VENTA:
        errores.append("El tipo de venta debe ser 'unidad' o 'peso'.")

    for campo, etiqueta in (("costo", "El costo"), ("ganancia_pct", "La ganancia"),
                            ("stock_minimo", "El stock mínimo")):
        valor = datos.get(campo)
        if not isinstance(valor, int) or valor < 0:
            errores.append(f"{etiqueta} debe ser un número entero mayor o igual a 0.")

    if datos.get("iva_pct") not in IVAS_PERMITIDOS:
        errores.append("El IVA debe ser 0 %, 5 % o 19 %.")

    if "stock" in datos:
        stock = datos.get("stock")
        if not isinstance(stock, int) or stock < 0:
            errores.append("El stock debe ser un número mayor o igual a 0.")

    codigo = normalizar_codigo(datos.get("codigo_barras"))
    if codigo:
        otro = obtener_por_codigo(codigo)
        if otro and otro["id"] != producto_id:
            estado = "" if otro["activo"] else " (desactivado; puede reactivarlo)"
            errores.append(f"El código {codigo} ya pertenece a '{otro['nombre']}'{estado}.")
    return errores


# ---------------------------------------------------------------------
# Movimientos de stock (usado también por ventas y devoluciones)
# ---------------------------------------------------------------------
def registrar_movimiento(con, producto_id: int, tipo: str, cantidad: int,
                         motivo: str | None = None, referencia_id: int | None = None) -> int:
    """
    Suma `cantidad` (positiva o negativa) al stock y deja el registro.
    Debe llamarse DENTRO de una transacción. Devuelve el stock nuevo.
    """
    fila = con.execute("SELECT stock FROM productos WHERE id = ?", (producto_id,)).fetchone()
    if fila is None:
        raise ErrorInventario("El producto no existe.")
    anterior = fila["stock"]
    nuevo = anterior + cantidad
    motivo_mayus = motivo.strip().upper() if motivo and motivo.strip() else None
    con.execute("UPDATE productos SET stock = ?, actualizado_en = ? WHERE id = ?",
                (nuevo, ahora(), producto_id))
    con.execute(
        """INSERT INTO movimientos_stock
           (producto_id, fecha, tipo, cantidad, stock_anterior, stock_nuevo, motivo, referencia_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (producto_id, ahora(), tipo, cantidad, anterior, nuevo, motivo_mayus, referencia_id),
    )
    return nuevo


# ---------------------------------------------------------------------
# Crear / editar / activar
# ---------------------------------------------------------------------
def _precios(
    con,
    producto_id: int | None,
    costo: int,
    ganancia: int,
    iva: int,
    redondeo_multiplo: int = 1,
    redondeo_modo: str = "arriba",
    precio_manual_indicado: bool = False,
    precio_manual_valor: int | None = None,
) -> tuple[int, int | None, int]:
    """Devuelve (precio_calculado, precio_manual, precio_final)."""
    calculado = calcular_precio(costo, ganancia, iva, redondeo_multiplo, redondeo_modo)
    if precio_manual_indicado:
        manual = precio_manual_valor
    elif producto_id is not None:
        fila = con.execute("SELECT precio_manual FROM productos WHERE id = ?", (producto_id,)).fetchone()
        manual = fila["precio_manual"] if fila else None
    else:
        manual = None
    return calculado, manual, (manual if manual is not None else calculado)


def crear_en(con, datos: dict, tipo_movimiento: str = "ingreso",
             motivo: str = "Stock inicial") -> int:
    """Inserta un producto dentro de una transacción ya abierta. Devuelve su id."""
    errores = validar(datos)
    if errores:
        raise ErrorInventario(errores)
    categoria_id = _obtener_o_crear_categoria(con, datos.get("categoria"))
    mult = int(datos.get("redondeo_multiplo") or 1)
    modo = datos.get("redondeo_modo") or "arriba"
    tiene_manual = "precio_manual" in datos
    calculado, manual, final = _precios(
        con, None, datos["costo"], datos["ganancia_pct"], datos["iva_pct"],
        mult, modo, tiene_manual, datos.get("precio_manual"),
    )
    momento = ahora()
    producto_id = con.execute(
        """INSERT INTO productos
           (codigo_barras, nombre, categoria_id, tipo_venta, costo, ganancia_pct, iva_pct,
            redondeo_multiplo, redondeo_modo, precio_calculado, precio_manual, precio_final,
            stock, stock_minimo, activo, creado_en, actualizado_en)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 1, ?, ?)""",
        (normalizar_codigo(datos.get("codigo_barras")), datos["nombre"].strip().upper(), categoria_id,
         datos["tipo_venta"], datos["costo"], datos["ganancia_pct"], datos["iva_pct"],
         mult, modo, calculado, manual, final, datos["stock_minimo"], momento, momento),
    ).lastrowid
    stock = datos.get("stock") or 0
    if stock:
        registrar_movimiento(con, producto_id, tipo_movimiento, stock, motivo)
    return producto_id


def crear(datos: dict) -> int:
    """Crea un producto nuevo (con su stock inicial)."""
    with transaccion() as con:
        return crear_en(con, datos)


def actualizar_en(con, producto_id: int, datos: dict) -> None:
    """
    Edita un producto dentro de una transacción ya abierta.
    NO cambia el stock (eso se hace con ajustar_stock, para dejar registro)
    ni el tipo de venta (cambiaría el significado del stock: unidades vs gramos).
    """
    actual = obtener(producto_id)
    if actual is None:
        raise ErrorInventario("El producto no existe.")
    if datos.get("tipo_venta", actual["tipo_venta"]) != actual["tipo_venta"]:
        raise ErrorInventario("No se puede cambiar el tipo de venta de un producto existente.")
    datos = {**datos, "tipo_venta": actual["tipo_venta"]}
    datos.pop("stock", None)
    errores = validar(datos, producto_id)
    if errores:
        raise ErrorInventario(errores)
    categoria_id = _obtener_o_crear_categoria(con, datos.get("categoria"))
    mult = int(datos.get("redondeo_multiplo", actual.get("redondeo_multiplo", 1)) or 1)
    modo = datos.get("redondeo_modo", actual.get("redondeo_modo", "arriba")) or "arriba"
    tiene_manual = "precio_manual" in datos
    calculado, manual, final = _precios(
        con, producto_id, datos["costo"], datos["ganancia_pct"], datos["iva_pct"],
        mult, modo, tiene_manual, datos.get("precio_manual"),
    )
    activo = int(datos.get("activo", actual["activo"]))
    con.execute(
        """UPDATE productos SET
             codigo_barras = ?, nombre = ?, categoria_id = ?, costo = ?, ganancia_pct = ?,
             iva_pct = ?, redondeo_multiplo = ?, redondeo_modo = ?,
             precio_calculado = ?, precio_manual = ?, precio_final = ?,
             stock_minimo = ?, activo = ?, actualizado_en = ?
           WHERE id = ?""",
        (normalizar_codigo(datos.get("codigo_barras")), datos["nombre"].strip().upper(), categoria_id,
         datos["costo"], datos["ganancia_pct"], datos["iva_pct"], mult, modo,
         calculado, manual, final, datos["stock_minimo"], activo, ahora(), producto_id),
    )


def actualizar(producto_id: int, datos: dict) -> None:
    with transaccion() as con:
        actualizar_en(con, producto_id, datos)


def cambiar_activo(producto_id: int, activo: bool) -> None:
    """Desactivar (borrado lógico) o reactivar un producto."""
    with transaccion() as con:
        con.execute("UPDATE productos SET activo = ?, actualizado_en = ? WHERE id = ?",
                    (1 if activo else 0, ahora(), producto_id))


def ajustar_stock(producto_id: int, tipo: str, cantidad: int, motivo: str = "") -> int:
    """
    Ajuste manual de stock. `cantidad` siempre positiva (unidades o gramos):
      - ingreso:    suma la cantidad
      - merma:      resta la cantidad
      - correccion: el stock queda EXACTAMENTE en la cantidad indicada
    Devuelve el stock nuevo.
    """
    if tipo not in TIPOS_AJUSTE:
        raise ErrorInventario("Tipo de ajuste no válido.")
    if not isinstance(cantidad, int) or cantidad < 0:
        raise ErrorInventario("La cantidad debe ser un número mayor o igual a 0.")
    if tipo != "correccion" and cantidad == 0:
        raise ErrorInventario("La cantidad debe ser mayor que 0.")
    with transaccion() as con:
        fila = con.execute("SELECT stock FROM productos WHERE id = ?", (producto_id,)).fetchone()
        if fila is None:
            raise ErrorInventario("El producto no existe.")
        actual = fila["stock"]
        if tipo == "ingreso":
            cambio = cantidad
        elif tipo == "merma":
            if cantidad > actual:
                raise ErrorInventario("La merma no puede ser mayor que el stock actual.")
            cambio = -cantidad
        else:  # correccion
            cambio = cantidad - actual
            if cambio == 0:
                raise ErrorInventario("El stock ya tiene esa cantidad; no hay nada que corregir.")
        return registrar_movimiento(con, producto_id, tipo, cambio, (motivo or "").strip() or None)


def historial_stock(producto_id: int, limite: int = 200) -> list[dict]:
    """Últimos movimientos de stock de un producto."""
    filas = obtener_conexion().execute(
        "SELECT * FROM movimientos_stock WHERE producto_id = ? ORDER BY id DESC LIMIT ?",
        (producto_id, limite),
    ).fetchall()
    return [dict(f) for f in filas]
