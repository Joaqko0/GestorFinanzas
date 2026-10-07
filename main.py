"""Gestor de Finanzas: ingresos y egresos con datos cifrados.

Uso:  python main.py          (o el .exe que arma construir_app.bat)
"""
import os
import sys
import tkinter as tk
from tkinter import messagebox

from almacen import Boveda, ruta_datos
from interfaz import App


def ruta_recurso(nombre: str) -> str:
    """Ruta de un archivo que viaja con el programa (dentro del .exe, PyInstaller lo deja en _MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, nombre)


def nitidez_en_windows():
    """En pantallas con escala (125 %, 150 %...) Windows estira la ventana y se ve borrosa.
    Así la app se dibuja nítida. En otros sistemas no hace nada."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def main():
    nitidez_en_windows()
    try:
        bd = Boveda(ruta_datos())
    except Exception as error:      # por ejemplo, sin permiso para escribir en la carpeta de datos
        raiz = tk.Tk()
        raiz.withdraw()
        messagebox.showerror("Gestor de Finanzas", f"No se pudo abrir el archivo de datos:\n{error}")
        return
    app = App(bd)
    try:
        app.iconbitmap(default=ruta_recurso("icono.ico"))       # ícono de la ventana y de sus diálogos
    except tk.TclError:
        pass                                                    # sin ícono no pasa nada
    app.mainloop()


if __name__ == "__main__":
    main()
