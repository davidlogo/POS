"""
Módulo de Ventas (Fase 4).

Reglas clave:
  * Todo el dinero es ENTERO en pesos (sin decimales).
  * Productos por unidad: cantidad en unidades enteras (> 0).
  * Productos por peso:   cantidad en GRAMOS enteros (> 0); el precio y el costo
    del producto están definidos por LIBRA (500 g).
    El subtotal proporcional se calcula al peso exacto (sin redondeo a múltiplos):
        subtotal = redondear_al_peso(precio_por_libra × gramos / 500)
  * En `venta_items` se guarda la "foto" del producto al momento de la venta
    (nombre, código, tipo_venta, precio_unitario, costo_unitario, iva_pct,
    subtotal, iva_valor, costo_total). Así los cambios futuros de precio o costo
    NUNCA alteran ventas ni reportes pasados.
  * Toda venta y su descuento de stock se ejecutan en UNA sola transacción
    ("todo o nada").
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from database.conexion import ahora, obtener_conexion, transaccion
from hardware.cajon import abrir_cajon
from modules import ajustes, inventario
from modules.precios import redondear_al_peso
from utils.peso import GRAMOS_POR_LIBRA, formatear_peso
from utils.porcentajes import a_decimal

MEDIOS_PAGO = (
    ("efectivo", "Efectivo"),
    ("transferencia", "Transferencia"),
)


class ErrorVenta(Exception):
    """Error de validación al intentar cobrar una venta."""


def calcular_linea(
    tipo_venta: str,
    cantidad: int,
    precio_unitario: int,
    costo_unitario: int,
    iva_pct: int,
) -> dict:
    """
    Calcula subtotal, costo_total e iva_valor (IVA contenido en el subtotal)
    de una línea de carrito.
    """
    cantidad = int(cantidad)
    precio_unitario = int(precio_unitario)
    costo_unitario = int(costo_unitario)
    iva_pct = int(iva_pct)

    if cantidad < 0:
        raise ValueError("La cantidad no puede ser negativa.")
    if cantidad == 0:
        return {"subtotal": 0, "costo_total": 0, "iva_valor": 0}

    if tipo_venta == "peso":
        factor = Decimal(cantidad) / Decimal(GRAMOS_POR_LIBRA)
        subtotal = redondear_al_peso(Decimal(precio_unitario) * factor)
        costo_total = redondear_al_peso(Decimal(costo_unitario) * factor)
    else:
        subtotal = precio_unitario * cantidad
        costo_total = costo_unitario * cantidad

    # IVA contenido en el subtotal cobrado: subtotal - subtotal / (1 + IVA%)
    if iva_pct > 0:
        tasa = a_decimal(iva_pct)
        base_sin_iva = Decimal(subtotal) / (Decimal(1) + tasa)
        iva_valor = redondear_al_peso(Decimal(subtotal) - base_sin_iva)
    else:
        iva_valor = 0

    return {
        "subtotal": subtotal,
        "costo_total": costo_total,
        "iva_valor": iva_valor,
    }


@dataclass
class ItemCarrito:
    producto_id: int
    codigo_barras: str | None
    nombre: str
    tipo_venta: str          # 'unidad' | 'peso'
    cantidad: int            # unidades o gramos
    precio_unitario: int     # por unidad o por libra (500 g)
    costo_unitario: int      # por unidad o por libra (500 g)
    iva_pct: int             # centésimas (1900 = 19 %)
    subtotal: int = 0
    costo_total: int = 0
    iva_valor: int = 0

    def __post_init__(self) -> None:
        self.recalcular()

    def recalcular(self) -> None:
        datos = calcular_linea(
            self.tipo_venta,
            self.cantidad,
            self.precio_unitario,
            self.costo_unitario,
            self.iva_pct,
        )
        self.subtotal = datos["subtotal"]
        self.costo_total = datos["costo_total"]
        self.iva_valor = datos["iva_valor"]

    def texto_cantidad(self) -> str:
        if self.tipo_venta == "peso":
            return formatear_peso(self.cantidad)
        return str(self.cantidad)


@dataclass
class Carrito:
    """Carrito de compras activo en la pantalla de ventas."""

    items: list[ItemCarrito] = field(default_factory=list)

    def esta_vacio(self) -> bool:
        return len(self.items) == 0

    def limpiar(self) -> None:
        self.items.clear()

    def total(self) -> int:
        return sum(i.subtotal for i in self.items)

    def total_iva(self) -> int:
        return sum(i.iva_valor for i in self.items)

    def total_costo(self) -> int:
        return sum(i.costo_total for i in self.items)

    def buscar_indice(self, producto_id: int) -> int:
        for idx, item in enumerate(self.items):
            if item.producto_id == producto_id:
                return idx
        return -1

    def agregar_producto(self, producto: dict, cantidad: int) -> int:
        """
        Agrega un producto al carrito (si ya estaba, suma la cantidad).
        `cantidad`: unidades si es por unidad, o gramos si es por peso.
        Para productos por peso se permite `cantidad = 0` al agregarlo para que
        el cajero escriba los gramos directamente en la celda de Cantidad.
        Devuelve el índice de la fila en el carrito.
        """
        if not producto.get("activo", 1):
            raise ErrorVenta(f"El producto '{producto['nombre']}' está desactivado.")
        cantidad = int(cantidad)
        es_peso = producto["tipo_venta"] == "peso"
        if (not es_peso and cantidad <= 0) or (es_peso and cantidad < 0):
            raise ErrorVenta("La cantidad debe ser mayor que 0.")

        idx = self.buscar_indice(producto["id"])
        if idx >= 0:
            item = self.items[idx]
            item.nombre = producto["nombre"]
            item.codigo_barras = producto["codigo_barras"]
            item.precio_unitario = producto["precio_final"]
            item.costo_unitario = producto["costo"]
            item.iva_pct = producto["iva_pct"]
            item.cantidad += cantidad
            item.recalcular()
            return idx

        nuevo = ItemCarrito(
            producto_id=producto["id"],
            codigo_barras=producto["codigo_barras"],
            nombre=producto["nombre"],
            tipo_venta=producto["tipo_venta"],
            cantidad=cantidad,
            precio_unitario=producto["precio_final"],
            costo_unitario=producto["costo"],
            iva_pct=producto["iva_pct"],
        )
        self.items.append(nuevo)
        return len(self.items) - 1

    def cambiar_cantidad(self, indice: int, nueva_cantidad: int) -> None:
        if not (0 <= indice < len(self.items)):
            raise IndexError("Ítem fuera de rango")
        nueva_cantidad = int(nueva_cantidad)
        es_peso = self.items[indice].tipo_venta == "peso"
        if (not es_peso and nueva_cantidad <= 0) or (es_peso and nueva_cantidad < 0):
            raise ErrorVenta("La cantidad debe ser mayor que 0.")
        self.items[indice].cantidad = nueva_cantidad
        self.items[indice].recalcular()

    def quitar_item(self, indice: int) -> None:
        if 0 <= indice < len(self.items):
            self.items.pop(indice)

    def clonar(self) -> "Carrito":
        copia = Carrito()
        for i in self.items:
            copia.items.append(
                ItemCarrito(
                    producto_id=i.producto_id,
                    codigo_barras=i.codigo_barras,
                    nombre=i.nombre,
                    tipo_venta=i.tipo_venta,
                    cantidad=i.cantidad,
                    precio_unitario=i.precio_unitario,
                    costo_unitario=i.costo_unitario,
                    iva_pct=i.iva_pct,
                )
            )
        return copia


# ---------------------------------------------------------------------
# Validación de stock y cobro transaccional
# ---------------------------------------------------------------------
def verificar_stock_carrito(carrito: Carrito) -> list[dict]:
    """
    Revisa si algún ítem del carrito supera el stock disponible actual en la BD.
    Devuelve una lista de diccionarios con los productos que no alcanzan:
      [{'producto_id', 'nombre', 'tipo_venta', 'pedido', 'disponible', 'faltante'}]
    Lista vacía = todo alcanza.
    """
    faltantes = []
    for item in carrito.items:
        actual = inventario.obtener(item.producto_id)
        disponible = actual["stock"] if actual else 0
        if item.cantidad > disponible:
            faltantes.append({
                "producto_id": item.producto_id,
                "nombre": item.nombre,
                "tipo_venta": item.tipo_venta,
                "pedido": item.cantidad,
                "disponible": disponible,
                "faltante": item.cantidad - disponible,
            })
    return faltantes


def _turno_abierto_id(con) -> int | None:
    """Si hay un turno de caja abierto (Fase 7), devuelve su id; si no, None."""
    fila = con.execute(
        "SELECT id FROM turnos WHERE cerrado_en IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return fila["id"] if fila else None


def registrar_venta(
    carrito: Carrito,
    medio_pago: str,
    monto_recibido: int | None = None,
    permitir_sin_stock: bool | None = None,
    exigir_turno: bool = True,
) -> dict:
    """
    Guarda la venta, sus ítems ("foto" al momento de la venta) y descuenta el stock
    en UNA sola transacción. Luego llama a `abrir_cajon()`.

    Desde la Fase 7 (`exigir_turno=True`), exige que exista un turno de caja abierto.
    """
    if carrito.esta_vacio():
        raise ErrorVenta("El carrito está vacío.")
    sin_cantidad = [it.nombre for it in carrito.items if it.cantidad <= 0]
    if sin_cantidad:
        raise ErrorVenta(
            "Falta ingresar la cantidad en gramos para: " + ", ".join(sin_cantidad) + "."
        )
    if medio_pago not in dict(MEDIOS_PAGO):
        raise ErrorVenta("Medio de pago no válido.")

    total = carrito.total()
    if medio_pago == "efectivo":
        if monto_recibido is None:
            monto_recibido = total
        monto_recibido = int(monto_recibido)
        if monto_recibido < total:
            raise ErrorVenta("El monto recibido es menor que el total a cobrar.")
        cambio = monto_recibido - total
    else:
        monto_recibido = total
        cambio = 0

    if permitir_sin_stock is None:
        permitir_sin_stock = ajustes.obtener("politica_stock") != "bloquear"

    faltantes = verificar_stock_carrito(carrito)
    if faltantes and not permitir_sin_stock:
        nombres = ", ".join(f["nombre"] for f in faltantes)
        raise ErrorVenta(f"Stock insuficiente para: {nombres}.")

    momento = ahora()
    total_iva = carrito.total_iva()
    total_costo = carrito.total_costo()

    # Transacción "todo o nada": encabezado + líneas + descuento de stock
    with transaccion() as con:
        turno_id = _turno_abierto_id(con)
        if exigir_turno and turno_id is None:
            raise ErrorVenta("Debe abrir un turno de caja antes de registrar una venta.")
        venta_id = con.execute(
            """INSERT INTO ventas
               (fecha, turno_id, total, total_iva, total_costo, medio_pago, monto_recibido, cambio)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (momento, turno_id, total, total_iva, total_costo, medio_pago, monto_recibido, cambio),
        ).lastrowid

        for item in carrito.items:
            con.execute(
                """INSERT INTO venta_items
                   (venta_id, producto_id, nombre, codigo_barras, tipo_venta, cantidad,
                    precio_unitario, costo_unitario, iva_pct, subtotal, iva_valor, costo_total)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    venta_id,
                    item.producto_id,
                    item.nombre,
                    item.codigo_barras,
                    item.tipo_venta,
                    item.cantidad,
                    item.precio_unitario,
                    item.costo_unitario,
                    item.iva_pct,
                    item.subtotal,
                    item.iva_valor,
                    item.costo_total,
                ),
            )
            inventario.registrar_movimiento(
                con,
                producto_id=item.producto_id,
                tipo="venta",
                cantidad=-item.cantidad,
                motivo=f"Venta #{venta_id}",
                referencia_id=venta_id,
            )

    # Abrir cajón fuera de la transacción: si falla, la venta ya quedó guardada.
    # Opción A aprobada: abrir en ventas en efectivo, o también en otros medios si así se configuró.
    debe_abrir = (medio_pago == "efectivo") or ajustes.obtener_booleano("cajon_abrir_otros_medios")
    if debe_abrir:
        try:
            cajon_ok, cajon_msg = abrir_cajon()
        except Exception as e:  # noqa: BLE001
            cajon_ok, cajon_msg = False, str(e)
    else:
        cajon_ok, cajon_msg = False, f"No se abre en pagos por {medio_pago}"

    return {
        "venta_id": venta_id,
        "fecha": momento,
        "total": total,
        "medio_pago": medio_pago,
        "monto_recibido": monto_recibido,
        "cambio": cambio,
        "cajon_abierto": cajon_ok,
        "cajon_mensaje": cajon_msg,
    }


# ---------------------------------------------------------------------
# Ventas en espera (en memoria mientras el programa esté abierto)
# ---------------------------------------------------------------------
@dataclass
class VentaEnEspera:
    numero: int
    hora: str
    nota: str
    carrito: Carrito

    def resumen(self) -> str:
        n_items = len(self.carrito.items)
        etiqueta = f" ({self.nota})" if self.nota else ""
        return f"Espera #{self.numero} [{self.hora}]{etiqueta} — {n_items} ítem(s)"


class GestorVentasEnEspera:
    """Mantiene en memoria las ventas pausadas."""

    def __init__(self) -> None:
        self._lista: list[VentaEnEspera] = []
        self._consecutivo: int = 1

    def cantidad(self) -> int:
        return len(self._lista)

    def listar(self) -> list[VentaEnEspera]:
        return list(self._lista)

    def poner_en_espera(self, carrito: Carrito, nota: str = "") -> VentaEnEspera:
        if carrito.esta_vacio():
            raise ErrorVenta("No hay productos en el carrito para poner en espera.")
        entrada = VentaEnEspera(
            numero=self._consecutivo,
            hora=datetime.now().strftime("%H:%M"),
            nota=(nota or "").strip().upper(),
            carrito=carrito.clonar(),
        )
        self._consecutivo += 1
        self._lista.append(entrada)
        return entrada

    def recuperar(self, indice: int) -> VentaEnEspera:
        if not (0 <= indice < len(self._lista)):
            raise IndexError("Venta en espera no encontrada")
        return self._lista.pop(indice)

    def eliminar(self, indice: int) -> None:
        if 0 <= indice < len(self._lista):
            self._lista.pop(indice)
