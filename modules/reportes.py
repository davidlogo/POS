"""
Módulo de Reportes y exportación a Excel (.xlsx).

Cubre 4 submódulos:
  1. Ventas (resumen, listado, detalle y productos más vendidos).
  2. Inventario (estado actual, valorización y movimientos de stock del período/cierre).
  3. Devoluciones (resumen, listado y detalle por producto; al exportar a Excel
     incluye fecha y hora completa dd-mm-aaaa HH:MM:SS).
  4. Caja (turnos/cierres del período o cierre específico y sus retiros/gastos,
     con fecha y hora completa en Excel).
"""

from datetime import datetime
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from database.conexion import obtener_conexion
from modules import caja, inventario, ventas
from modules.precios import redondear_al_peso
from utils.fechas import formatear_fecha_dmy, formatear_fecha_hora_dmy
from utils.porcentajes import a_decimal


def _limites_timestamp(fecha_desde: str, fecha_hasta: str) -> tuple[str, str]:
    """Convierte ('2026-11-18', '2026-11-18') en límites completos con hora."""
    return f"{fecha_desde} 00:00:00", f"{fecha_hasta} 23:59:59"


def _clausula_filtro(
    prefijo: str,
    fecha_desde: str | None,
    fecha_hasta: str | None,
    turno_id: int | None,
) -> tuple[str, tuple]:
    """Construye la cláusula WHERE por turno, rango de fechas o todos los registros."""
    if turno_id is not None:
        return f"{prefijo}turno_id = ?", (turno_id,)
    if not fecha_desde and not fecha_hasta:
        return "1 = 1", ()
    ini, fin = _limites_timestamp(fecha_desde or "", fecha_hasta or "")
    return f"{prefijo}fecha >= ? AND {prefijo}fecha <= ?", (ini, fin)


def _ventana_tiempo(
    fecha_desde: str | None,
    fecha_hasta: str | None,
    turno_id: int | None,
) -> tuple[str, str]:
    """Devuelve el rango (inicio, fin) 'AAAA-MM-DD HH:MM:SS' para tablas sin columna turno_id."""
    if turno_id is not None:
        turno = caja.obtener_turno(turno_id)
        if turno:
            ini = turno["abierto_en"]
            fin = turno["cerrado_en"] or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return ini, fin
        return "9999-12-31 23:59:59", "0000-01-01 00:00:00"
    if not fecha_desde and not fecha_hasta:
        return "0000-01-01 00:00:00", "9999-12-31 23:59:59"
    return _limites_timestamp(fecha_desde or "", fecha_hasta or "")


# =====================================================================
# 1. REPORTES DE VENTAS
# =====================================================================
def obtener_resumen(
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    turno_id: int | None = None,
) -> dict:
    """
    Calcula todos los indicadores de ventas del rango [fecha_desde, fecha_hasta]
    o de un cierre (`turno_id`). Todos los valores de dinero son enteros en pesos.
    """
    con = obtener_conexion()
    where_v, params_v = _clausula_filtro("", fecha_desde, fecha_hasta, turno_id)
    where_d_alias, params_d_alias = _clausula_filtro("d.", fecha_desde, fecha_hasta, turno_id)
    where_d, params_d = _clausula_filtro("", fecha_desde, fecha_hasta, turno_id)

    fila_v = con.execute(
        f"""
        SELECT
            COUNT(*) AS numero_ventas,
            COALESCE(SUM(total), 0) AS total_bruto,
            COALESCE(SUM(total_iva), 0) AS total_iva,
            COALESCE(SUM(total_costo), 0) AS total_costo,
            COALESCE(SUM(CASE WHEN medio_pago = 'efectivo' THEN total ELSE 0 END), 0) AS ventas_efectivo,
            COALESCE(SUM(CASE WHEN medio_pago = 'tarjeta' THEN total ELSE 0 END), 0) AS ventas_tarjeta,
            COALESCE(SUM(CASE WHEN medio_pago = 'transferencia' THEN total ELSE 0 END), 0) AS ventas_transferencia
        FROM ventas
        WHERE {where_v}
        """,
        params_v,
    ).fetchone()

    numero_ventas = fila_v["numero_ventas"]
    total_bruto = fila_v["total_bruto"]
    total_iva = fila_v["total_iva"]
    total_costo = fila_v["total_costo"]
    ventas_efectivo = fila_v["ventas_efectivo"]
    ventas_tarjeta = fila_v["ventas_tarjeta"]
    ventas_transferencia = fila_v["ventas_transferencia"]

    filas_dev = con.execute(
        f"""
        SELECT
            di.valor,
            di.costo_valor,
            vi.iva_pct
        FROM devolucion_items di
        JOIN devoluciones d ON d.id = di.devolucion_id
        JOIN venta_items vi ON vi.id = di.venta_item_id
        WHERE {where_d_alias}
        """,
        params_d_alias,
    ).fetchall()

    numero_devoluciones = con.execute(
        f"SELECT COUNT(*) FROM devoluciones WHERE {where_d}",
        params_d,
    ).fetchone()[0]

    total_devoluciones = 0
    costo_devuelto = 0
    iva_devuelto = 0
    for fd in filas_dev:
        val = fd["valor"]
        total_devoluciones += val
        costo_devuelto += fd["costo_valor"]
        if fd["iva_pct"] > 0:
            tasa = a_decimal(fd["iva_pct"])
            base = Decimal(val) / (Decimal(1) + tasa)
            iva_devuelto += redondear_al_peso(Decimal(val) - base)

    venta_neta = total_bruto - total_devoluciones
    costo_neto = total_costo - costo_devuelto
    iva_neto = total_iva - iva_devuelto

    ganancia_estimada = (venta_neta - iva_neto) - costo_neto
    ganancia_bruta_con_iva = venta_neta - costo_neto

    ticket_promedio = redondear_al_peso(Decimal(total_bruto) / Decimal(numero_ventas)) if numero_ventas > 0 else 0
    efectivo_neto = ventas_efectivo - total_devoluciones

    return {
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "turno_id": turno_id,
        "numero_ventas": numero_ventas,
        "total_bruto": total_bruto,
        "numero_devoluciones": numero_devoluciones,
        "total_devoluciones": total_devoluciones,
        "venta_neta": venta_neta,
        "ticket_promedio": ticket_promedio,
        "ventas_efectivo": ventas_efectivo,
        "ventas_tarjeta": ventas_tarjeta,
        "ventas_transferencia": ventas_transferencia,
        "efectivo_neto": efectivo_neto,
        "total_costo": total_costo,
        "costo_neto": costo_neto,
        "total_iva": total_iva,
        "iva_neto": iva_neto,
        "ganancia_estimada": ganancia_estimada,
        "ganancia_con_iva": ganancia_bruta_con_iva,
    }


