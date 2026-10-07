# Gestor de Finanzas

App de escritorio en **Python** para llevar ingresos, egresos y deudas, con **datos cifrados**, gráficos y modo claro/oscuro.

## Qué hace
- **Movimientos**: ingresos y egresos con categoría, frecuencia (única vez, mensual, etc.), medio de pago y motivo. Búsqueda, filtros por monto, orden y borrado múltiple con "deshacer".
- **Categorías automáticas** por palabras clave (Rappi → Comida, Metrogas → Servicios…), que aprenden de tus correcciones.
- **Importación** de resúmenes de Mercado Pago (PDF, CSV, XLSX o texto pegado) y CSV/Excel de otros bancos, con verificación de que los saldos encadenen.
- **Saldo real y proyección**: usa los saldos del banco como puntos de control y proyecta con tus planes, cuotas y el promedio de los últimos 3 meses.
- **Deudas** en cuotas ("yo debo" / "me deben").
- **Gráficos**: evolución (barras + línea de saldo), distribución por categoría y un balance general (activo, pasivo, patrimonio neto).
- **Privacidad**: SQLite donde cada registro se guarda cifrado con Fernet (AES + HMAC). La clave se deriva de tu contraseña con PBKDF2 (480.000 iteraciones); la contraseña nunca se guarda.

## Tecnologías
Python 3.9+ · Tkinter · SQLite · `cryptography` · `openpyxl` · `pdfplumber` · PyInstaller

## Estructura
| Archivo | Rol |
|---|---|
| `main.py` | Punto de entrada |
| `interfaz.py` | Interfaz (Tkinter) |
| `logica.py` | Modelos y cálculos (movimientos, deudas, categorías, proyección) |
| `almacen.py` | Persistencia cifrada (SQLite + Fernet) |
| `importar.py` | Lectura de resúmenes y archivos bancarios |

## Cómo correrlo
```bash
pip install -r requirements.txt
python main.py
```
Para armar el ejecutable: `construir_app.bat` (Windows) o `./construir_app.sh` (Linux/Mac). Más detalle de uso en [`LEEME.txt`](LEEME.txt).

Los datos se guardan fuera del proyecto (`%APPDATA%\GestorFinanzas\finanzas.dat` en Windows) y **no forman parte de este repositorio**.

## Autor
Joaquin Gandur — estudiante de la Tecnicatura Universitaria en Programación (UTN FRA).
