"""
Módulo de Devoluciones (Fase 5).

Reglas:
  * Permite buscar una venta pasada (por número de venta, fecha o producto)
    y devolver total o parcialmente sus productos.
  * El reembolso de dinero sale SIEMPRE en efectivo ('efectivo'), por lo que
    se resta del efectivo esperado en el cierre de caja y de las ventas netas
    en los reportes.
  * Por cada producto devuelto se indica si repone stock (1 = vuelve al inventario)
    o no (0 = producto dañado / merma).
  * Toda devolución y su reposición de stock se ejecutan en UNA sola transacción.
"""

from decimal import Decimal

from database.conexion import ahora, obtener_conexion, transaccion
from modules import inventario
from modules.precios import redondear_al_peso


class ErrorDevolucion(Exception):
    """Error de validación al registrar una devolución."""


def _turno_abierto_id(con) -> int | None:
    fila = con.execute(
        "SELECT id FROM turnos WHERE cerrado_en IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return fila["id"] if fila else None


# ---------------------------------------------------------------------
# Búsqueda y consulta de ventas para devolver
# ---------------------------------------------------------------------
def buscar_ventas(
    texto: str = "",
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    limite: int = 100,
    turno_id: int | None = None,
    solo_turno_abierto: bool = False,
) -> list[dict]:
    """
    Busca ventas pasadas por:
      - número de venta (ej. "15" o "#15"),
      - nombre o código de barras de algún producto dentro de la venta,
      - rango de fechas opcional ('AAAA-MM-DD'),
      - turno específico (`turno_id`) o únicamente el turno abierto actual (`solo_turno_abierto`).
    Devuelve cada venta con `total_devuelto` acumulado hasta ahora.
    """
    con = obtener_conexion()
    condiciones = []
    parametros: list = []

    if solo_turno_abierto:
        turno_actual = _turno_abierto_id(con)
        if turno_actual is None:
            return []
        condiciones.append("v.turno_id = ?")
        parametros.append(turno_actual)
    elif turno_id is not None:
        condiciones.append("v.turno_id = ?")
        parametros.append(turno_id)

    limpio = (texto or "").strip()
    if limpio:
        sin_numeral = limpio.lstrip("#").strip()
        if sin_numeral.isdigit():
            condiciones.append(
                "(v.id = ? OR EXISTS ("
                "  SELECT 1 FROM venta_items vi"
                "  WHERE vi.venta_id = v.id AND (vi.codigo_barras LIKE ? OR vi.nombre LIKE ?)"
                "))"
            )
            parametros += [int(sin_numeral), f"%{limpio}%", f"%{limpio}%"]
        else:
            condiciones.append(
                "EXISTS ("
                "  SELECT 1 FROM venta_items vi"
                "  WHERE vi.venta_id = v.id AND (vi.nombre LIKE ? OR vi.codigo_barras LIKE ?)"
                ")"
            )
            parametros += [f"%{limpio}%", f"%{limpio}%"]

    if fecha_desde:
        condiciones.append("v.fecha >= ?")
        parametros.append(f"{fecha_desde} 00:00:00")
    if fecha_hasta:
        condiciones.append("v.fecha <= ?")
        parametros.append(f"{fecha_hasta} 23:59:59")

    sql = """
        SELECT
            v.*,
            COALESCE((SELECT SUM(d.total_devuelto) FROM devoluciones d WHERE d.venta_id = v.id), 0)
                AS total_devuelto,
            (SELECT GROUP_CONCAT(vi.nombre, ', ') FROM venta_items vi WHERE vi.venta_id = v.id)
                AS resumen_productos
        FROM ventas v
    """
    if condiciones:
        sql += " WHERE " + " AND ".join(condiciones)
    sql += " ORDER BY v.id DESC LIMIT ?"
    parametros.append(limite)

    filas = obtener_conexion().execute(sql, parametros).fetchall()
    return [dict(f) for f in filas]


def obtener_venta_para_devolucion(venta_id: int) -> dict | None:
    """
    Devuelve la venta con sus líneas (`items`) y las devoluciones ya hechas.
    Cada línea incluye:
      - `cantidad`: cantidad vendida originalmente
      - `cantidad_devuelta`: suma ya devuelta en devoluciones previas
      - `cantidad_disponible`: cuánto queda por devolver
      - `valor_devuelto`: pesos ya devueltos de esa línea
      - `valor_disponible`: pesos restantes de esa línea
    """
    con = obtener_conexion()
    venta = con.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
    if venta is None:
        return None

    filas_items = con.execute(
        """
        SELECT
            vi.*,
            COALESCE((SELECT SUM(di.cantidad) FROM devolucion_items di WHERE di.venta_item_id = vi.id), 0)
                AS cantidad_devuelta,
            COALESCE((SELECT SUM(di.valor) FROM devolucion_items di WHERE di.venta_item_id = vi.id), 0)
                AS valor_devuelto,
            COALESCE((SELECT SUM(di.costo_valor) FROM devolucion_items di WHERE di.venta_item_id = vi.id), 0)
                AS costo_devuelto
        FROM venta_items vi
        WHERE vi.venta_id = ?
        ORDER BY vi.id
        """,
        (venta_id,),
    ).fetchall()

    items = []
    for f in filas_items:
        d = dict(f)
        d["cantidad_disponible"] = max(0, d["cantidad"] - d["cantidad_devuelta"])
        d["valor_disponible"] = max(0, d["subtotal"] - d["valor_devuelto"])
        d["costo_disponible"] = max(0, d["costo_total"] - d["costo_devuelto"])
        items.append(d)

    devs = con.execute(
        "SELECT * FROM devoluciones WHERE venta_id = ? ORDER BY id DESC",
        (venta_id,),
    ).fetchall()

    resultado = dict(venta)
    resultado["items"] = items
    resultado["devoluciones"] = [dict(x) for x in devs]
    resultado["total_devuelto"] = sum(x["total_devuelto"] for x in devs)
    return resultado


def calcular_valor_devolucion_item(item_venta: dict, cantidad_a_devolver: int) -> tuple[int, int]:
    """
    Calcula (valor_pesos, costo_pesos) proporcionales para `cantidad_a_devolver`
    de un ítem de venta.
    Si `cantidad_a_devolver` es igual a toda la `cantidad_disponible`, devuelve
    exactamente el saldo restante (`valor_disponible`, `costo_disponible`) para
    que nunca queden diferencias de 1 peso por redondeo.
    """
    cantidad_a_devolver = int(cantidad_a_devolver)
    if cantidad_a_devolver <= 0:
        return 0, 0
    disponible = item_venta["cantidad_disponible"]
    if cantidad_a_devolver > disponible:
        raise ErrorDevolucion(
            f"No se puede devolver más de lo disponible en '{item_venta['nombre']}'."
        )
    if cantidad_a_devolver == disponible:
        return item_venta["valor_disponible"], item_venta["costo_disponible"]

    proporcion = Decimal(cantidad_a_devolver) / Decimal(item_venta["cantidad"])
    valor = redondear_al_peso(Decimal(item_venta["subtotal"]) * proporcion)
    costo = redondear_al_peso(Decimal(item_venta["costo_total"]) * proporcion)
    return min(valor, item_venta["valor_disponible"]), min(costo, item_venta["costo_disponible"])


# ---------------------------------------------------------------------
# Registro transaccional de la devolución
# ---------------------------------------------------------------------
def registrar_devolucion(
    venta_id: int,
    motivo: str,
    lineas: list[dict],
) -> dict:
    """
    Registra una devolución (total o parcial) en efectivo.
    `lineas`: lista de diccionarios:
        [{'venta_item_id': int, 'cantidad': int, 'repone_stock': bool}]

    Devuelve:
        {'devolucion_id': int, 'venta_id': int, 'total_devuelto': int, 'items_repuestos': int}
    """
    motivo = (motivo or "").strip().upper()
    if not motivo:
        raise ErrorDevolucion("El motivo de la devolución es obligatorio.")

    info_venta = obtener_venta_para_devolucion(venta_id)
    if info_venta is None:
        raise ErrorDevolucion(f"La venta #{venta_id} no existe.")

    mapa_items = {it["id"]: it for it in info_venta["items"]}

    lineas_validas = []
    total_devuelto = 0
    for l in lineas:
        cantidad = int(l.get("cantidad") or 0)
        if cantidad <= 0:
            continue
        vi_id = l.get("venta_item_id")
        if vi_id not in mapa_items:
            raise ErrorDevolucion("Uno de los productos no pertenece a esta venta.")
        item_v = mapa_items[vi_id]
        if cantidad > item_v["cantidad_disponible"]:
            disp = inventario.formatear_stock(item_v["tipo_venta"], item_v["cantidad_disponible"])
            raise ErrorDevolucion(
                f"En '{item_v['nombre']}' solo queda disponible para devolver: {disp}."
            )
        valor, costo_valor = calcular_valor_devolucion_item(item_v, cantidad)
        total_devuelto += valor
        lineas_validas.append({
            "item_venta": item_v,
            "cantidad": cantidad,
            "valor": valor,
            "costo_valor": costo_valor,
            "repone_stock": bool(l.get("repone_stock", True)),
        })

    if not lineas_validas:
        raise ErrorDevolucion("Indique al menos un producto con cantidad a devolver mayor que 0.")

    momento = ahora()
    items_repuestos = 0

    with transaccion() as con:
        turno_id = _turno_abierto_id(con)
        if turno_id is None:
            raise ErrorDevolucion("Debe abrir un turno de caja para registrar devoluciones.")
        if info_venta.get("turno_id") != turno_id:
            raise ErrorDevolucion("Solo se permiten devoluciones de ventas del turno actual.")
        dev_id = con.execute(
            """INSERT INTO devoluciones
               (venta_id, turno_id, fecha, motivo, total_devuelto, medio_reembolso)
               VALUES (?, ?, ?, ?, ?, 'efectivo')""",
            (venta_id, turno_id, momento, motivo, total_devuelto),
        ).lastrowid

        for lv in lineas_validas:
            iv = lv["item_venta"]
            con.execute(
                """INSERT INTO devolucion_items
                   (devolucion_id, venta_item_id, cantidad, valor, costo_valor, repone_stock)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    dev_id,
                    iv["id"],
                    lv["cantidad"],
                    lv["valor"],
                    lv["costo_valor"],
                    1 if lv["repone_stock"] else 0,
                ),
            )
            if lv["repone_stock"]:
                inventario.registrar_movimiento(
                    con,
                    producto_id=iv["producto_id"],
                    tipo="devolucion",
                    cantidad=lv["cantidad"],
                    motivo=f"Devolución #{dev_id} (Venta #{venta_id}): {motivo}",
                    referencia_id=dev_id,
                )
                items_repuestos += 1

    return {
        "devolucion_id": dev_id,
        "venta_id": venta_id,
        "fecha": momento,
        "total_devuelto": total_devuelto,
        "items_repuestos": items_repuestos,
    }


def listar_devoluciones_recientes(
    limite: int = 50,
    turno_id: int | None = None,
    solo_turno_abierto: bool = False,
) -> list[dict]:
    """Últimas devoluciones registradas con resumen de productos."""
    con = obtener_conexion()
    condiciones = []
    parametros: list = []

    if solo_turno_abierto:
        turno_actual = _turno_abierto_id(con)
        if turno_actual is None:
            return []
        condiciones.append("d.turno_id = ?")
        parametros.append(turno_actual)
    elif turno_id is not None:
        condiciones.append("d.turno_id = ?")
        parametros.append(turno_id)

    sql = """
        SELECT
            d.*,
            (SELECT GROUP_CONCAT(vi.nombre, ', ')
             FROM devolucion_items di
             JOIN venta_items vi ON vi.id = di.venta_item_id
             WHERE di.devolucion_id = d.id) AS resumen_productos
        FROM devoluciones d
    """
    if condiciones:
        sql += " WHERE " + " AND ".join(condiciones)
    sql += " ORDER BY d.id DESC LIMIT ?"
    parametros.append(limite)

    filas = con.execute(sql, parametros).fetchall()
    return [dict(f) for f in filas]