def listar_ventas_periodo(
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    turno_id: int | None = None,
) -> list[dict]:
    """Lista las ventas del período o cierre con su costo, ganancia y devoluciones."""
    where_v, params_v = _clausula_filtro("v.", fecha_desde, fecha_hasta, turno_id)
    sql = f"""
        SELECT
            v.*,
            COALESCE((SELECT SUM(d.total_devuelto) FROM devoluciones d WHERE d.venta_id = v.id), 0)
                AS devuelto_de_esta_venta,
            (SELECT COUNT(*) FROM venta_items vi WHERE vi.venta_id = v.id)
                AS cantidad_lineas,
            (SELECT GROUP_CONCAT(vi.nombre, ', ') FROM venta_items vi WHERE vi.venta_id = v.id)
                AS resumen_productos
        FROM ventas v
        WHERE {where_v}
        ORDER BY v.id DESC
    """
    filas = obtener_conexion().execute(sql, params_v).fetchall()
    resultado = []
    for f in filas:
        d = dict(f)
        d["ganancia_venta"] = (d["total"] - d["total_iva"]) - d["total_costo"]
        resultado.append(d)
    return resultado


def obtener_detalle_venta(venta_id: int) -> dict | None:
    """Devuelve el encabezado de una venta, sus líneas históricas y sus devoluciones."""
    con = obtener_conexion()
    venta = con.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
    if venta is None:
        return None

    items = con.execute(
        """
        SELECT
            vi.*,
            COALESCE((SELECT SUM(di.cantidad) FROM devolucion_items di WHERE di.venta_item_id = vi.id), 0)
                AS cantidad_devuelta,
            COALESCE((SELECT SUM(di.valor) FROM devolucion_items di WHERE di.venta_item_id = vi.id), 0)
                AS valor_devuelto
        FROM venta_items vi
        WHERE vi.venta_id = ?
        ORDER BY vi.id
        """,
        (venta_id,),
    ).fetchall()

    devs = con.execute(
        "SELECT * FROM devoluciones WHERE venta_id = ? ORDER BY id",
        (venta_id,),
    ).fetchall()

    d = dict(venta)
    d["items"] = [dict(x) for x in items]
    d["devoluciones"] = [dict(x) for x in devs]
    return d


