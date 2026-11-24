-- =====================================================================
-- ESQUEMA DE LA BASE DE DATOS DEL POS (versión 1)
--
-- Convenciones:
--   * Dinero: INTEGER en pesos (sin decimales).
--   * Porcentajes: INTEGER en centésimas (19 % = 1900).
--   * Peso: INTEGER en gramos. Precio y costo de productos por peso = por LIBRA (500 g).
--   * Fechas: TEXT 'AAAA-MM-DD HH:MM:SS' (hora local).
-- =====================================================================

-- Configuración general (clave / valor)
CREATE TABLE IF NOT EXISTS ajustes (
    clave   TEXT PRIMARY KEY,
    valor   TEXT
);

-- Único usuario del sistema (siempre id = 1)
CREATE TABLE IF NOT EXISTS usuario (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    hash_clave      TEXT    NOT NULL,
    sal             TEXT    NOT NULL,
    iteraciones     INTEGER NOT NULL,
    actualizado_en  TEXT    NOT NULL
);

-- Categorías de productos
CREATE TABLE IF NOT EXISTS categorias (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    activo  INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);

-- Productos (borrado lógico con "activo")
CREATE TABLE IF NOT EXISTS productos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_barras     TEXT    UNIQUE,                 -- opcional (NULL permitido)
    nombre            TEXT    NOT NULL,
    categoria_id      INTEGER REFERENCES categorias(id),
    tipo_venta        TEXT    NOT NULL DEFAULT 'unidad' CHECK (tipo_venta IN ('unidad', 'peso')),
    costo             INTEGER NOT NULL DEFAULT 0 CHECK (costo >= 0),        -- por unidad o por libra
    ganancia_pct      INTEGER NOT NULL DEFAULT 0 CHECK (ganancia_pct >= 0),
    iva_pct           INTEGER NOT NULL DEFAULT 0 CHECK (iva_pct >= 0),
    redondeo_multiplo INTEGER NOT NULL DEFAULT 1,
    redondeo_modo     TEXT    NOT NULL DEFAULT 'arriba',
    precio_calculado  INTEGER NOT NULL DEFAULT 0 CHECK (precio_calculado >= 0),
    precio_manual     INTEGER CHECK (precio_manual IS NULL OR precio_manual >= 0),
    precio_final      INTEGER NOT NULL DEFAULT 0 CHECK (precio_final >= 0), -- el que se usa al vender
    stock             INTEGER NOT NULL DEFAULT 0,      -- unidades o gramos (puede quedar negativo según ajustes)
    stock_minimo      INTEGER NOT NULL DEFAULT 0 CHECK (stock_minimo >= 0),
    activo            INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en         TEXT    NOT NULL,
    actualizado_en    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_productos_nombre ON productos(nombre COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_productos_activo ON productos(activo);

-- Historial de todos los cambios de stock
CREATE TABLE IF NOT EXISTS movimientos_stock (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id     INTEGER NOT NULL REFERENCES productos(id),
    fecha           TEXT    NOT NULL,
    tipo            TEXT    NOT NULL CHECK (tipo IN
                        ('venta', 'devolucion', 'ingreso', 'merma', 'correccion', 'importacion')),
    cantidad        INTEGER NOT NULL,                  -- con signo: + entra, - sale
    stock_anterior  INTEGER NOT NULL,
    stock_nuevo     INTEGER NOT NULL,
    motivo          TEXT,
    referencia_id   INTEGER                            -- id de venta o devolución, si aplica
);
CREATE INDEX IF NOT EXISTS idx_movstock_producto ON movimientos_stock(producto_id, fecha);

-- Turnos de caja (apertura / cierre)
CREATE TABLE IF NOT EXISTS turnos (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    abierto_en              TEXT    NOT NULL,
    fondo_inicial           INTEGER NOT NULL DEFAULT 0 CHECK (fondo_inicial >= 0),
    cerrado_en              TEXT,                      -- NULL = turno abierto
    ventas_efectivo         INTEGER,
    ventas_tarjeta          INTEGER,
    ventas_transferencia    INTEGER,
    devoluciones_efectivo   INTEGER,
    devoluciones_total      INTEGER,
    retiros_total           INTEGER,
    efectivo_esperado       INTEGER,
    efectivo_contado        INTEGER,
    diferencia              INTEGER,                   -- + sobrante / - faltante
    notas                   TEXT
);

-- Retiros y gastos de caja
CREATE TABLE IF NOT EXISTS movimientos_caja (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    turno_id    INTEGER NOT NULL REFERENCES turnos(id),
    fecha       TEXT    NOT NULL,
    tipo        TEXT    NOT NULL CHECK (tipo IN ('retiro', 'gasto')),
    monto       INTEGER NOT NULL CHECK (monto > 0),
    motivo      TEXT    NOT NULL
);

-- Ventas (encabezado)
CREATE TABLE IF NOT EXISTS ventas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha           TEXT    NOT NULL,
    turno_id        INTEGER REFERENCES turnos(id),
    total           INTEGER NOT NULL CHECK (total >= 0),   -- IVA incluido
    total_iva       INTEGER NOT NULL DEFAULT 0,
    total_costo     INTEGER NOT NULL DEFAULT 0,
    medio_pago      TEXT    NOT NULL CHECK (medio_pago IN ('efectivo', 'tarjeta', 'transferencia')),
    monto_recibido  INTEGER,
    cambio          INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha);

-- Detalle de ventas: "foto" del producto al momento de vender
CREATE TABLE IF NOT EXISTS venta_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id         INTEGER NOT NULL REFERENCES ventas(id),
    producto_id      INTEGER NOT NULL REFERENCES productos(id),
    nombre           TEXT    NOT NULL,
    codigo_barras    TEXT,
    tipo_venta       TEXT    NOT NULL CHECK (tipo_venta IN ('unidad', 'peso')),
    cantidad         INTEGER NOT NULL CHECK (cantidad > 0),   -- unidades o gramos
    precio_unitario  INTEGER NOT NULL,                        -- por unidad o por libra
    costo_unitario   INTEGER NOT NULL,                        -- por unidad o por libra
    iva_pct          INTEGER NOT NULL,
    subtotal         INTEGER NOT NULL,
    iva_valor        INTEGER NOT NULL,
    costo_total      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_venta_items_venta ON venta_items(venta_id);

-- Devoluciones (encabezado)
CREATE TABLE IF NOT EXISTS devoluciones (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id         INTEGER NOT NULL REFERENCES ventas(id),
    turno_id         INTEGER REFERENCES turnos(id),
    fecha            TEXT    NOT NULL,
    motivo           TEXT    NOT NULL,
    total_devuelto   INTEGER NOT NULL CHECK (total_devuelto >= 0),
    medio_reembolso  TEXT    NOT NULL CHECK (medio_reembolso IN ('efectivo', 'tarjeta', 'transferencia'))
);
CREATE INDEX IF NOT EXISTS idx_devoluciones_fecha ON devoluciones(fecha);

-- Detalle de devoluciones
CREATE TABLE IF NOT EXISTS devolucion_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    devolucion_id   INTEGER NOT NULL REFERENCES devoluciones(id),
    venta_item_id   INTEGER NOT NULL REFERENCES venta_items(id),
    cantidad        INTEGER NOT NULL CHECK (cantidad > 0),
    valor           INTEGER NOT NULL,
    costo_valor     INTEGER NOT NULL,
    repone_stock    INTEGER NOT NULL CHECK (repone_stock IN (0, 1))
);
