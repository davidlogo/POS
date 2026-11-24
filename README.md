# POS – Punto de venta de escritorio

Sistema de punto de venta 100 % offline para una tienda. Funciona en Windows y Linux.

**Estado actual: Fase 2** (base de datos, login, ajustes, inventario + importación/exportación Excel y CSV).

---

## 1. Instalación (solo la primera vez en un computador nuevo)

### Windows
1. Instale **Python 3.11 o superior** desde https://www.python.org/downloads/
   - En el instalador marque la casilla **"Add Python to PATH"**.
2. Abra la carpeta `pos`, haga clic en la barra de direcciones del Explorador, escriba `powershell` y presione Enter.
3. Copie y pegue estos comandos, uno por uno:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
   (Esto necesita internet **solo esta vez**, para descargar las librerías. El POS después funciona sin internet).

### Linux (Ubuntu / Mint)
```bash
sudo apt install python3 python3-venv
cd ruta/a/pos
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

---

## 2. Ejecutar el programa

### Opción A (la más fácil en Windows): doble clic
Haga doble clic sobre el archivo **`iniciar_pos.bat`** dentro de la carpeta `pos`.

### Opción B: desde PowerShell / Terminal
- **Windows:**
  ```powershell
  .\.venv\Scripts\python.exe main.py
  ```
- **Linux:**
  ```bash
  .venv/bin/python main.py
  ```

La primera vez le pedirá **crear la contraseña**. Las siguientes veces se la pedirá para entrar.

---

## 3. Si olvida la contraseña

Ejecute este comando en PowerShell dentro de la carpeta `pos` (no borra productos ni ventas):
```powershell
.\.venv\Scripts\python.exe scripts\restablecer_clave.py
```

---

## 4. Plantilla de Excel para importar productos

- Puede descargarla desde el botón **"Descargar plantilla Excel"** en la pestaña **Inventario (F6)**, o usar la copia en `recursos/plantilla_productos.xlsx`.
- También acepta archivos **CSV** separados por `;` o por `,` (se detecta solo).

---

## 5. Dónde quedan los datos

Todo se guarda en un solo archivo: `pos/datos/pos.db`.
No lo borre ni lo mueva: ahí están productos, ventas y ajustes.
(En la Fase 8 se agregan los respaldos automáticos).

---

## 6. Atajos de teclado

| Tecla | Acción |
|---|---|
| F1 | Ventas |
| F6 | Inventario |
| F7 | Devoluciones |
| F9 | Caja |
| F10 | Reportes |
| F11 | Ajustes |
| Ctrl+S | Guardar en ventanas de producto o ajuste de stock |