def productos_mas_vendidos(
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    limite: int = 100,
    turno_id: int | None = None,
) -> list[dict]:
    """Ranking de productos vendidos en el período o cierre, descontando devoluciones."""
    con = obtener_conexion()
    where_v, params_v = _clausula_filtro("v.", fecha_desde, fecha_hasta, turno_id)
    where_d, params_d = _clausula_filtro("d.", fecha_desde, fecha_hasta, turno_id)

    filas_v = con.execute(
        f"""
        SELECT
            vi.producto_id,
            MAX(vi.nombre) AS nombre,
            MAX(vi.codigo_barras) AS codigo_barras,
            vi.tipo_venta,
            SUM(vi.cantidad) AS cantidad_vendida,
            SUM(vi.subtotal) AS total_vendido,
            SUM(vi.iva_valor) AS iva_vendido,
            SUM(vi.costo_total) AS costo_vendido
        FROM venta_items vi
        JOIN ventas v ON v.id = vi.venta_id
        WHERE {where_v}
        GROUP BY vi.producto_id, vi.tipo_venta
        """,
        params_v,
    ).fetchall()

    filas_d = con.execute(
        f"""
        SELECT
            vi.producto_id,
            vi.tipo_venta,
            SUM(di.cantidad) AS cantidad_devuelta,
            SUM(di.valor) AS valor_devuelto,
            SUM(di.costo_valor) AS costo_devuelto
        FROM devolucion_items di
        JOIN devoluciones d ON d.id = di.devolucion_id
        JOIN venta_items vi ON vi.id = di.venta_item_id
        WHERE {where_d}
        GROUP BY vi.producto_id, vi.tipo_venta
        """,
        params_d,
    ).fetchall()

    mapa_dev = {(f["producto_id"], f["tipo_venta"]): dict(f) for f in filas_d}

    ranking = []
    for f in filas_v:
        clave = (f["producto_id"], f["tipo_venta"])
        dev = mapa_dev.get(clave, {})
        cant_dev = dev.get("cantidad_devuelta", 0)
        val_dev = dev.get("valor_devuelto", 0)
        costo_dev = dev.get("costo_devuelto", 0)

        cant_neta = f["cantidad_vendida"] - cant_dev
        venta_neta = f["total_vendido"] - val_dev
        costo_neto = f["costo_vendido"] - costo_dev
        if f["total_vendido"] > 0:
            prop = Decimal(venta_neta) / Decimal(f["total_vendido"])
            iva_neto = redondear_al_peso(Decimal(f["iva_vendido"]) * prop)
        else:
            iva_neto = 0
        ganancia = (venta_neta - iva_neto) - costo_neto

        ranking.append({
            "producto_id": f["producto_id"],
            "codigo_barras": f["codigo_barras"],
            "nombre": f["nombre"],
            "tipo_venta": f["tipo_venta"],
            "cantidad_vendida": f["cantidad_vendida"],
            "cantidad_devuelta": cant_dev,
            "cantidad_neta": cant_neta,
            "total_vendido": f["total_vendido"],
            "valor_devuelto": val_dev,
            "venta_neta": venta_neta,
            "costo_neto": costo_neto,
            "ganancia_estimada": ganancia,
        })

    ranking.sort(key=lambda r: (r["venta_neta"], r["cantidad_neta"]), reverse=True)
    return ranking[:limite]


# =====================================================================
# 2. REPORTES DE INVENTARIO
# =====================================================================
def obtener_reporte_inventario(
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    turno_id: int | None = None,
) -> dict:
    """
    Devuelve el estado actual del inventario valorizado (costo y precio de venta)
    y los movimientos de stock registrados en el período o cierre.
    """
    productos = inventario.buscar(incluir_inactivos=False)
    items_inv = []
    stock_bajo = 0
    sin_stock = 0
    valor_venta_total = 0
    valor_costo_total = 0
    por_unidad = 0
    por_peso = 0

    for p in productos:
        es_peso = p["tipo_venta"] == "peso"
        if es_peso:
            por_peso += 1
        else:
            por_unidad += 1

        stock_pos = max(0, p["stock"])
        if es_peso:
            val_venta = redondear_al_peso(Decimal(stock_pos) * Decimal(p["precio_final"]) / Decimal(500))
            val_costo = redondear_al_peso(Decimal(stock_pos) * Decimal(p["costo"]) / Decimal(500))
        else:
            val_venta = stock_pos * p["precio_final"]
            val_costo = stock_pos * p["costo"]

        es_bajo = p["stock"] <= p["stock_minimo"]
        if es_bajo:
            stock_bajo += 1
        if p["stock"] <= 0:
            sin_stock += 1

        valor_venta_total += val_venta
        valor_costo_total += val_costo

        items_inv.append({
            **p,
            "valor_venta": val_venta,
            "valor_costo": val_costo,
            "es_stock_bajo": es_bajo,
        })

    ini, fin = _ventana_tiempo(fecha_desde, fecha_hasta, turno_id)
    filas_mov = obtener_conexion().execute(
        """
        SELECT
            m.*,
            p.nombre AS producto_nombre,
            p.codigo_barras AS codigo_barras,
            p.tipo_venta AS tipo_venta
        FROM movimientos_stock m
        JOIN productos p ON p.id = m.producto_id
        WHERE m.fecha >= ? AND m.fecha <= ?
        ORDER BY m.id DESC
        LIMIT 500
        """,
        (ini, fin),
    ).fetchall()
    movimientos = [dict(f) for f in filas_mov]

    return {
        "total_productos": len(items_inv),
        "por_unidad": por_unidad,
        "por_peso": por_peso,
        "stock_bajo": stock_bajo,
        "sin_stock": sin_stock,
        "valor_venta_total": valor_venta_total,
        "valor_costo_total": valor_costo_total,
        "productos": items_inv,
        "movimientos": movimientos,
        "numero_movimientos": len(movimientos),
    }


