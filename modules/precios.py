"""
Cálculo de precios, redondeo por producto, precio manual y cambios masivos.

Fórmula aprobada:
    precio_sin_redondear = costo × (1 + ganancia%) × (1 + IVA%)
    precio_calculado     = redondear(precio_sin_redondear, multiplo_producto, modo_producto)
    precio_final         = precio_manual (si existe) o precio_calculado

Opciones de redondeo por producto:
  - Múltiplo: 1 (sin redondear, deja el valor tal cual al peso), 50, 100.
  - Modo:
      * 'arriba' -> redondea hacia arriba al siguiente múltiplo (ej. 3.001 -> 3.050)
      * 'abajo'  -> redondea hacia abajo al múltiplo anterior  (ej. 3.049 -> 3.000)
"""

from decimal import Decimal, ROUND_HALF_UP

from database.conexion import ahora, obtener_conexion, transaccion
from utils.porcentajes import a_decimal

MULTIPLOS_REDONDEO = (
    (1, "Sin redondear (dejar valor tal cual)"),
    (50, "Múltiplo de $ 50"),
    (100, "Múltiplo de $ 100"),
)

MODOS_REDONDEO = (
    ("arriba", "Redondear hacia arriba"),
    ("abajo", "Redondear hacia abajo"),
)


