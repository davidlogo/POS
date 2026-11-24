"""
Módulo de Caja y Cierre de turno (Fase 7).

Reglas:
  * Solo puede haber UN turno abierto a la vez (`cerrado_en IS NULL`).
  * Desde la Fase 7 es obligatorio tener un turno abierto para cobrar ventas.
  * Durante el turno abierto se pueden registrar retiros y gastos de caja con motivo
    (salen en efectivo del cajón).
  * Fórmulas del cierre de caja (todo en pesos enteros):
      efectivo_esperado = fondo_inicial
                        + ventas_efectivo
                        - devoluciones_efectivo
                        - retiros_total
      diferencia        = efectivo_contado - efectivo_esperado
        * diferencia == 0 -> Cuadre exacto
        * diferencia >  0 -> Sobrante (+)
        * diferencia <  0 -> Faltante (−)
"""

from database.conexion import ahora, obtener_conexion, transaccion

TIPOS_MOVIMIENTO_CAJA = (
    ("gasto", "Gasto de tienda (pago proveedor, insumos, etc.)"),
    ("retiro", "Retiro de efectivo de caja"),
)


class ErrorCaja(Exception):
    """Error de validación en operaciones de caja."""


def obtener_turno_abierto() -> dict | None:
    """Devuelve el turno actualmente abierto (o None si la caja está cerrada)."""
    fila = obtener_conexion().execute(
        "SELECT * FROM turnos WHERE cerrado_en IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(fila) if fila else None


def hay_turno_abierto() -> bool:
    return obtener_turno_abierto() is not None


def abrir_turno(fondo_inicial: int) -> int:
    """
    Abre un nuevo turno de caja con `fondo_inicial` (entero >= 0).
    Devuelve el id del turno creado.
    """
    if not isinstance(fondo_inicial, int) or fondo_inicial < 0:
        raise ErrorCaja("El fondo inicial debe ser un monto en pesos mayor o igual a $ 0.")
    if hay_turno_abierto():
        raise ErrorCaja("Ya hay un turno de caja abierto.")

    with transaccion() as con:
        turno_id = con.execute(
            "INSERT INTO turnos (abierto_en, fondo_inicial) VALUES (?, ?)",
            (ahora(), fondo_inicial),
        ).lastrowid
    return turno_id


def registrar_movimiento_caja(tipo: str, monto: int, motivo: str) -> int:
    """
    Registra un retiro o gasto de caja en el turno abierto actual.
    Devuelve el id del movimiento.
    """
    if tipo not in dict(TIPOS_MOVIMIENTO_CAJA):
        raise ErrorCaja("El tipo debe ser 'retiro' o 'gasto'.")
    if not isinstance(monto, int) or monto <= 0:
        raise ErrorCaja("El monto debe ser mayor que $ 0.")
    motivo = (motivo or "").strip().upper()
    if not motivo:
        raise ErrorCaja("El motivo es obligatorio.")

    turno = obtener_turno_abierto()
    if turno is None:
        raise ErrorCaja("Debe abrir un turno de caja antes de registrar retiros o gastos.")

    with transaccion() as con:
        mov_id = con.execute(
            """INSERT INTO movimientos_caja (turno_id, fecha, tipo, monto, motivo)
               VALUES (?, ?, ?, ?, ?)""",
            (turno["id"], ahora(), tipo, monto, motivo),
        ).lastrowid
    return mov_id


def listar_movimientos_turno(turno_id: int) -> list[dict]:
    """Lista los retiros y gastos registrados en un turno."""
    filas = obtener_conexion().execute(
        "SELECT * FROM movimientos_caja WHERE turno_id = ? ORDER BY id DESC",
        (turno_id,),
    ).fetchall()
    return [dict(f) for f in filas]


def calcular_estado_turno(turno_id: int | None = None) -> dict | None:
    """
    Calcula en vivo todos los totales de un turno (abierto o cerrado):
      - fondo_inicial
      - ventas_efectivo, ventas_tarjeta, ventas_transferencia, ventas_total, numero_ventas
      - devoluciones_efectivo, devoluciones_total, numero_devoluciones
      - retiros_total, movimientos (lista de retiros/gastos)
      - efectivo_esperado
    Si el turno ya está cerrado, incluye también `efectivo_contado`, `diferencia` y `notas`.
    """
    con = obtener_conexion()
    if turno_id is None:
        fila_t = con.execute(
            "SELECT * FROM turnos WHERE cerrado_en IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
    else:
        fila_t = con.execute("SELECT * FROM turnos WHERE id = ?", (turno_id,)).fetchone()

    if fila_t is None:
        return None

    t = dict(fila_t)
    tid = t["id"]

    # Ventas asociadas al turno
    fv = con.execute(
        """
        SELECT
            COUNT(*) AS numero_ventas,
            COALESCE(SUM(total), 0) AS ventas_total,
            COALESCE(SUM(CASE WHEN medio_pago = 'efectivo' THEN total ELSE 0 END), 0) AS ventas_efectivo,
            COALESCE(SUM(CASE WHEN medio_pago = 'tarjeta' THEN total ELSE 0 END), 0) AS ventas_tarjeta,
            COALESCE(SUM(CASE WHEN medio_pago = 'transferencia' THEN total ELSE 0 END), 0) AS ventas_transferencia
        FROM ventas
        WHERE turno_id = ?
        """,
        (tid,),
    ).fetchone()

    # Devoluciones registradas durante este turno (todas salen en efectivo)
    fd = con.execute(
        """
        SELECT
            COUNT(*) AS numero_devoluciones,
            COALESCE(SUM(total_devuelto), 0) AS devoluciones_total,
            COALESCE(SUM(CASE WHEN medio_reembolso = 'efectivo' THEN total_devuelto ELSE 0 END), 0)
                AS devoluciones_efectivo
        FROM devoluciones
        WHERE turno_id = ?
        """,
        (tid,),
    ).fetchone()

    # Retiros y gastos de este turno
    movs = listar_movimientos_turno(tid)
    retiros_total = sum(m["monto"] for m in movs)

    fondo = t["fondo_inicial"]
    v_efec = fv["ventas_efectivo"]
    v_tarj = fv["ventas_tarjeta"]
    v_tran = fv["ventas_transferencia"]
    d_efec = fd["devoluciones_efectivo"]
    d_tot = fd["devoluciones_total"]

    efectivo_esperado = fondo + v_efec - d_efec - retiros_total

    return {
        "id": tid,
        "abierto_en": t["abierto_en"],
        "cerrado_en": t["cerrado_en"],
        "abierto": t["cerrado_en"] is None,
        "fondo_inicial": fondo,
        "numero_ventas": fv["numero_ventas"],
        "ventas_total": fv["ventas_total"],
        "ventas_efectivo": v_efec,
        "ventas_tarjeta": v_tarj,
        "ventas_transferencia": v_tran,
        "numero_devoluciones": fd["numero_devoluciones"],
        "devoluciones_efectivo": d_efec,
        "devoluciones_total": d_tot,
        "retiros_total": retiros_total,
        "movimientos": movs,
        "efectivo_esperado": efectivo_esperado,
        "efectivo_contado": t["efectivo_contado"],
        "diferencia": t["diferencia"],
        "notas": t["notas"],
    }


def cerrar_turno(efectivo_contado: int, notas: str = "") -> dict:
    """
    Cierra el turno abierto actual guardando la foto de todos los totales,
    el efectivo contado y la diferencia (+ sobrante / - faltante / 0 exacto).
    Devuelve el diccionario con el resumen del cierre.
    """
    if not isinstance(efectivo_contado, int) or efectivo_contado < 0:
        raise ErrorCaja("El efectivo contado debe ser un monto en pesos mayor o igual a $ 0.")

    estado = calcular_estado_turno()
    if estado is None or not estado["abierto"]:
        raise ErrorCaja("No hay ningún turno abierto para cerrar.")

    diferencia = efectivo_contado - estado["efectivo_esperado"]
    momento = ahora()
    notas_limpias = (notas or "").strip().upper() or None

    with transaccion() as con:
        con.execute(
            """UPDATE turnos SET
                 cerrado_en = ?,
                 ventas_efectivo = ?,
                 ventas_tarjeta = ?,
                 ventas_transferencia = ?,
                 devoluciones_efectivo = ?,
                 devoluciones_total = ?,
                 retiros_total = ?,
                 efectivo_esperado = ?,
                 efectivo_contado = ?,
                 diferencia = ?,
                 notas = ?
               WHERE id = ?""",
            (
                momento,
                estado["ventas_efectivo"],
                estado["ventas_tarjeta"],
                estado["ventas_transferencia"],
                estado["devoluciones_efectivo"],
                estado["devoluciones_total"],
                estado["retiros_total"],
                estado["efectivo_esperado"],
                efectivo_contado,
                diferencia,
                notas_limpias,
                estado["id"],
            ),
        )

    return calcular_estado_turno(estado["id"])


def listar_cierres(limite: int = 100) -> list[dict]:
    """Devuelve el historial de turnos ya cerrados (del más reciente al más antiguo)."""
    filas = obtener_conexion().execute(
        "SELECT * FROM turnos WHERE cerrado_en IS NOT NULL ORDER BY id DESC LIMIT ?",
        (limite,),
    ).fetchall()
    return [dict(f) for f in filas]


def listar_turnos(limite: int = 200) -> list[dict]:
    """Devuelve todos los turnos (abiertos y cerrados), del más reciente al más antiguo."""
    filas = obtener_conexion().execute(
        "SELECT * FROM turnos ORDER BY id DESC LIMIT ?",
        (limite,),
    ).fetchall()
    return [dict(f) for f in filas]


def obtener_turno(turno_id: int) -> dict | None:
    """Devuelve los datos básicos de un turno por su id."""
    fila = obtener_conexion().execute(
        "SELECT * FROM turnos WHERE id = ?",
        (turno_id,),
    ).fetchone()
    return dict(fila) if fila else None