# =====================================================================
# 3. REPORTES DE DEVOLUCIONES
# =====================================================================
def obtener_reporte_devoluciones(
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    turno_id: int | None = None,
) -> dict:
    """Devuelve resumen, listado y detalle de devoluciones del período o cierre."""
    con = obtener_conexion()
    where_d, params_d = _clausula_filtro("d.", fecha_desde, fecha_hasta, turno_id)

    filas_dev = con.execute(
        f"""
        SELECT
            d.*,
            (SELECT GROUP_CONCAT(vi.nombre, ', ')
             FROM devolucion_items di
             JOIN venta_items vi ON vi.id = di.venta_item_id
             WHERE di.devolucion_id = d.id) AS resumen_productos
        FROM devoluciones d
        WHERE {where_d}
        ORDER BY d.id DESC
        """,
        params_d,
    ).fetchall()

    devoluciones_lista = [dict(f) for f in filas_dev]

    filas_det = con.execute(
        f"""
        SELECT
            di.*,
            d.venta_id,
            d.turno_id,
            d.fecha,
            d.motivo,
            vi.codigo_barras,
            vi.nombre,
            vi.tipo_venta,
            vi.precio_unitario
        FROM devolucion_items di
        JOIN devoluciones d ON d.id = di.devolucion_id
        JOIN venta_items vi ON vi.id = di.venta_item_id
        WHERE {where_d}
        ORDER BY d.id DESC, di.id ASC
        """,
        params_d,
    ).fetchall()

    detalle_lista = [dict(f) for f in filas_det]
    por_dev: dict[int, list[dict]] = {}
    lineas_repuestas = 0
    lineas_no_repuestas = 0
    valor_repuesto = 0
    valor_no_repuesto = 0
    costo_devuelto = 0

    for it in detalle_lista:
        por_dev.setdefault(it["devolucion_id"], []).append(it)
        costo_devuelto += it["costo_valor"]
        if it["repone_stock"]:
            lineas_repuestas += 1
            valor_repuesto += it["valor"]
        else:
            lineas_no_repuestas += 1
            valor_no_repuesto += it["valor"]

    for d in devoluciones_lista:
        d["items"] = por_dev.get(d["id"], [])

    total_devuelto = sum(d["total_devuelto"] for d in devoluciones_lista)

    return {
        "numero_devoluciones": len(devoluciones_lista),
        "total_devuelto": total_devuelto,
        "costo_devuelto": costo_devuelto,
        "total_lineas": len(detalle_lista),
        "lineas_repuestas": lineas_repuestas,
        "lineas_no_repuestas": lineas_no_repuestas,
        "valor_repuesto": valor_repuesto,
        "valor_no_repuesto": valor_no_repuesto,
        "devoluciones": devoluciones_lista,
        "detalle_items": detalle_lista,
    }


# =====================================================================
# 4. REPORTES DE CAJA
# =====================================================================
def obtener_reporte_caja(
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    turno_id: int | None = None,
) -> dict:
    """Devuelve resumen, turnos/cierres y movimientos de caja del período o cierre."""
    con = obtener_conexion()
    if turno_id is not None:
        filas_t = con.execute("SELECT id FROM turnos WHERE id = ?", (turno_id,)).fetchall()
    elif not fecha_desde and not fecha_hasta:
        filas_t = con.execute("SELECT id FROM turnos ORDER BY id DESC LIMIT 200").fetchall()
    else:
        ini, fin = _limites_timestamp(fecha_desde or "", fecha_hasta or "")
        filas_t = con.execute(
            """
            SELECT id FROM turnos
            WHERE (abierto_en >= ? AND abierto_en <= ?)
               OR (cerrado_en IS NOT NULL AND cerrado_en >= ? AND cerrado_en <= ?)
            ORDER BY id DESC
            """,
            (ini, fin, ini, fin),
        ).fetchall()

    turnos_det = []
    movimientos_todos = []
    total_base = 0
    total_v_efec = 0
    total_v_transf = 0
    total_devs_efec = 0
    total_retiros = 0
    diferencia_acum = 0
    cerrados = 0
    abiertos = 0

    for ft in filas_t:
        est = caja.calcular_estado_turno(ft["id"])
        if not est:
            continue
        turnos_det.append(est)
        total_base += est["fondo_inicial"]
        total_v_efec += est["ventas_efectivo"]
        total_v_transf += est["ventas_transferencia"]
        total_devs_efec += est["devoluciones_efectivo"]
        total_retiros += est["retiros_total"]
        if est["abierto"]:
            abiertos += 1
        else:
            cerrados += 1
            diferencia_acum += est["diferencia"] or 0
        for m in est["movimientos"]:
            movimientos_todos.append({**m, "turno_id": est["id"]})

    return {
        "numero_turnos": len(turnos_det),
        "turnos_cerrados": cerrados,
        "turnos_abiertos": abiertos,
        "total_base": total_base,
        "total_ventas_efectivo": total_v_efec,
        "total_ventas_transferencia": total_v_transf,
        "total_devoluciones_efectivo": total_devs_efec,
        "total_retiros": total_retiros,
        "diferencia_acumulada": diferencia_acum,
        "turnos": turnos_det,
        "movimientos": movimientos_todos,
    }