def redondear_al_peso(valor: Decimal) -> int:
    """Redondea un Decimal al peso entero más cercano (0,5 sube)."""
    return int(valor.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def aplicar_redondeo(valor_pesos: int, multiplo: int = 1, modo: str = "arriba") -> int:
    """
    Aplica la regla de redondeo a un valor entero en pesos.
    Si `multiplo` <= 1, devuelve el valor tal cual.
    """
    valor_pesos = int(valor_pesos)
    multiplo = int(multiplo or 1)
    if multiplo <= 1 or valor_pesos <= 0:
        return valor_pesos

    resto = valor_pesos % multiplo
    if resto == 0:
        return valor_pesos

    if modo == "abajo":
        return valor_pesos - resto
    # Por defecto 'arriba'
    return valor_pesos + (multiplo - resto)


def calcular_ganancia_desde_precio(costo: int, precio_venta: int) -> int:
    """
    Calcula el % de ganancia en centésimas de punto (ej. 25 % -> 2500)
    a partir del costo y el precio de venta (para productos por peso).
    Si costo <= 0 o precio_venta <= costo, devuelve 0.
    """
    costo = int(costo or 0)
    precio_venta = int(precio_venta or 0)
    if costo <= 0 or precio_venta <= costo:
        return 0
    # ((precio - costo) / costo) * 100 * 100 (centésimas)
    centesimas = (Decimal(precio_venta - costo) * Decimal(10_000)) / Decimal(costo)
    return int(centesimas.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calcular_precio_base(costo: int, ganancia_pct: int, iva_pct: int) -> int:
    """Precio exacto de la fórmula redondeado al peso (sin múltiplo de 50/100)."""
    valor = Decimal(int(costo)) * (1 + a_decimal(ganancia_pct)) * (1 + a_decimal(iva_pct))
    return redondear_al_peso(valor)


def calcular_precio(
    costo: int,
    ganancia_pct: int,
    iva_pct: int,
    multiplo: int = 1,
    modo: str = "arriba",
) -> int:
    """
    Calcula el precio final de fórmula aplicando el redondeo propio del producto.
    """
    base = calcular_precio_base(costo, ganancia_pct, iva_pct)
    return aplicar_redondeo(base, multiplo, modo)


# ---------------------------------------------------------------------
# Edición individual de costos, redondeo y precios por producto
# ---------------------------------------------------------------------
def actualizar_precios_producto(
    producto_id: int,
    costo: int,
    ganancia_pct: int,
    iva_pct: int,
    precio_manual: int | None,
    redondeo_multiplo: int = 1,
    redondeo_modo: str = "arriba",
) -> dict:
    """
    Actualiza costo, % ganancia, % IVA, redondeo individual y precio manual
    (None = usar cálculo) de un producto, recalculando `precio_calculado` y `precio_final`.
    Devuelve los nuevos precios.
    """
    if costo < 0 or ganancia_pct < 0 or iva_pct < 0:
        raise ValueError("Costo, ganancia e IVA deben ser mayores o iguales a 0.")
    if precio_manual is not None and precio_manual < 0:
        raise ValueError("El precio manual no puede ser negativo.")
    redondeo_multiplo = int(redondeo_multiplo or 1)
    if redondeo_multiplo not in (1, 50, 100):
        redondeo_multiplo = 1
    if redondeo_modo not in ("arriba", "abajo"):
        redondeo_modo = "arriba"

    calculado = calcular_precio(costo, ganancia_pct, iva_pct, redondeo_multiplo, redondeo_modo)
    final = precio_manual if precio_manual is not None else calculado

    with transaccion() as con:
        con.execute(
            """UPDATE productos SET
                 costo = ?,
                 ganancia_pct = ?,
                 iva_pct = ?,
                 redondeo_multiplo = ?,
                 redondeo_modo = ?,
                 precio_calculado = ?,
                 precio_manual = ?,
                 precio_final = ?,
                 actualizado_en = ?
               WHERE id = ?""",
            (
                costo,
                ganancia_pct,
                iva_pct,
                redondeo_multiplo,
                redondeo_modo,
                calculado,
                precio_manual,
                final,
                ahora(),
                producto_id,
            ),
        )
    return {"precio_calculado": calculado, "precio_manual": precio_manual, "precio_final": final}


# ---------------------------------------------------------------------
# Cambio masivo con vista previa (respeta el redondeo de cada producto)
# ---------------------------------------------------------------------
def previsualizar_cambio_masivo(
    producto_ids: list[int],
    nueva_ganancia_pct: int | None = None,
    nuevo_iva_pct: int | None = None,
    aplicar_a_manuales: bool = False,
) -> list[dict]:
    """
    Calcula cómo quedarían los productos indicados sin guardar nada en la base.
    Usa el `redondeo_multiplo` y `redondeo_modo` propios de cada producto.
    """
    if not producto_ids:
        return []
    con = obtener_conexion()
    marcas = ",".join("?" for _ in producto_ids)
    filas = con.execute(
        f"""SELECT p.*, c.nombre AS categoria
            FROM productos p
            LEFT JOIN categorias c ON c.id = p.categoria_id
            WHERE p.id IN ({marcas})
            ORDER BY p.nombre COLLATE NOCASE""",
        producto_ids,
    ).fetchall()

    resultado = []
    for f in filas:
        es_peso = f["tipo_venta"] == "peso"
        tenia_manual = (f["precio_manual"] is not None) or es_peso
        # Los productos por peso tienen IVA y ganancia bloqueados (precio manual fijo por libra)
        omitido = es_peso or (tenia_manual and not aplicar_a_manuales)

        gan_nueva = f["ganancia_pct"] if (nueva_ganancia_pct is None or omitido) else nueva_ganancia_pct
        iva_nuevo = f["iva_pct"] if (nuevo_iva_pct is None or omitido) else nuevo_iva_pct
        mult = f["redondeo_multiplo"] if "redondeo_multiplo" in f.keys() else 1
        modo = f["redondeo_modo"] if "redondeo_modo" in f.keys() else "arriba"
        calc_nuevo = calcular_precio(f["costo"], gan_nueva, iva_nuevo, mult, modo)

        if omitido:
            manual_nuevo = f["precio_manual"]
            final_nuevo = f["precio_final"]
        else:
            manual_nuevo = None
            final_nuevo = calc_nuevo

        resultado.append({
            "id": f["id"],
            "codigo_barras": f["codigo_barras"],
            "nombre": f["nombre"],
            "categoria": f["categoria"],
            "tipo_venta": f["tipo_venta"],
            "costo": f["costo"],
            "tenia_manual": tenia_manual,
            "omitido_por_manual": omitido,
            "ganancia_anterior": f["ganancia_pct"],
            "ganancia_nueva": gan_nueva,
            "iva_anterior": f["iva_pct"],
            "iva_nuevo": iva_nuevo,
            "precio_anterior": f["precio_final"],
            "precio_calculado_nuevo": calc_nuevo,
            "precio_manual_nuevo": manual_nuevo,
            "precio_nuevo": final_nuevo,
            "cambia": (
                not omitido
                and (
                    gan_nueva != f["ganancia_pct"]
                    or iva_nuevo != f["iva_pct"]
                    or final_nuevo != f["precio_final"]
                    or tenia_manual
                )
            ),
        })
    return resultado


def aplicar_cambio_masivo(
    producto_ids: list[int],
    nueva_ganancia_pct: int | None = None,
    nuevo_iva_pct: int | None = None,
    aplicar_a_manuales: bool = False,
) -> dict:
    """
    Aplica el cambio masivo en una sola transacción.
    Devuelve {'actualizados': N, 'omitidos_manual': M, 'sin_cambios': K}.
    """
    vista = previsualizar_cambio_masivo(
        producto_ids,
        nueva_ganancia_pct=nueva_ganancia_pct,
        nuevo_iva_pct=nuevo_iva_pct,
        aplicar_a_manuales=aplicar_a_manuales,
    )
    conteo = {"actualizados": 0, "omitidos_manual": 0, "sin_cambios": 0}
    momento = ahora()
    with transaccion() as con:
        for item in vista:
            if item["omitido_por_manual"]:
                conteo["omitidos_manual"] += 1
                continue
            if not item["cambia"]:
                conteo["sin_cambios"] += 1
                continue
            con.execute(
                """UPDATE productos SET
                     ganancia_pct = ?,
                     iva_pct = ?,
                     precio_calculado = ?,
                     precio_manual = ?,
                     precio_final = ?,
                     actualizado_en = ?
                   WHERE id = ?""",
                (
                    item["ganancia_nueva"],
                    item["iva_nuevo"],
                    item["precio_calculado_nuevo"],
                    item["precio_manual_nuevo"],
                    item["precio_nuevo"],
                    momento,
                    item["id"],
                ),
            )
            conteo["actualizados"] += 1
    return conteo