# =====================================================================
# EXPORTACIÓN A EXCEL (.xlsx) — SIN CSV
# =====================================================================
_RELLENO_ENC = PatternFill("solid", fgColor="1E3A8A")
_FUENTE_ENC = Font(bold=True, color="FFFFFF")


def _estilizar_encabezado(hoja, encabezados: list[str]) -> None:
    hoja.append(encabezados)
    for celda in hoja[hoja.max_row]:
        celda.fill = _RELLENO_ENC
        celda.font = _FUENTE_ENC
        celda.alignment = Alignment(horizontal="center")


def _aplicar_anchos(hoja, anchos: list[int]) -> None:
    for col, ancho in enumerate(anchos, start=1):
        hoja.column_dimensions[chr(ord("A") + col - 1)].width = ancho


def _filas_filtro_excel(
    fecha_desde: str | None,
    fecha_hasta: str | None,
    turno_id: int | None,
) -> list[tuple]:
    if turno_id is not None:
        turno = caja.obtener_turno(turno_id)
        return [
            ("Filtro", f"Cierre / Turno #{turno_id}"),
            ("Apertura del turno", formatear_fecha_hora_dmy(turno["abierto_en"]) if turno else ""),
            (
                "Cierre del turno",
                (formatear_fecha_hora_dmy(turno["cerrado_en"]) if turno["cerrado_en"] else "Turno abierto")
                if turno
                else "",
            ),
        ]
    if not fecha_desde and not fecha_hasta:
        return [("Período", "Todos los registros")]
    return [
        ("Fecha inicial", formatear_fecha_dmy(fecha_desde)),
        ("Fecha final", formatear_fecha_dmy(fecha_hasta)),
    ]


def _escribir_hojas_ventas(
    libro: Workbook,
    hoja_resumen,
    fecha_desde: str | None,
    fecha_hasta: str | None,
    turno_id: int | None,
) -> None:
    res = obtener_resumen(fecha_desde, fecha_hasta, turno_id=turno_id)
    lista_ventas = listar_ventas_periodo(fecha_desde, fecha_hasta, turno_id=turno_id)
    ranking = productos_mas_vendidos(fecha_desde, fecha_hasta, limite=500, turno_id=turno_id)
    mapa_medios = dict(ventas.MEDIOS_PAGO)

    _estilizar_encabezado(hoja_resumen, ["Indicador", "Valor"])
    filas_resumen = _filas_filtro_excel(fecha_desde, fecha_hasta, turno_id) + [
        ("Generado el", datetime.now().strftime("%d-%m-%Y %H:%M:%S")),
        ("Número de ventas", res["numero_ventas"]),
        ("Total vendido (bruto)", res["total_bruto"]),
        ("Número de devoluciones", res["numero_devoluciones"]),
        ("Total devoluciones (efectivo)", res["total_devoluciones"]),
        ("Venta neta (ventas - devoluciones)", res["venta_neta"]),
        ("Ticket promedio", res["ticket_promedio"]),
        ("Ventas en Efectivo", res["ventas_efectivo"]),
        ("Efectivo neto (efectivo - devoluciones)", res["efectivo_neto"]),
        ("Ventas por Transferencia", res["ventas_transferencia"]),
        ("Costo neto de lo vendido", res["costo_neto"]),
        ("IVA neto incluido", res["iva_neto"]),
        ("Ganancia estimada (sin IVA - costo)", res["ganancia_estimada"]),
    ]
    for nombre, valor in filas_resumen:
        hoja_resumen.append([nombre, valor])
        if isinstance(valor, int) and nombre not in ("Número de ventas", "Número de devoluciones"):
            hoja_resumen.cell(row=hoja_resumen.max_row, column=2).number_format = "#,##0"
    _aplicar_anchos(hoja_resumen, [40, 24])

    h_ven = libro.create_sheet("Ventas")
    _estilizar_encabezado(
        h_ven,
        ["# Venta", "Fecha y hora", "Medio de pago", "Total", "IVA", "Costo", "Ganancia est.", "Devuelto", "Productos"],
    )
    for v in lista_ventas:
        h_ven.append([
            v["id"],
            formatear_fecha_hora_dmy(v["fecha"]),
            mapa_medios.get(v["medio_pago"], v["medio_pago"]),
            v["total"],
            v["total_iva"],
            v["total_costo"],
            v["ganancia_venta"],
            v["devuelto_de_esta_venta"],
            v["resumen_productos"] or "",
        ])
    _aplicar_anchos(h_ven, [10, 22, 16, 14, 12, 14, 14, 14, 45])

    h_prod = libro.create_sheet("Productos más vendidos")
    _estilizar_encabezado(
        h_prod,
        ["Código", "Producto", "Tipo", "Cantidad neta", "Total vendido", "Devuelto", "Venta neta", "Costo neto", "Ganancia est."],
    )
    for p in ranking:
        h_prod.append([
            p["codigo_barras"] or "",
            p["nombre"],
            p["tipo_venta"],
            inventario.formatear_stock(p["tipo_venta"], p["cantidad_neta"]),
            p["total_vendido"],
            p["valor_devuelto"],
            p["venta_neta"],
            p["costo_neto"],
            p["ganancia_estimada"],
        ])
    _aplicar_anchos(h_prod, [16, 30, 12, 18, 15, 14, 15, 15, 15])


def _escribir_hojas_inventario(
    libro: Workbook,
    hoja_resumen,
    fecha_desde: str | None,
    fecha_hasta: str | None,
    turno_id: int | None,
    incluir_resumen: bool = True,
) -> None:
    rep = obtener_reporte_inventario(fecha_desde, fecha_hasta, turno_id=turno_id)

    if incluir_resumen and hoja_resumen is not None:
        _estilizar_encabezado(hoja_resumen, ["Indicador", "Valor"])
        filas_res = _filas_filtro_excel(fecha_desde, fecha_hasta, turno_id) + [
            ("Generado el", datetime.now().strftime("%d-%m-%Y %H:%M:%S")),
            ("Productos activos", rep["total_productos"]),
            ("Productos por unidad", rep["por_unidad"]),
            ("Productos por peso", rep["por_peso"]),
            ("Productos con stock bajo", rep["stock_bajo"]),
            ("Productos sin stock (<= 0)", rep["sin_stock"]),
            ("Valor inventario (precio venta)", rep["valor_venta_total"]),
            ("Valor inventario (al costo)", rep["valor_costo_total"]),
            ("Movimientos de stock en el filtro", rep["numero_movimientos"]),
        ]
        for nombre, valor in filas_res:
            hoja_resumen.append([nombre, valor])
            if isinstance(valor, int) and "Valor inventario" in nombre:
                hoja_resumen.cell(row=hoja_resumen.max_row, column=2).number_format = "#,##0"
        _aplicar_anchos(hoja_resumen, [40, 24])

    h_inv = libro.create_sheet("Inventario")
    _estilizar_encabezado(
        h_inv,
        ["Código", "Producto", "Categoría", "Tipo", "Stock actual", "Stock mínimo", "Estado", "Costo", "Precio venta", "Valor costo", "Valor venta"],
    )
    for p in rep["productos"]:
        h_inv.append([
            p["codigo_barras"] or "",
            p["nombre"],
            p["categoria"] or "",
            "Peso (lb)" if p["tipo_venta"] == "peso" else "Unidad",
            inventario.formatear_stock(p["tipo_venta"], p["stock"]),
            inventario.formatear_stock(p["tipo_venta"], p["stock_minimo"]),
            "STOCK BAJO" if p["es_stock_bajo"] else "OK",
            p["costo"],
            p["precio_final"],
            p["valor_costo"],
            p["valor_venta"],
        ])
    _aplicar_anchos(h_inv, [16, 30, 18, 12, 18, 16, 14, 14, 14, 15, 15])

    h_mov = libro.create_sheet("Movimientos Stock")
    _estilizar_encabezado(
        h_mov,
        ["# Mov.", "Fecha y hora", "Código", "Producto", "Tipo", "Cantidad", "Stock ant.", "Stock nuevo", "Motivo"],
    )
    for m in rep["movimientos"]:
        signo = "+" if m["cantidad"] > 0 else ""
        cant_fmt = f"{signo}{inventario.formatear_stock(m['tipo_venta'], m['cantidad'])}"
        h_mov.append([
            m["id"],
            formatear_fecha_hora_dmy(m["fecha"]),
            m["codigo_barras"] or "",
            m["producto_nombre"],
            (m["tipo"] or "").upper(),
            cant_fmt,
            inventario.formatear_stock(m["tipo_venta"], m["stock_anterior"]),
            inventario.formatear_stock(m["tipo_venta"], m["stock_nuevo"]),
            m["motivo"] or "",
        ])
    _aplicar_anchos(h_mov, [10, 22, 16, 28, 14, 18, 16, 16, 36])


def _escribir_hojas_devoluciones(
    libro: Workbook,
    hoja_resumen,
    fecha_desde: str | None,
    fecha_hasta: str | None,
    turno_id: int | None,
    incluir_resumen: bool = True,
) -> None:
    rep = obtener_reporte_devoluciones(fecha_desde, fecha_hasta, turno_id=turno_id)

    if incluir_resumen and hoja_resumen is not None:
        _estilizar_encabezado(hoja_resumen, ["Indicador", "Valor"])
        filas_res = _filas_filtro_excel(fecha_desde, fecha_hasta, turno_id) + [
            ("Generado el", datetime.now().strftime("%d-%m-%Y %H:%M:%S")),
            ("Número de devoluciones", rep["numero_devoluciones"]),
            ("Total devuelto", rep["total_devuelto"]),
            ("Costo devuelto", rep["costo_devuelto"]),
            ("Líneas de productos devueltos", rep["total_lineas"]),
            ("Líneas repuestas al stock", rep["lineas_repuestas"]),
            ("Líneas NO repuestas (dañado/merma)", rep["lineas_no_repuestas"]),
        ]
        for nombre, valor in filas_res:
            hoja_resumen.append([nombre, valor])
            if isinstance(valor, int) and nombre in ("Total devuelto", "Costo devuelto"):
                hoja_resumen.cell(row=hoja_resumen.max_row, column=2).number_format = "#,##0"
        _aplicar_anchos(hoja_resumen, [40, 24])

    # Hoja de Devoluciones con fecha Y HORA completa (dd-mm-aaaa HH:MM:SS)
    h_dev = libro.create_sheet("Devoluciones")
    _estilizar_encabezado(
        h_dev,
        ["# Dev.", "# Venta", "Fecha y hora", "Turno", "Motivo", "Total devuelto", "Productos"],
    )
    for d in rep["devoluciones"]:
        h_dev.append([
            d["id"],
            d["venta_id"],
            formatear_fecha_hora_dmy(d["fecha"]),
            f"#{d['turno_id']}" if d["turno_id"] else "",
            d["motivo"],
            d["total_devuelto"],
            d["resumen_productos"] or "",
        ])
    _aplicar_anchos(h_dev, [10, 10, 22, 10, 30, 16, 40])

    h_det = libro.create_sheet("Detalle Devoluciones")
    _estilizar_encabezado(
        h_det,
        ["# Dev.", "# Venta", "Fecha y hora", "Código", "Producto", "Tipo", "Cantidad devuelta", "Valor devuelto", "Costo devuelto", "Repone stock"],
    )
    for it in rep["detalle_items"]:
        h_det.append([
            it["devolucion_id"],
            it["venta_id"],
            formatear_fecha_hora_dmy(it["fecha"]),
            it["codigo_barras"] or "",
            it["nombre"],
            "Peso (lb)" if it["tipo_venta"] == "peso" else "Unidad",
            inventario.formatear_stock(it["tipo_venta"], it["cantidad"]),
            it["valor"],
            it["costo_valor"],
            "Sí" if it["repone_stock"] else "No",
        ])
    _aplicar_anchos(h_det, [10, 10, 22, 16, 28, 12, 18, 16, 16, 14])


def _escribir_hojas_caja(
    libro: Workbook,
    hoja_resumen,
    fecha_desde: str | None,
    fecha_hasta: str | None,
    turno_id: int | None,
    incluir_resumen: bool = True,
) -> None:
    rep = obtener_reporte_caja(fecha_desde, fecha_hasta, turno_id=turno_id)

    if incluir_resumen and hoja_resumen is not None:
        _estilizar_encabezado(hoja_resumen, ["Indicador", "Valor"])
        filas_res = _filas_filtro_excel(fecha_desde, fecha_hasta, turno_id) + [
            ("Generado el", datetime.now().strftime("%d-%m-%Y %H:%M:%S")),
            ("Turnos en el reporte", rep["numero_turnos"]),
            ("Turnos cerrados", rep["turnos_cerrados"]),
            ("Turnos abiertos", rep["turnos_abiertos"]),
            ("Total base inicial", rep["total_base"]),
            ("Ventas en efectivo", rep["total_ventas_efectivo"]),
            ("Ventas por transferencia", rep["total_ventas_transferencia"]),
            ("Devoluciones en efectivo", rep["total_devoluciones_efectivo"]),
            ("Total retiros y gastos", rep["total_retiros"]),
            ("Diferencia acumulada (cierres)", rep["diferencia_acumulada"]),
        ]
        for nombre, valor in filas_res:
            hoja_resumen.append([nombre, valor])
            if isinstance(valor, int) and nombre not in ("Turnos en el reporte", "Turnos cerrados", "Turnos abiertos"):
                hoja_resumen.cell(row=hoja_resumen.max_row, column=2).number_format = "#,##0"
        _aplicar_anchos(hoja_resumen, [40, 24])

    h_caja = libro.create_sheet("Caja y Cierres")
    _estilizar_encabezado(
        h_caja,
        [
            "# Turno",
            "Estado",
            "Apertura (Fecha y hora)",
            "Cierre (Fecha y hora)",
            "Base",
            "Ventas Efec.",
            "Ventas Transf.",
            "Devoluciones",
            "Retiros/Gastos",
            "Efectivo en caja",
            "Efectivo contado",
            "Diferencia",
            "Notas",
        ],
    )
    for t in rep["turnos"]:
        h_caja.append([
            t["id"],
            "Abierto" if t["abierto"] else "Cerrado",
            formatear_fecha_hora_dmy(t["abierto_en"]),
            formatear_fecha_hora_dmy(t["cerrado_en"]) if t["cerrado_en"] else "Abierto",
            t["fondo_inicial"],
            t["ventas_efectivo"],
            t["ventas_transferencia"],
            t["devoluciones_efectivo"],
            t["retiros_total"],
            t["efectivo_esperado"],
            t["efectivo_contado"] if t["efectivo_contado"] is not None else "",
            t["diferencia"] if t["diferencia"] is not None else "",
            t["notas"] or "",
        ])
    _aplicar_anchos(h_caja, [10, 12, 22, 22, 14, 14, 14, 14, 14, 16, 16, 14, 30])

    h_mov = libro.create_sheet("Retiros y Gastos")
    _estilizar_encabezado(h_mov, ["# Turno", "Fecha y hora", "Tipo", "Motivo", "Monto"])
    for m in rep["movimientos"]:
        h_mov.append([
            m["turno_id"],
            formatear_fecha_hora_dmy(m["fecha"]),
            "GASTO" if m["tipo"] == "gasto" else "RETIRO",
            m["motivo"],
            m["monto"],
        ])
    _aplicar_anchos(h_mov, [10, 22, 12, 36, 14])


def exportar_reporte_excel(
    ruta,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    turno_id: int | None = None,
    modulo: str = "ventas",
) -> None:
    """
    Exporta a Excel (.xlsx) según `modulo`:
      - 'ventas': Resumen, Ventas, Productos más vendidos
      - 'inventario': Resumen Inventario, Inventario, Movimientos Stock
      - 'devoluciones': Resumen Devoluciones, Devoluciones (con hora), Detalle Devoluciones (con hora)
      - 'caja': Resumen Caja, Caja y Cierres (con hora), Retiros y Gastos (con hora)
      - 'todo': Libro completo con las hojas de los 4 submódulos
    """
    libro = Workbook()
    hoja_inicial = libro.active

    if modulo == "inventario":
        hoja_inicial.title = "Resumen Inventario"
        _escribir_hojas_inventario(libro, hoja_inicial, fecha_desde, fecha_hasta, turno_id, incluir_resumen=True)
    elif modulo == "devoluciones":
        hoja_inicial.title = "Resumen Devoluciones"
        _escribir_hojas_devoluciones(libro, hoja_inicial, fecha_desde, fecha_hasta, turno_id, incluir_resumen=True)
    elif modulo == "caja":
        hoja_inicial.title = "Resumen Caja"
        _escribir_hojas_caja(libro, hoja_inicial, fecha_desde, fecha_hasta, turno_id, incluir_resumen=True)
    elif modulo == "todo":
        hoja_inicial.title = "Resumen Ventas"
        _escribir_hojas_ventas(libro, hoja_inicial, fecha_desde, fecha_hasta, turno_id)
        _escribir_hojas_inventario(libro, None, fecha_desde, fecha_hasta, turno_id, incluir_resumen=False)
        _escribir_hojas_devoluciones(libro, None, fecha_desde, fecha_hasta, turno_id, incluir_resumen=False)
        _escribir_hojas_caja(libro, None, fecha_desde, fecha_hasta, turno_id, incluir_resumen=False)
    else:
        hoja_inicial.title = "Resumen"
        _escribir_hojas_ventas(libro, hoja_inicial, fecha_desde, fecha_hasta, turno_id)

    libro.save(ruta)
