"""Interfaz gráfica (tkinter): movimientos, deudas, resumen, gráfico de evolución y gráfico circular."""
from __future__ import annotations

import math
import sys
import tkinter as tk
import traceback
from datetime import date
from tkinter import filedialog, messagebox, ttk

from almacen import Boveda, ClaveIncorrecta
from importar import es_propia, leer_archivos, leer_mercadopago, leer_texto_resumen, marcar_repetidas
from logica import (BalanceGeneral, CATEGORIAS_EGRESO, CATEGORIAS_INGRESO, ENTRE_MIS_CUENTAS, FRECUENCIAS, GRANULARIDADES, MESES,
                    SIN_CATEGORIA,
                    UNIDADES, Deuda, Movimiento, Punto, categorizar, cuotas_en_mes, cuotas_futuras, dinero,
                    dinero_corto, distribucion, etiqueta_eje, inicio_periodo, nombre_periodo, normalizar, numero,
                    ocurre_en, parse_entero, parse_fecha, parse_hora, parse_monto, periodo_anterior,
                    periodo_siguiente, saldo_en, serie, ticks_agradables, totales_periodo, veces_cubierto, ocurrencias,
                    arrastre_de, balance_general, inicio_datos_reales,
                    fin_periodo,
                    estimado_variable, meses_con_datos, _sumar_meses)

# Colores del gráfico circular (verificados para daltonismo en los dos temas). "Otros" va siempre en gris.
PALETA_TORTA = {
    "claro": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"],
    "oscuro": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"],
}

TEMAS = {
    "claro": {
        "fondo": "#eceff4", "panel": "#ffffff", "texto": "#1c2430", "suave": "#647084",
        "borde": "#d3d9e2", "entrada": "#ffffff", "acento": "#2b59c3", "acento_hover": "#234aa3",
        "boton": "#dfe4ec", "boton_hover": "#ced5e0", "grilla": "#e4e8ef",
        "ingreso": "#1f8a4c", "egreso": "#d33b2f", "saldo": "#2b59c3", "aviso": "#b36b00", "error": "#d33b2f",
    },
    "oscuro": {
        "fondo": "#141a24", "panel": "#1d2533", "texto": "#e7ebf2", "suave": "#8e9bb0",
        "borde": "#2d384a", "entrada": "#141a24", "acento": "#5b8def", "acento_hover": "#4a7be0",
        "boton": "#293346", "boton_hover": "#354158", "grilla": "#2a3446",
        "ingreso": "#4cc38a", "egreso": "#f0736a", "saldo": "#6ea0ff", "aviso": "#f2b544", "error": "#f0736a",
    },
}

# Opciones del gráfico circular: (texto en pantalla, clave interna)
AGRUPAR = (("Categoría", "categoria"), ("Nombre", "nombre"), ("Motivo", "motivo"), ("Hora del día", "hora"),
           ("Medio de pago", "medio"))
# Qué muestra la lista de la izquierda
FILTROS = (("Del período elegido", "periodo"), ("Todos", "todos"), ("Solo los que se repiten", "repiten"))
TIPOS_DEUDA = (("Yo debo", "debo"), ("Me deben", "me_deben"))
ORDENES = (("Más nuevos primero", "fecha_desc"), ("Más viejos primero", "fecha_asc"),
           ("Monto: de mayor a menor", "monto_desc"), ("Monto: de menor a mayor", "monto_asc"))
MAX_TARJETAS = 150                     # más que esto se vuelve lento; se pide filtrar
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

FUENTE = ("Segoe UI", 10)
FUENTE_CHICA = ("Segoe UI", 9)
FUENTE_NEG = ("Segoe UI", 10, "bold")
FUENTE_CIFRA = ("Segoe UI", 17, "bold")
FUENTE_TITULO = ("Segoe UI", 15, "bold")


def mezclar(color: str, otro: str, t: float) -> str:
    """Mezcla dos colores #rrggbb (t=0 devuelve `color`, t=1 devuelve `otro`). Sirve para 'aclarar'."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(otro[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def texto_repeticion(m: Movimiento) -> str:
    """'Se repite cada mes, sin fecha de fin' / 'Se repite 12 meses (hasta 01/03/2027)'."""
    cada = {"Diaria": "cada día", "Semanal": "cada semana", "Mensual": "cada mes", "Anual": "cada año"}
    if m.duracion:
        return f"Se repite {m.duracion} {UNIDADES[m.frecuencia]} (hasta {m.ultima_fecha():%d/%m/%Y})"
    return f"Se repite {cada[m.frecuencia]}, sin fecha de fin"


# ─────────────────────────── piezas básicas ───────────────────────────

class Boton(tk.Label):
    """Botón hecho con Label: se pinta igual en todos los sistemas (modo claro y oscuro)."""

    def __init__(self, padre, texto, comando, bg, fg, hover, fuente=FUENTE_NEG, padx=14, pady=6):
        super().__init__(padre, text=texto, bg=bg, fg=fg, font=fuente, padx=padx, pady=pady, cursor="hand2")
        self._bg, self._hover = bg, hover
        self.bind("<Button-1>", lambda e: comando())
        self.bind("<Enter>", lambda e: self.config(bg=self._hover))
        self.bind("<Leave>", lambda e: self.config(bg=self._bg))

    def colorear(self, bg, fg, hover):
        self._bg, self._hover = bg, hover
        self.config(bg=bg, fg=fg)


class Barra(tk.Canvas):
    """Barra que muestra qué parte del ingreso se va en egresos."""

    def __init__(self, padre, c):
        super().__init__(padre, height=10, bg=c["panel"], highlightthickness=0)
        self.c, self.ratio, self.color = c, 0.0, c["ingreso"]
        self.bind("<Configure>", lambda e: self._pintar())

    def poner(self, ratio, color):
        self.ratio, self.color = ratio, color
        self._pintar()

    def _pintar(self):
        self.delete("all")
        ancho = self.winfo_width()
        self.create_rectangle(0, 0, ancho, 10, fill=self.c["grilla"], width=0)
        if self.ratio > 0:
            self.create_rectangle(0, 0, ancho * self.ratio, 10, fill=self.color, width=0)


class ListaScroll(tk.Frame):
    """Zona con scroll vertical donde se apilan las tarjetas."""

    def __init__(self, padre, c, mensaje_vacio, ancho=400):
        super().__init__(padre, bg=c["fondo"])
        self.canvas = tk.Canvas(self, bg=c["fondo"], highlightthickness=0, width=ancho, yscrollincrement=20)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.interior = tk.Frame(self.canvas, bg=c["fondo"])
        ventana = self.canvas.create_window((0, 0), window=self.interior, anchor="nw")
        self.interior.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(ventana, width=e.width))
        self.vacio = tk.Label(self.interior, text=mensaje_vacio, bg=c["fondo"], fg=c["suave"], font=FUENTE,
                              justify="center", wraplength=340, pady=36)

    def limpiar(self):
        """Saca todo lo que hay en la lista (menos el mensaje de lista vacía)."""
        for w in self.interior.winfo_children():
            if w is not self.vacio:
                w.destroy()

    def actualizar_vacio(self, mensaje=None):
        """Muestra la invitación a agregar algo cuando no hay tarjetas."""
        if mensaje:
            self.vacio.config(text=mensaje)
        hay = [w for w in self.interior.pack_slaves() if w is not self.vacio]
        if hay:
            self.vacio.pack_forget()
        else:
            self.vacio.pack(fill="x")

    def al_inicio(self):
        self.canvas.yview_moveto(0)

    def desplazar(self, evento):
        if self.canvas.yview() == (0.0, 1.0):          # todo entra en pantalla: nada que mover
            return
        if evento.num == 4:                            # Linux: rueda hacia arriba
            paso = -1
        elif evento.num == 5:                          # Linux: rueda hacia abajo
            paso = 1
        else:                                          # Windows y Mac
            paso = -1 if evento.delta > 0 else 1
        self.canvas.yview_scroll(paso * 3, "units")


class Formulario:
    """Ayuda para armar grillas de campos con el mismo estilo (etiqueta + entrada)."""

    def __init__(self, app, marco, guardar_luego, guardar_ya):
        self.app, self.marco = app, marco
        self.guardar_luego, self.guardar_ya = guardar_luego, guardar_ya
        marco.grid_columnconfigure(1, weight=1, uniform="campo")
        marco.grid_columnconfigure(3, weight=1, uniform="campo")

    def etiqueta(self, fila, columna, texto):
        c = self.app.c
        tk.Label(self.marco, text=texto, bg=c["panel"], fg=c["suave"], font=FUENTE_CHICA, anchor="w").grid(
            row=fila, column=columna, sticky="w", padx=(0, 8))

    def entrada(self, padre, var, **kw):
        c = self.app.c
        e = tk.Entry(padre, textvariable=var, bg=c["entrada"], fg=c["texto"], insertbackground=c["texto"],
                     disabledbackground=c["fondo"], disabledforeground=c["suave"], relief="flat",
                     highlightthickness=1, highlightbackground=c["borde"], highlightcolor=c["acento"],
                     font=FUENTE, **kw)
        e.bind("<Return>", lambda ev: self.guardar_ya())
        e.bind("<FocusOut>", lambda ev: self.guardar_ya())
        return e

    def campo(self, var, fila, columna, columnas=1):
        e = self.entrada(self.marco, var)
        e.grid(row=fila, column=columna, columnspan=columnas, sticky="ew", pady=3, ipady=3,
               padx=(0, 8) if columna + columnas < 4 else 0)
        return e

    def lista(self, var, valores, fila, columna, editable=False, ancho=8):
        combo = ttk.Combobox(self.marco, textvariable=var, values=valores, state="normal" if editable else "readonly",
                             width=ancho, font=FUENTE)
        combo.grid(row=fila, column=columna, sticky="ew", pady=3, padx=(0, 8) if columna < 3 else 0)
        combo.bind("<<ComboboxSelected>>", lambda e: self.guardar_ya())
        return combo


# ─────────────────────────── tarjeta de movimiento ───────────────────────────

class Tarjeta(tk.Frame):
    """Un ingreso o egreso. Cerrada muestra una línea de resumen; abierta, todos los campos.
    Se guarda sola un instante después de editar."""

    def __init__(self, padre, app: App, mov: Movimiento, abierta=False):
        c = app.c
        super().__init__(padre, bg=c["panel"], highlightthickness=1, highlightbackground=c["borde"])
        self.app, self.mov, self._timer, self.v, self.cuerpo = app, mov, None, None, None
        self._abierta = False
        self.color = c["egreso"] if mov.tipo == "egreso" else c["ingreso"]
        tk.Frame(self, bg=self.color, width=5).pack(side="left", fill="y")      # franja de color del tipo
        self.var_sel = None
        if app.modo_seleccion:                                                   # casilla para borrar varios
            self.var_sel = tk.BooleanVar(value=mov.id in app.seleccionados)
            tk.Checkbutton(self, variable=self.var_sel, command=self._marcar, bg=c["panel"],
                           activebackground=c["panel"], selectcolor=c["entrada"], fg=c["texto"],
                           activeforeground=c["texto"], highlightthickness=0, bd=0, cursor="hand2").pack(
                side="left", padx=(8, 0))
        self.contenido = tk.Frame(self, bg=c["panel"], padx=12, pady=8)
        self.contenido.pack(side="left", fill="both", expand=True)

        cab = tk.Frame(self.contenido, bg=c["panel"])
        cab.pack(fill="x")
        cab.grid_columnconfigure(0, weight=1)
        self.l_nombre = tk.Label(cab, bg=c["panel"], fg=c["texto"], font=FUENTE_NEG, anchor="w", cursor="hand2")
        self.l_nombre.grid(row=0, column=0, sticky="w")
        self.l_monto = tk.Label(cab, bg=c["panel"], fg=self.color, font=FUENTE_NEG, anchor="e", cursor="hand2")
        self.l_monto.grid(row=0, column=1, sticky="e")
        self.l_info = tk.Label(cab, bg=c["panel"], fg=c["suave"], font=FUENTE_CHICA, anchor="w", justify="left",
                               wraplength=230, cursor="hand2")
        self.l_info.grid(row=1, column=0, sticky="w")
        acciones = tk.Frame(cab, bg=c["panel"])
        acciones.grid(row=1, column=1, rowspan=2, sticky="se")
        self.b_editar = Boton(acciones, "Editar", self.alternar, c["panel"], c["acento"], c["boton_hover"],
                              fuente=FUENTE_CHICA, padx=5, pady=1)
        self.b_editar.pack(side="left")
        Boton(acciones, "Duplicar", lambda: self.app.duplicar(self), c["panel"], c["acento"], c["boton_hover"],
              fuente=FUENTE_CHICA, padx=5, pady=1).pack(side="left")
        Boton(acciones, "✕", self._eliminar, c["panel"], c["suave"], c["boton_hover"], padx=6, pady=1).pack(
            side="left", padx=(2, 0))
        self.l_repite = tk.Label(cab, bg=c["panel"], fg=c["aviso"], font=FUENTE_CHICA, anchor="w")
        for w in (self.l_nombre, self.l_monto, self.l_info):
            w.bind("<Button-1>", lambda e: self.alternar())
        self._pintar_cabecera()
        if abierta:
            self.abrir()

    # ── cabecera ──
    def _pintar_cabecera(self):
        m = self.mov
        self.l_nombre.config(text=m.nombre or "Sin nombre")
        self.l_monto.config(text=("-" if m.tipo == "egreso" else "+") + dinero(m.cantidad))
        partes = [f"{m.inicio:%d/%m/%Y}" + (f" {m.hora}" if m.hora else ""), m.categoria or SIN_CATEGORIA]
        if m.medio:
            partes.append(m.medio)
        self.l_info.config(text=", ".join(partes))
        if m.se_repite:
            self.l_repite.config(text="↻ " + texto_repeticion(m))
            self.l_repite.grid(row=2, column=0, sticky="w")
        else:
            self.l_repite.grid_remove()

    # ── abrir / cerrar ──
    @property
    def abierta(self) -> bool:
        return self._abierta

    def _marcar(self):
        self.app.marcar(self.mov.id, self.var_sel.get())

    def alternar(self):
        if self.var_sel is not None:                 # modo selección: un clic marca o desmarca
            self.var_sel.set(not self.var_sel.get())
            self._marcar()
            return
        if self._abierta:
            self.cerrar()
        else:
            self.abrir()

    def abrir(self):
        if self.cuerpo is None:
            self._armar_cuerpo()
        self.cuerpo.pack(fill="x", pady=(8, 0))
        self._abierta = True
        self.b_editar.config(text="Cerrar")

    def cerrar(self):
        self.flush()
        if self.cuerpo is not None:
            self.cuerpo.pack_forget()
        self._abierta = False
        self.b_editar.config(text="Editar")

    def _armar_cuerpo(self):
        c, m = self.app.c, self.mov
        self.cuerpo = tk.Frame(self.contenido, bg=c["panel"])
        f = Formulario(self.app, self.cuerpo, self._programar, self.flush)
        self.v = {
            "nombre": tk.StringVar(value=m.nombre),
            "cantidad": tk.StringVar(value=numero(m.cantidad) if m.cantidad else ""),
            "categoria": tk.StringVar(value=m.categoria),
            "frecuencia": tk.StringVar(value=m.frecuencia),
            "duracion": tk.StringVar(value=str(m.duracion) if m.duracion else ""),
            "inicio": tk.StringVar(value=f"{m.inicio:%d/%m/%Y}"),
            "hora": tk.StringVar(value=m.hora),
            "medio": tk.StringVar(value=m.medio),
            "motivo": tk.StringVar(value=m.motivo),
        }
        f.etiqueta(0, 0, "Nombre")
        self.entrada_nombre = f.campo(self.v["nombre"], 0, 1, 3)
        f.etiqueta(1, 0, "Cantidad")
        f.campo(self.v["cantidad"], 1, 1)
        f.etiqueta(1, 2, "Categoría")
        f.lista(self.v["categoria"], CATEGORIAS_EGRESO if m.tipo == "egreso" else CATEGORIAS_INGRESO, 1, 3,
                editable=True, ancho=14)
        f.etiqueta(2, 0, "Frecuencia")
        f.lista(self.v["frecuencia"], FRECUENCIAS, 2, 1)
        f.etiqueta(2, 2, "Repeticiones")
        marco_dur = tk.Frame(self.cuerpo, bg=c["panel"])
        marco_dur.grid(row=2, column=3, sticky="w")
        self.e_dur = f.entrada(marco_dur, self.v["duracion"], width=5)
        self.e_dur.pack(side="left", pady=3, ipady=3)
        self.l_unidad = tk.Label(marco_dur, bg=c["panel"], fg=c["suave"], font=FUENTE_CHICA)
        self.l_unidad.pack(side="left", padx=(6, 0))
        f.etiqueta(3, 0, "Fecha")
        f.campo(self.v["inicio"], 3, 1)
        f.etiqueta(3, 2, "Hora")
        f.campo(self.v["hora"], 3, 3)
        f.etiqueta(4, 0, "Medio")
        f.campo(self.v["medio"], 4, 1, 3)
        f.etiqueta(5, 0, "Motivo")
        f.campo(self.v["motivo"], 5, 1, 3)
        self.l_total = tk.Label(self.cuerpo, bg=c["panel"], fg=self.color, font=FUENTE_NEG, anchor="w",
                                justify="left", wraplength=340)
        self.l_total.grid(row=6, column=0, columnspan=4, sticky="w", pady=(8, 0))
        # Recién ahora se conecta el autoguardado (así los valores iniciales no lo disparan).
        for var in self.v.values():
            var.trace_add("write", lambda *a: self._programar())
        self.v["frecuencia"].trace_add("write", lambda *a: self._actualizar_duracion())
        self._actualizar_duracion()
        self._mostrar_total()

    def _actualizar_duracion(self):
        frecuencia = self.v["frecuencia"].get()
        self.e_dur.config(state="disabled" if frecuencia == "Única vez" else "normal")
        self.l_unidad.config(text=f"{UNIDADES.get(frecuencia, '')} (vacío = sin fin)" if frecuencia != "Única vez"
                             else "")

    def _mostrar_total(self, extra=""):
        m = self.mov
        if not m.se_repite:
            texto = f"Total: {dinero(m.cantidad)}"
        elif m.duracion:
            texto = f"{m.duracion} × {dinero(m.cantidad)} = {dinero(m.total())}"
        else:
            texto = f"Sin fecha de fin: equivale a {dinero(m.equivalente_mensual())} por mes, todos los meses"
        if m.se_repite:
            cubiertas = veces_cubierto(m, self.app.movs, date.today())
            if cubiertas:
                texto += (f"\n{cubiertas} {'vez ya está cargada' if cubiertas == 1 else 'veces ya están cargadas'}"
                          " como movimiento real (mismo monto ±15 %, misma semana): no se cuentan dos veces.")
        self.l_total.config(text=texto + (f"\n{extra}" if extra else ""), fg=self.color)

    def _leer(self) -> Movimiento:
        """Arma un Movimiento con lo escrito; lanza ValueError (con un mensaje claro) si algo no sirve."""
        frecuencia = self.v["frecuencia"].get()
        texto_dur = self.v["duracion"].get().strip()
        duracion = 0
        if frecuencia != "Única vez" and texto_dur:
            duracion = parse_entero(texto_dur, "Repeticiones", 1, 10000)
        return Movimiento(tipo=self.mov.tipo, nombre=self.v["nombre"].get().strip(),
                          cantidad=parse_monto(self.v["cantidad"].get()), frecuencia=frecuencia,
                          duracion=duracion, motivo=self.v["motivo"].get().strip(),
                          inicio=parse_fecha(self.v["inicio"].get()), hora=parse_hora(self.v["hora"].get()),
                          medio=self.v["medio"].get().strip(), categoria=self.v["categoria"].get().strip(),
                          ref=self.mov.ref, id=self.mov.id)

    # ── guardado ──
    def _programar(self):
        """Espera un instante después de la última tecla y recién ahí guarda."""
        if self._timer is not None:
            self.after_cancel(self._timer)
        self._timer = self.after(600, self.guardar)

    def guardar(self):
        self._timer = None
        try:
            nuevo = self._leer()
        except ValueError as error:
            self.l_total.config(text=f"⚠ {error}", fg=self.app.c["error"])
            return
        anterior = self.mov
        extra = ""
        if not nuevo.categoria and nuevo.nombre:
            # Sin categoría: se sugiere una sola (se puede cambiar).
            nuevo.categoria = categorizar(nuevo.nombre, nuevo.motivo, nuevo.tipo, self.app.aprendidas)
            if nuevo.categoria != "Otros gastos" and nuevo.categoria != "Otros ingresos":
                self.v["categoria"].set(nuevo.categoria)
                if self._timer is not None:          # ese set() no necesita otro guardado
                    self.after_cancel(self._timer)
                    self._timer = None
            else:
                nuevo.categoria = ""
        elif nuevo.categoria and nuevo.categoria != anterior.categoria and nuevo.nombre and anterior.nombre:
            n = self.app.aprender(nuevo, anterior.categoria)
            if n:
                extra = f"También la apliqué a {n} movimiento{'s' if n != 1 else ''} más de «{nuevo.nombre}»."
        self.mov = nuevo
        self.app.mov_cambiado(nuevo)
        self._pintar_cabecera()
        self._mostrar_total(extra)

    def flush(self):
        """Guarda ya mismo si había un guardado pendiente."""
        if self._timer is not None:
            self.after_cancel(self._timer)
            self.guardar()

    def _eliminar(self):
        m = self.mov
        if m.nombre or m.cantidad:
            if not messagebox.askyesno("Eliminar", f"¿Eliminar «{m.nombre or 'sin nombre'}»?\nNo se puede deshacer.",
                                       parent=self.app):
                return
        self.app.eliminar_tarjeta(self)

    def destroy(self):
        if self._timer is not None:
            self.after_cancel(self._timer)
            self._timer = None
        super().destroy()


# ─────────────────────────── tarjeta de deuda ───────────────────────────

class TarjetaDeuda(tk.Frame):
    """Una deuda en cuotas: lo que debés o lo que te deben."""

    def __init__(self, padre, app: App, deuda: Deuda):
        c = app.c
        super().__init__(padre, bg=c["panel"], highlightthickness=1, highlightbackground=c["borde"])
        self.app, self.deuda, self._timer = app, deuda, None
        self.franja = tk.Frame(self, width=5)
        self.franja.pack(side="left", fill="y")
        cuerpo = tk.Frame(self, bg=c["panel"], padx=12, pady=10)
        cuerpo.pack(side="left", fill="both", expand=True)
        f = Formulario(app, cuerpo, self._programar, self.flush)
        d = deuda
        self.v = {
            "tipo": tk.StringVar(value=next(t for t, k in TIPOS_DEUDA if k == d.tipo)),
            "persona": tk.StringVar(value=d.persona),
            "total": tk.StringVar(value=numero(d.total) if d.total else ""),
            "cuotas": tk.StringVar(value=str(d.cuotas)),
            "primera": tk.StringVar(value=f"{d.primera:%d/%m/%Y}"),
            "motivo": tk.StringVar(value=d.motivo),
        }
        f.etiqueta(0, 0, "Tipo")
        f.lista(self.v["tipo"], [t for t, _ in TIPOS_DEUDA], 0, 1)
        Boton(cuerpo, "✕", self._eliminar, c["panel"], c["suave"], c["boton_hover"], padx=6, pady=1).grid(
            row=0, column=3, sticky="e")
        self.l_persona = tk.Label(cuerpo, bg=c["panel"], fg=c["suave"], font=FUENTE_CHICA, anchor="w")
        self.l_persona.grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.entrada_persona = f.campo(self.v["persona"], 1, 1, 3)
        f.etiqueta(2, 0, "Total")
        f.campo(self.v["total"], 2, 1)
        f.etiqueta(2, 2, "Cuotas")
        f.campo(self.v["cuotas"], 2, 3)
        f.etiqueta(3, 0, "1.ª cuota")
        f.campo(self.v["primera"], 3, 1)
        self.l_pagadas_titulo = tk.Label(cuerpo, bg=c["panel"], fg=c["suave"], font=FUENTE_CHICA, anchor="w")
        self.l_pagadas_titulo.grid(row=3, column=2, sticky="w", padx=(0, 8))
        marco = tk.Frame(cuerpo, bg=c["panel"])
        marco.grid(row=3, column=3, sticky="w")
        Boton(marco, "−", lambda: self.cambiar_pagadas(-1), c["boton"], c["texto"], c["boton_hover"],
              padx=8, pady=1).pack(side="left")
        self.l_pagadas = tk.Label(marco, bg=c["panel"], fg=c["texto"], font=FUENTE_NEG, width=3)
        self.l_pagadas.pack(side="left")
        Boton(marco, "+", lambda: self.cambiar_pagadas(1), c["boton"], c["texto"], c["boton_hover"],
              padx=8, pady=1).pack(side="left")
        f.etiqueta(4, 0, "Motivo")
        f.campo(self.v["motivo"], 4, 1, 3)
        self.l_estado = tk.Label(cuerpo, bg=c["panel"], font=FUENTE_NEG, anchor="w", justify="left", wraplength=340)
        self.l_estado.grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 0))
        for var in self.v.values():
            var.trace_add("write", lambda *a: self._programar())
        self._pintar()

    def _pintar(self, error=""):
        c, d = self.app.c, self.deuda
        debo = d.tipo == "debo"
        self.franja.config(bg=c["egreso"] if debo else c["ingreso"])
        self.l_persona.config(text="A quién" if debo else "Quién")
        self.l_pagadas_titulo.config(text="Pagadas" if debo else "Cobradas")
        self.l_pagadas.config(text=str(d.pagadas))
        if error:
            self.l_estado.config(text=f"⚠ {error}", fg=c["error"])
            return
        verbo, verbo_pas = ("pagar", "pagaste") if debo else ("cobrar", "cobraste")
        if d.saldada:
            self.l_estado.config(text=f"Saldada: {verbo_pas} las {d.cuotas} cuotas ({dinero(d.total)}).",
                                 fg=c["ingreso"])
            return
        prox = d.pendientes()[0]
        texto = (f"{d.cuotas} cuota{'s' if d.cuotas != 1 else ''} de {dinero(d.valor_cuota)}. "
                 f"Falta {verbo} {dinero(d.restante())}. Próxima: {prox[1]:%d/%m/%Y}.")
        vencidas = d.vencidas(date.today())
        color = c["egreso"] if debo else c["ingreso"]
        if vencidas:
            texto += (f"\n⚠ {len(vencidas)} cuota{'s' if len(vencidas) != 1 else ''} vencida{'s' if len(vencidas) != 1 else ''}"
                      f" sin {verbo} ({dinero(sum(v[2] for v in vencidas))}).")
            color = c["error"]
        self.l_estado.config(text=texto, fg=color)

    def _leer(self) -> Deuda:
        d = self.deuda
        cuotas = parse_entero(self.v["cuotas"].get(), "Cuotas", 1, 600)
        return Deuda(tipo=next(k for t, k in TIPOS_DEUDA if t == self.v["tipo"].get()),
                     persona=self.v["persona"].get().strip(), total=parse_monto(self.v["total"].get()),
                     cuotas=cuotas, pagadas=min(d.pagadas, cuotas), primera=parse_fecha(self.v["primera"].get()),
                     motivo=self.v["motivo"].get().strip(), id=d.id)

    def _programar(self):
        if self._timer is not None:
            self.after_cancel(self._timer)
        self._timer = self.after(600, self.guardar)

    def guardar(self):
        self._timer = None
        try:
            nueva = self._leer()
        except ValueError as error:
            self._pintar(str(error))
            return
        self.deuda = nueva
        self.app.deuda_cambiada(nueva)
        self._pintar()

    def flush(self):
        if self._timer is not None:
            self.after_cancel(self._timer)
            self.guardar()

    def cambiar_pagadas(self, n):
        self.flush()
        d = self.deuda
        nuevas = max(0, min(d.cuotas, d.pagadas + n))
        if nuevas != d.pagadas:
            d.pagadas = nuevas
            self.app.deuda_cambiada(d)
            self._pintar()

    def _eliminar(self):
        d = self.deuda
        if d.persona or d.total:
            if not messagebox.askyesno("Eliminar", f"¿Eliminar la deuda con «{d.persona or 'sin nombre'}»?\n"
                                                   "No se puede deshacer.", parent=self.app):
                return
        self.app.eliminar_deuda(self)

    def destroy(self):
        if self._timer is not None:
            self.after_cancel(self._timer)
            self._timer = None
        super().destroy()

# ───────────────────────────── gráfico ─────────────────────────────

class Grafico(tk.Canvas):
    """Barras de ingresos y egresos por período, con la línea del saldo (o del balance)."""

    IZQ, DER, ARR, ABA = 62, 18, 42, 34            # márgenes en píxeles

    def __init__(self, padre, c):
        super().__init__(padre, bg=c["panel"], width=520, height=300, highlightthickness=1,
                         highlightbackground=c["borde"])
        self.c = c
        self.puntos: list[Punto] = []
        self.gran = "Mes"
        self.seleccion: date | None = None     # período elegido (se resalta)
        self.nombre_linea = "Saldo en cuenta"  # o "Balance del período" si no cargaste tu saldo real
        self.al_elegir = None                  # función a llamar cuando se hace clic en un período
        self._geo = None
        self.bind("<Configure>", lambda e: self.dibujar())
        self.bind("<Motion>", self._mover)
        self.bind("<Leave>", lambda e: self.delete("hover"))
        self.bind("<Button-1>", self._clic)

    def mostrar(self, puntos, gran, seleccion=None):
        self.puntos, self.gran, self.seleccion = puntos, gran, seleccion
        self.dibujar()

    def _indice(self, x, y):
        if not self._geo:
            return None
        izq, der, arr, aba, banda = self._geo
        if not (izq <= x <= der and arr <= y <= aba):
            return None
        return min(len(self.puntos) - 1, int((x - izq) / banda))

    def _clic(self, e):
        i = self._indice(e.x, e.y)
        if i is not None and self.al_elegir:
            self.al_elegir(self.puntos[i].inicio)

    def dibujar(self):
        self.delete("all")
        self._geo = None
        ancho, alto, n, c = self.winfo_width(), self.winfo_height(), len(self.puntos), self.c
        if n == 0 or ancho < 260 or alto < 180:
            return
        izq, der, arr, aba = self.IZQ, ancho - self.DER, self.ARR, alto - self.ABA

        valores = [0.0]
        for p in self.puntos:
            valores += [p.ingresos, p.egresos] + ([p.acumulado] if p.acumulado is not None else [])
        vmin, vmax = min(valores), max(valores)
        if vmax - vmin < 1e-9:
            vmax = vmin + 1000
        marcas = ticks_agradables(vmin, vmax, 5)
        y0, y1 = marcas[0], marcas[-1]
        banda = (der - izq) / n
        self._geo = (izq, der, arr, aba, banda)

        def ypx(valor):
            return arr + (y1 - valor) / (y1 - y0) * (aba - arr)

        def xpx(i):
            return izq + (i + 0.5) * banda

        actual = max((i for i, p in enumerate(self.puntos) if not p.futuro), default=None)

        # zona de proyección (lo que todavía no pasó)
        if actual is not None and actual < n - 1:
            x_fut = izq + (actual + 1) * banda
            self.create_rectangle(x_fut, arr, der, aba, fill=c["fondo"], width=0)
            self.create_text(x_fut + 6, arr - 10, text="proyección", anchor="w", fill=c["suave"], font=FUENTE_CHICA)

        # período elegido (se resalta con una franja)
        elegido = next((i for i, p in enumerate(self.puntos) if p.inicio == self.seleccion), None)
        if elegido is not None and elegido != actual:
            x0 = izq + elegido * banda
            self.create_rectangle(x0, arr, x0 + banda, aba, fill=mezclar(c["acento"], c["panel"], 0.85), width=0)

        # cuadrícula y valores del eje vertical
        for marca in marcas:
            y = ypx(marca)
            self.create_line(izq, y, der, y, fill=c["suave"] if marca == 0 else c["grilla"])
            self.create_text(izq - 8, y, text=dinero_corto(marca), anchor="e", fill=c["suave"], font=FUENTE_CHICA)

        # barras
        ancho_barra = max(2, min(banda * 0.34, 24))
        base = ypx(0)
        for i, p in enumerate(self.puntos):
            x = xpx(i)
            verde = mezclar(c["ingreso"], c["fondo"], 0.5) if p.futuro else c["ingreso"]
            rojo = mezclar(c["egreso"], c["fondo"], 0.5) if p.futuro else c["egreso"]
            if p.ingresos:
                self.create_rectangle(x - ancho_barra - 1, ypx(p.ingresos), x - 1, base, fill=verde, width=0)
            if p.egresos:
                self.create_rectangle(x + 1, ypx(p.egresos), x + ancho_barra + 1, base, fill=rojo, width=0)

        # línea (punteada en la proyección; sin dibujar donde no hay datos para saberla)
        for i in range(n - 1):
            este, siguiente = self.puntos[i], self.puntos[i + 1]
            if este.acumulado is None or siguiente.acumulado is None:
                continue
            self.create_line(xpx(i), ypx(este.acumulado), xpx(i + 1), ypx(siguiente.acumulado),
                             fill=c["saldo"], width=2, dash=(5, 3) if siguiente.futuro else "")
        radio = 3.5 if n <= 24 else 2.5
        for i, p in enumerate(self.puntos):
            if p.acumulado is None:
                continue
            x, y = xpx(i), ypx(p.acumulado)
            self.create_oval(x - radio, y - radio, x + radio, y + radio, fill=c["saldo"], outline=c["panel"])

        # marca del período actual
        if actual is not None:
            x = xpx(actual)
            self.create_line(x, arr, x, aba, fill=c["acento"], dash=(2, 4))
            self.create_text(x - 4, arr - 10, text="hoy" if self.gran == "Día" else "actual", anchor="e",
                             fill=c["acento"], font=FUENTE_CHICA)

        # nombres del eje horizontal (salteando los que no entran)
        paso = max(1, math.ceil(52 / banda))
        for i in range(actual % paso if actual is not None else 0, n, paso):
            self.create_text(xpx(i), aba + 8, text=etiqueta_eje(self.puntos[i].inicio, self.gran), anchor="n",
                             fill=c["suave"], font=FUENTE_CHICA)

        # leyenda
        x = izq
        for texto, color in (("Ingresos", c["ingreso"]), ("Egresos", c["egreso"]), (self.nombre_linea, c["saldo"])):
            self.create_rectangle(x, 9, x + 10, 19, fill=color, width=0)
            t = self.create_text(x + 15, 14, text=texto, anchor="w", fill=c["texto"], font=FUENTE_CHICA)
            x = self.bbox(t)[2] + 20

    def _mover(self, e):
        """Al pasar el mouse muestra los números del período."""
        self.delete("hover")
        i = self._indice(e.x, e.y)
        if i is None:
            return
        izq, der, arr, aba, banda = self._geo
        p, c = self.puntos[i], self.c
        cx = izq + (i + 0.5) * banda
        self.create_line(cx, arr, cx, aba, fill=c["suave"], tags="hover")
        lineas = [nombre_periodo(p.inicio, self.gran) + ("  (proyección)" if p.futuro else ""),
                  f"Ingresos: {dinero(p.ingresos)}", f"Egresos: {dinero(p.egresos)}",
                  f"{self.nombre_linea}: " + (dinero(p.acumulado) if p.acumulado is not None
                                              else "sin datos (antes de tus movimientos reales)"),
                  "Clic para ver este período"]
        texto = self.create_text(0, 0, text="\n".join(lineas), anchor="nw", fill=c["texto"], font=FUENTE_CHICA,
                                 tags="hover")
        x0, y0, x1, y1 = self.bbox(texto)
        ancho, alto = x1 - x0, y1 - y0
        px = e.x + 14 if e.x + 14 + ancho + 14 < self.winfo_width() else e.x - 14 - ancho - 12
        py = min(max(e.y - alto / 2, arr), aba - alto - 10)
        self.coords(texto, px + 6, py + 5)
        self.create_rectangle(px, py, px + ancho + 12, py + alto + 10, fill=c["panel"], outline=c["borde"],
                              tags="hover")
        self.tag_raise(texto)


# ─────────────────────────── gráfico circular ───────────────────────────

class Torta(tk.Canvas):
    """Gráfico circular (dona) con la parte de cada cosa y una leyenda con montos y porcentajes."""

    def __init__(self, padre, app):
        c = app.c
        super().__init__(padre, bg=c["panel"], width=520, height=300, highlightthickness=1,
                         highlightbackground=c["borde"])
        self.app, self.c = app, c
        self.partes: list[tuple[str, float]] = []
        self.vacio = ""
        self.bind("<Configure>", lambda e: self.dibujar())

    def mostrar(self, partes, vacio):
        self.partes, self.vacio = partes, vacio
        self.dibujar()

    def colores(self):
        paleta = PALETA_TORTA[self.app.tema]
        return [self.c["suave"] if nombre.startswith("Otros (") else paleta[i % len(paleta)]
                for i, (nombre, _) in enumerate(self.partes)]

    def dibujar(self):
        self.delete("all")
        ancho, alto, c = self.winfo_width(), self.winfo_height(), self.c
        if ancho < 260 or alto < 160:
            return
        total = sum(v for _, v in self.partes)
        if total <= 0:
            self.create_text(ancho / 2, alto / 2, text=self.vacio, fill=c["suave"], font=FUENTE, justify="center",
                             width=ancho - 40)
            return

        # la dona
        diametro = max(120, min(alto - 48, ancho * 0.42))
        radio = diametro / 2
        cx, cy = 24 + radio, alto / 2
        caja = (cx - radio, cy - radio, cx + radio, cy + radio)
        colores = self.colores()
        if len(self.partes) == 1:
            self.create_oval(*caja, fill=colores[0], outline=c["panel"], width=2)
        else:
            angulo = 90.0                                       # arranca arriba y gira en sentido horario
            for (_nombre, valor), color in zip(self.partes, colores):
                extension = -360.0 * valor / total
                if abs(extension) >= 0.05:
                    self.create_arc(*caja, start=angulo, extent=extension, style="pieslice", fill=color,
                                    outline=c["panel"], width=2)
                angulo += extension
        hueco = radio * 0.58
        self.create_oval(cx - hueco, cy - hueco, cx + hueco, cy + hueco, fill=c["panel"], outline=c["panel"])
        self.create_text(cx, cy - 9, text=dinero(total), fill=c["texto"], font=FUENTE_NEG)
        self.create_text(cx, cy + 11, text="en total", fill=c["suave"], font=FUENTE_CHICA)

        # la leyenda: color, nombre, monto y porcentaje
        x0 = cx + radio + 30
        fila = 30 if alto >= 40 + 30 * len(self.partes) else 24
        y = cy - fila * len(self.partes) / 2 + fila / 2
        x_pct, x_monto = ancho - 16, ancho - 70
        lugar_nombre = max(40, x_monto - 112 - (x0 + 18))
        for (nombre, valor), color in zip(self.partes, colores):
            self.create_rectangle(x0, y - 6, x0 + 12, y + 6, fill=color, width=0)
            maximo = max(4, int(lugar_nombre / 7.2))
            texto = nombre if len(nombre) <= maximo else nombre[:maximo - 1].rstrip() + "…"
            self.create_text(x0 + 20, y, text=texto, anchor="w", fill=c["texto"], font=FUENTE)
            self.create_text(x_monto, y, text=dinero(valor), anchor="e", fill=c["suave"], font=FUENTE_CHICA)
            self.create_text(x_pct, y, text=f"{valor / total * 100:.1f} %".replace(".", ","), anchor="e",
                             fill=c["texto"], font=FUENTE_NEG)
            y += fila




# ─────────────────────────── balance general ───────────────────────────

class VistaBalance(tk.Canvas):
    """Balance general al estilo contable: ACTIVO, PASIVO y PATRIMONIO NETO, con los montos de cada
    rubro en una columna y el total de cada sección en la de la derecha."""

    MAX_FILAS = 5                          # por sección; el resto se junta en "Otros"

    def __init__(self, padre, app):
        c = app.c
        super().__init__(padre, bg=c["panel"], width=520, height=300, highlightthickness=1,
                         highlightbackground=c["borde"])
        self.app, self.c = app, c
        self.datos: BalanceGeneral | None = None
        self.bind("<Configure>", lambda e: self.dibujar())

    def mostrar(self, datos: BalanceGeneral):
        self.datos = datos
        self.dibujar()

    @staticmethod
    def _recortar(items, otros):
        if len(items) <= VistaBalance.MAX_FILAS:
            return items
        resto = items[VistaBalance.MAX_FILAS - 1:]
        return items[:VistaBalance.MAX_FILAS - 1] + [(f"{otros} ({len(resto)})", round(sum(v for _, v in resto), 2))]

    def dibujar(self):
        self.delete("all")
        ancho, alto, c, b = self.winfo_width(), self.winfo_height(), self.c, self.datos
        if b is None or ancho < 300 or alto < 200:
            return
        caja = b.caja if b.caja is not None else 0.0
        secciones = [
            ("ACTIVO", b.activo, [(b.nombre_caja, caja)] +
             [(f"Te debe {n}", v) for n, v in self._recortar(b.creditos, "Otros que te deben")]),
            ("PASIVO", b.pasivo, [(f"Deuda con {n}", v) for n, v in self._recortar(b.deudas, "Otras deudas")]
             or [("Sin deudas", 0.0)]),
            ("PATRIMONIO NETO", b.patrimonio, [("Patrimonio anterior", b.patrimonio_anterior),
                                               ("Resultado del período", b.resultado)]),
        ]
        filas = 2 + sum(1 + len(items) for _, _, items in secciones) + 2
        paso = max(15, min(25, (alto - 40) / filas))
        izq, sangria = 28, 46
        x_rubro, x_total = ancho * 0.66, ancho - 28
        y = 26

        def monto(x, y, valor, fuente, color=None):
            self.create_text(x, y, text=dinero(valor), anchor="e", font=fuente,
                             fill=color or (c["egreso"] if valor < 0 else c["texto"]))

        self.create_text(izq, y, text=f"BALANCE GENERAL AL {b.dia:%d/%m/%Y}", anchor="w", font=FUENTE_NEG,
                         fill=c["texto"])
        self.create_line(izq, y + paso * 0.6, x_total, y + paso * 0.6, fill=c["borde"])
        y += paso * 1.5
        for titulo, total, items in secciones:
            self.create_text(izq, y, text=titulo, anchor="w", font=FUENTE_NEG, fill=c["texto"])
            monto(x_total, y, total, FUENTE_NEG)
            y += paso
            for i, (nombre, valor) in enumerate(items):
                self.create_text(sangria, y, text=nombre, anchor="w", font=FUENTE, fill=c["texto"])
                if titulo == "ACTIVO" and i == 0 and b.caja is None:
                    self.create_text(x_rubro, y, text="sin datos", anchor="e", font=FUENTE_CHICA, fill=c["suave"])
                else:
                    monto(x_rubro, y, valor, FUENTE)
                y += paso
            # raya de suma debajo del último rubro, como en un balance en papel
            self.create_line(x_rubro - 90, y - paso * 0.45, x_rubro, y - paso * 0.45, fill=c["suave"])
            y += paso * 0.5

        # control: activo = pasivo + patrimonio neto
        self.create_line(izq, y - paso * 0.3, x_total, y - paso * 0.3, fill=c["borde"])
        ok = abs(b.activo - (b.pasivo + b.patrimonio)) < 0.01
        self.create_text(izq, y + paso * 0.3, anchor="w", font=FUENTE_CHICA, fill=c["ingreso"] if ok else c["error"],
                         text=f"{'✓' if ok else '⚠'} Activo {dinero(b.activo)} = Pasivo {dinero(b.pasivo)} + "
                              f"Patrimonio neto {dinero(b.patrimonio)}")
        if b.caja is None:
            self.create_text(izq, y + paso * 1.2, anchor="w", font=FUENTE_CHICA, fill=c["suave"],
                             text="Para la plata del período, cargá tu saldo real o importá tus movimientos.")


# ──────────────────────── importar de Mercado Pago ────────────────────────

class Importador(tk.Toplevel):
    """Ventana para traer movimientos: pegando la actividad o abriendo los resúmenes descargados."""

    def __init__(self, app):
        c = app.c
        super().__init__(app, bg=c["fondo"])
        self.app, self.c, self.filas = app, c, []
        self.saldo_archivo = None           # (día, plata) que informa el archivo, si informa
        self.saldos_archivo: dict = {}      # saldo del banco al cierre de cada día, si el archivo lo trae
        self.title("Importar movimientos")
        self.geometry("820x680")
        self.minsize(660, 540)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.cerrar)

        marco = tk.Frame(self, bg=c["fondo"], padx=20, pady=16)
        marco.pack(fill="both", expand=True)
        tk.Label(marco, text="Importar movimientos", bg=c["fondo"], fg=c["texto"], font=FUENTE_TITULO,
                 anchor="w").pack(fill="x")
        tk.Label(marco, text="Opción 1, todo tu historial: en Mercado Pago descargá el «Resumen de cuenta» de cada "
                             "mes (PDF, .csv o .xlsx) y abrí todos los archivos juntos.\n"
                             "Opción 2, lo último: copiá tu actividad y pegala acá.",
                 bg=c["fondo"], fg=c["suave"], font=FUENTE, anchor="w", justify="left", wraplength=760).pack(
            fill="x", pady=(4, 10))

        self.texto = tk.Text(marco, height=6, wrap="word", bg=c["entrada"], fg=c["texto"],
                             insertbackground=c["texto"], relief="flat", highlightthickness=1,
                             highlightbackground=c["borde"], highlightcolor=c["acento"], font=FUENTE_CHICA,
                             padx=8, pady=6)
        self.texto.pack(fill="x")

        botones = tk.Frame(marco, bg=c["fondo"])
        botones.pack(fill="x", pady=(8, 12))
        Boton(botones, "Abrir resúmenes (PDF, .csv, .xlsx)", self.abrir_archivos, c["acento"], "#ffffff",
              c["acento_hover"]).pack(side="left")
        Boton(botones, "Pegar del portapapeles", self.pegar, c["boton"], c["texto"], c["boton_hover"]).pack(
            side="left", padx=(8, 0))
        Boton(botones, "Leer texto", self.leer, c["boton"], c["texto"], c["boton_hover"]).pack(
            side="left", padx=(8, 0))
        Boton(botones, "Borrar", self.borrar, c["fondo"], c["suave"], c["boton_hover"]).pack(side="right")

        marcar = tk.Frame(marco, bg=c["fondo"])
        marcar.pack(fill="x", pady=(0, 6))
        Boton(marcar, "Marcar todo", lambda: self.marcar_todo(True), c["boton"], c["texto"], c["boton_hover"],
              fuente=FUENTE_CHICA, padx=10, pady=3).pack(side="left")
        Boton(marcar, "Desmarcar todo", lambda: self.marcar_todo(False), c["boton"], c["texto"], c["boton_hover"],
              fuente=FUENTE_CHICA, padx=10, pady=3).pack(side="left", padx=(6, 0))
        Boton(marcar, "Solo egresos", lambda: self.marcar_tipo("egreso"), c["boton"], c["texto"], c["boton_hover"],
              fuente=FUENTE_CHICA, padx=10, pady=3).pack(side="left", padx=(16, 0))
        Boton(marcar, "Solo ingresos", lambda: self.marcar_tipo("ingreso"), c["boton"], c["texto"], c["boton_hover"],
              fuente=FUENTE_CHICA, padx=10, pady=3).pack(side="left", padx=(6, 0))
        self.lista = ListaScroll(marco, c, "Abrí tus resúmenes o pegá el texto para ver las operaciones.", ancho=760)
        self.lista.pack(fill="both", expand=True)
        self.lista.actualizar_vacio()

        pie = tk.Frame(marco, bg=c["fondo"])
        pie.pack(fill="x", pady=(12, 0))
        self.l_resumen = tk.Label(pie, text="", bg=c["fondo"], fg=c["texto"], font=FUENTE_CHICA, anchor="w",
                                  justify="left", wraplength=560)
        self.l_resumen.pack(side="left", fill="x", expand=True)
        Boton(pie, "Cancelar", self.cerrar, c["boton"], c["texto"], c["boton_hover"]).pack(side="right")
        self.b_importar = Boton(pie, "Importar", self.importar, c["acento"], "#ffffff", c["acento_hover"])
        self.b_importar.pack(side="right", padx=(0, 8))
        self.b_ir = Boton(pie, "Ver ese mes", self.ir_a_lo_leido, c["boton"], c["acento"], c["boton_hover"])
        self.repetidas: list[bool] = []
        self.todo_cargado = False
        self.texto.focus_set()

    def cerrar(self):
        self.app._importador = None
        self.destroy()

    def _aviso(self, texto):
        self.l_resumen.config(text=texto, fg=self.c["aviso"])

    def borrar(self):
        self.texto.delete("1.0", "end")
        self.saldo_archivo = None
        self._mostrar([])
        self.l_resumen.config(text="")

    def pegar(self):
        try:
            contenido = self.clipboard_get()
        except tk.TclError:
            self._aviso("El portapapeles está vacío. Copiá la actividad de Mercado Pago primero.")
            return
        self.texto.delete("1.0", "end")
        self.texto.insert("1.0", contenido)
        self.leer()

    def leer(self):
        self.saldo_archivo = None
        self.saldos_archivo = {}
        texto = self.texto.get("1.0", "end")
        resumen = leer_texto_resumen(texto)            # ¿es un resumen de cuenta copiado (con saldos)?
        if resumen is not None and resumen.ops:
            self.saldos_archivo = resumen.saldos
            self._mostrar(resumen.ops)
            partes = [self.l_resumen.cget("text")] + [f"✓ {v}." for v in resumen.verificado] + resumen.errores
            self.l_resumen.config(text="\n".join(partes),
                                  fg=self.c["aviso"] if resumen.errores else self.c["texto"])
            return
        ops = leer_mercadopago(texto)
        self._mostrar(ops)
        if not ops and self.texto.get("1.0", "end").strip():
            self._aviso("No encontré operaciones. Asegurate de copiar también los montos (por ejemplo -$4.000).")

    def abrir_archivos(self):
        rutas = filedialog.askopenfilenames(
            parent=self, title="Elegí tus resúmenes de cuenta",
            filetypes=[("Resúmenes (.pdf, .csv, .xlsx)", "*.pdf *.csv *.xlsx"), ("Todos los archivos", "*.*")])
        if not rutas:
            return
        lectura = leer_archivos(rutas)
        self.saldo_archivo = lectura.saldo
        self.saldos_archivo = lectura.saldos
        if lectura.titular and not self.app.titular:
            self.app.guardar_titular(lectura.titular)
        self._mostrar(lectura.ops)
        partes = [self.l_resumen.cget("text")] if lectura.ops else []
        partes += [f"✓ {v}." for v in lectura.verificado] + lectura.errores
        self.l_resumen.config(text="\n".join(partes), fg=self.c["aviso"] if lectura.errores else self.c["texto"])

    def _mostrar(self, ops):
        c = self.c
        self.lista.limpiar()
        self.filas = []
        repetidas = marcar_repetidas(ops, self.app.movs)
        self.repetidas = repetidas
        for op, repetida in zip(ops, repetidas):
            propia = es_propia(op, self.app.titular)
            if repetida:
                nota = "Ya está cargada"
            elif propia:
                nota = ""                            # entre tus cuentas: se cuenta (categoría "Entre mis cuentas")
            elif op.interna:
                nota = "Movimiento entre tu cuenta y tus reservas o inversiones: no es ingreso ni gasto"
            elif op.anulada_por is not None and op.es_devolucion:
                nota = "Te devuelve un pago cancelado: no es un ingreso"
            elif op.anulada_por is not None:
                nota = f"{op.estado or 'No cobrado'} y devuelto: no cuenta"
            elif not op.aprobada:
                nota = f"{op.estado or 'Monto tachado'}: no se cobró"
            else:
                nota = ""
            mov = op.a_movimiento(self.app.aprendidas)
            if propia:
                mov.categoria = ENTRE_MIS_CUENTAS
            var = tk.BooleanVar(value=op.cuenta and not repetida)
            fila = tk.Frame(self.lista.interior, bg=c["panel"], highlightthickness=1, highlightbackground=c["borde"],
                            padx=8, pady=6)
            fila.pack(fill="x", pady=(0, 4))
            fila.grid_columnconfigure(2, weight=1)
            tk.Checkbutton(fila, variable=var, command=self._resumir, bg=c["panel"], activebackground=c["panel"],
                           selectcolor=c["entrada"], fg=c["texto"], activeforeground=c["texto"],
                           highlightthickness=0, bd=0, cursor="hand2").grid(row=0, column=0, rowspan=2, sticky="n")
            tk.Label(fila, text=f"{op.fecha:%d/%m/%Y}  {op.hora}".strip(), bg=c["panel"], fg=c["suave"],
                     font=FUENTE_CHICA, width=16, anchor="w").grid(row=0, column=1, sticky="w", padx=(4, 8))
            tk.Label(fila, text=op.nombre, bg=c["panel"], fg=c["texto"], font=FUENTE_NEG, anchor="w").grid(
                row=0, column=2, sticky="w")
            detalle = ", ".join(x for x in (op.detalle, op.medio, mov.categoria) if x)
            tk.Label(fila, text=detalle + (f"   {nota}" if nota else ""), bg=c["panel"],
                     fg=c["aviso"] if nota else c["suave"], font=FUENTE_CHICA, anchor="w").grid(
                row=1, column=2, sticky="w")
            signo = "-" if op.tipo == "egreso" else "+"
            tk.Label(fila, text=f"{signo}{dinero(abs(op.monto))}", bg=c["panel"],
                     fg=c["egreso"] if op.tipo == "egreso" else c["ingreso"], font=FUENTE_NEG).grid(
                row=0, column=3, rowspan=2, sticky="e")
            self.filas.append((var, op, mov))
        # "todo cargado": hay repetidas y no queda nada nuevo que cuente (lo interno no se importa igual)
        self.todo_cargado = any(repetidas) and not any(var.get() for var, _, _ in self.filas)
        self.lista.actualizar_vacio()
        self.lista.al_inicio()
        self._resumir()

    def elegidas(self):
        return [op for var, op, _ in self.filas if var.get()]

    def marcar_todo(self, valor: bool):
        """Marca o desmarca todas las operaciones (también las repetidas o internas: la decisión es tuya)."""
        for var, _, _ in self.filas:
            var.set(valor)
        self._resumir()

    def marcar_tipo(self, tipo: str):
        """Deja marcadas solo las de un tipo (de las que ya estaban marcadas)."""
        for var, op, _ in self.filas:
            if op.tipo != tipo:
                var.set(False)
        self._resumir()

    def _resumir(self):
        elegidas = [(op, mov) for var, op, mov in self.filas if var.get()]
        self.b_importar.config(text=f"Importar {len(elegidas)}" if elegidas else "Importar")
        if not self.filas:
            return
        ing = sum(op.monto for op, _ in elegidas if op.tipo == "ingreso")
        egr = -sum(op.monto for op, _ in elegidas if op.tipo == "egreso")
        desde = min(op.fecha for _, op, _ in self.filas)
        hasta = max(op.fecha for _, op, _ in self.filas)
        texto = (f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}: encontré {len(self.filas)} operaciones y marqué "
                 f"{len(elegidas)}. Ingresos {dinero(ing)}, egresos {dinero(egr)}.")
        mes = nombre_periodo(hasta.replace(day=1), "Mes")
        if (date.today() - hasta).days > 180:
            texto += (f"\nOjo: son movimientos de {mes}, de hace más de 6 meses. Si buscabas un mes reciente, "
                      "en Mercado Pago generá el resumen eligiendo el año correcto.")
        if self.todo_cargado:
            texto += f"\nTodo esto ya está cargado en la app. Para verlo, andá a {mes}."
            self.b_ir.config(text=f"Ver {mes}")
            self.b_ir.pack(side="right", padx=(0, 8))
        else:
            self.b_ir.pack_forget()
        self.l_resumen.config(fg=self.c["texto"], text=texto)

    def ir_a_lo_leido(self):
        """Cierra y muestra el mes más reciente de lo que se leyó (útil cuando ya estaba todo cargado)."""
        if self.filas:
            hasta = max(op.fecha for _, op, _ in self.filas)
            self.cerrar()
            self.app.ir_a_mes(hasta.replace(day=1))

    def importar(self):
        elegidas = [mov for var, _, mov in self.filas if var.get()]
        if not elegidas and self.todo_cargado:
            self._aviso("No hay nada nuevo para importar: todo ya está cargado. Tocá «Ver …» para ir a ese mes.")
            return
        if not elegidas:
            self._aviso("Marcá al menos una operación para importar.")
            return
        saldos = self.saldos_archivo
        self.app.importar(elegidas)
        self.cerrar()
        if saldos:
            self.app.guardar_saldos_banco(saldos)


# ─────────────────────────── saldo real ───────────────────────────

class DialogoSaldo(tk.Toplevel):
    """Ventanita para cargar cuánta plata tenés de verdad (y en qué día)."""

    def __init__(self, app, sugerido: tuple[date, float] | None = None):
        c = app.c
        super().__init__(app, bg=c["fondo"])
        self.app = app
        self.title("Tu saldo real")
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        marco = tk.Frame(self, bg=c["fondo"], padx=22, pady=18)
        marco.pack(fill="both", expand=True)
        tk.Label(marco, text="¿Cuánta plata tenés?", bg=c["fondo"], fg=c["texto"], font=FUENTE_TITULO,
                 anchor="w").pack(fill="x")
        tk.Label(marco, text="Poné la plata que tenés en las cuentas que cargás en la app (por ejemplo, Mercado Pago "
                             "con tus reservas). Desde ese día la app suma lo que entra y resta lo que sale, hacia "
                             "adelante y hacia atrás.",
                 bg=c["fondo"], fg=c["suave"], font=FUENTE, justify="left", wraplength=380, anchor="w").pack(
            fill="x", pady=(4, 12))
        if sugerido:
            tk.Label(marco, text=f"Según el resumen, el {sugerido[0]:%d/%m/%Y} tenías {dinero(sugerido[1])} disponibles "
                                 "en Mercado Pago. Si además tenés plata en reservas o dólares dentro de Mercado "
                                 "Pago, sumala antes de guardar.",
                     bg=c["fondo"], fg=c["aviso"], font=FUENTE, justify="left", wraplength=380, anchor="w").pack(
                fill="x", pady=(0, 12))
        grilla = tk.Frame(marco, bg=c["fondo"])
        grilla.pack(fill="x")
        ancla = sugerido or app.ancla
        self.var_monto = tk.StringVar(value=numero(ancla[1]) if ancla else "")
        self.var_fecha = tk.StringVar(value=f"{(ancla[0] if ancla else date.today()):%d/%m/%Y}")
        for fila, (texto, var) in enumerate((("Plata", self.var_monto), ("Al final del día", self.var_fecha))):
            tk.Label(grilla, text=texto, bg=c["fondo"], fg=c["suave"], font=FUENTE_CHICA, anchor="w").grid(
                row=fila, column=0, sticky="w", padx=(0, 10))
            e = tk.Entry(grilla, textvariable=var, width=18, bg=c["entrada"], fg=c["texto"],
                         insertbackground=c["texto"], relief="flat", highlightthickness=1,
                         highlightbackground=c["borde"], highlightcolor=c["acento"], font=FUENTE)
            e.grid(row=fila, column=1, sticky="w", pady=3, ipady=4)
            e.bind("<Return>", lambda ev: self.guardar())
            if fila == 0:
                self.entrada_monto = e
        self.l_error = tk.Label(marco, text="", bg=c["fondo"], fg=c["error"], font=FUENTE_CHICA, anchor="w")
        self.l_error.pack(fill="x", pady=(6, 0))
        botones = tk.Frame(marco, bg=c["fondo"])
        botones.pack(fill="x", pady=(10, 0))
        Boton(botones, "Guardar", self.guardar, c["acento"], "#ffffff", c["acento_hover"]).pack(side="left")
        Boton(botones, "Cancelar", self.cerrar, c["boton"], c["texto"], c["boton_hover"]).pack(side="left", padx=8)
        if app.ancla:
            Boton(botones, "Quitar saldo real", self.quitar, c["fondo"], c["suave"], c["boton_hover"]).pack(
                side="right")
        self.entrada_monto.focus_set()

    def cerrar(self):
        self.app._dialogo_saldo = None
        self.destroy()

    def guardar(self):
        try:
            monto = parse_monto(self.var_monto.get(), negativo=True)
            fecha = parse_fecha(self.var_fecha.get())
        except ValueError as error:
            self.l_error.config(text=str(error))
            return
        if not self.var_monto.get().strip():
            self.l_error.config(text="Escribí cuánta plata tenés (puede ser 0).")
            return
        self.app.poner_ancla((fecha, monto))
        self.cerrar()

    def quitar(self):
        self.app.poner_ancla(None)
        self.cerrar()




# ─────────────────────────── borrar datos (resetear) ───────────────────────────

class DialogoBorrar(tk.Toplevel):
    """Elegir qué borrar de una vez: lo del período, todos los movimientos, deudas, saldo real, lo aprendido.
    Hay que escribir BORRAR para confirmar. Después se puede deshacer mientras la app siga abierta."""

    def __init__(self, app):
        c = app.c
        super().__init__(app, bg=c["fondo"])
        self.app = app
        self.title("Borrar datos")
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        marco = tk.Frame(self, bg=c["fondo"], padx=22, pady=18)
        marco.pack(fill="both", expand=True)
        tk.Label(marco, text="Borrar datos", bg=c["fondo"], fg=c["texto"], font=FUENTE_TITULO, anchor="w").pack(fill="x")
        tk.Label(marco, text="Elegí qué querés borrar. Vas a poder deshacerlo mientras no cierres la app.",
                 bg=c["fondo"], fg=c["suave"], font=FUENTE, anchor="w", justify="left", wraplength=420).pack(
            fill="x", pady=(4, 12))

        en_periodo = [m for m in app.movs if ocurre_en(m, app.sel, app.gran)]
        periodo = nombre_periodo(app.sel, app.gran)
        self.opciones = {
            "periodo": (f"Movimientos de {periodo[0].lower() + periodo[1:]} ({len(en_periodo)})", bool(en_periodo)),
            "movimientos": (f"Todos los movimientos ({len(app.movs)})", bool(app.movs)),
            "deudas": (f"Todas las deudas ({len(app.deudas)})", bool(app.deudas)),
            "saldo": ("Tus saldos reales" + (f" (el que cargaste y {len(app.saldos_banco)} días del banco)"
                                              if app.saldos_banco else (f" ({dinero(app.ancla[1])})" if app.ancla
                                                                        else " (no cargados)")),
                      bool(app.ancla or app.saldos_banco)),
            "aprendido": ("Las categorías que corregiste y tu nombre", bool(app.aprendidas or app.titular)),
        }
        self.vars = {}
        for clave, (texto, hay) in self.opciones.items():
            var = tk.BooleanVar(value=False)
            tk.Checkbutton(marco, text=texto, variable=var, command=self._actualizar, bg=c["fondo"],
                           activebackground=c["fondo"], fg=c["texto"] if hay else c["suave"],
                           activeforeground=c["texto"], selectcolor=c["entrada"], font=FUENTE, anchor="w",
                           highlightthickness=0, bd=0, state="normal" if hay else "disabled",
                           cursor="hand2").pack(fill="x", pady=2)
            self.vars[clave] = var
        self.var_todo = tk.BooleanVar(value=False)
        tk.Checkbutton(marco, text="Todo: empezar de cero (tu contraseña y el modo claro/oscuro se mantienen)",
                       variable=self.var_todo, command=self._todo, bg=c["fondo"], activebackground=c["fondo"],
                       fg=c["egreso"], activeforeground=c["egreso"], selectcolor=c["entrada"], font=FUENTE_NEG,
                       anchor="w", highlightthickness=0, bd=0, cursor="hand2").pack(fill="x", pady=(8, 2))

        tk.Label(marco, text="Para confirmar, escribí BORRAR:", bg=c["fondo"], fg=c["suave"], font=FUENTE_CHICA,
                 anchor="w").pack(fill="x", pady=(14, 2))
        self.var_confirmar = tk.StringVar()
        e = tk.Entry(marco, textvariable=self.var_confirmar, width=20, bg=c["entrada"], fg=c["texto"],
                     insertbackground=c["texto"], relief="flat", highlightthickness=1, highlightbackground=c["borde"],
                     highlightcolor=c["acento"], font=FUENTE)
        e.pack(anchor="w", ipady=4)
        e.bind("<Return>", lambda ev: self.borrar())
        self.l_error = tk.Label(marco, text="", bg=c["fondo"], fg=c["error"], font=FUENTE_CHICA, anchor="w",
                                justify="left", wraplength=420)
        self.l_error.pack(fill="x", pady=(6, 0))
        botones = tk.Frame(marco, bg=c["fondo"])
        botones.pack(fill="x", pady=(10, 0))
        self.b_borrar = Boton(botones, "Borrar", self.borrar, c["egreso"], "#ffffff", mezclar(c["egreso"], "#000000", 0.15))
        self.b_borrar.pack(side="left")
        Boton(botones, "Cancelar", self.cerrar, c["boton"], c["texto"], c["boton_hover"]).pack(side="left", padx=8)

    def _todo(self):
        for clave, var in self.vars.items():
            var.set(self.var_todo.get() and self.opciones[clave][1])
        self._actualizar()

    def _actualizar(self):
        if self.vars["movimientos"].get():
            self.vars["periodo"].set(False)          # "todos" ya incluye los del período
        elegidas = self.elegidas()
        todas = [k for k, (_, hay) in self.opciones.items() if hay and k != "periodo"]
        self.var_todo.set(bool(todas) and all(self.vars[k].get() for k in todas))
        self.l_error.config(text="")
        self.b_borrar.config(text="Borrar" if not elegidas else f"Borrar ({len(elegidas)})")

    def elegidas(self) -> list[str]:
        return [k for k, v in self.vars.items() if v.get() and self.opciones[k][1]]

    def borrar(self):
        elegidas = self.elegidas()
        if not elegidas:
            self.l_error.config(text="Marcá qué querés borrar.")
            return
        if self.var_confirmar.get().strip().upper() != "BORRAR":
            self.l_error.config(text="Escribí BORRAR (en mayúsculas o minúsculas) para confirmar.")
            return
        self.app.resetear(elegidas)
        self.cerrar()

    def cerrar(self):
        self.app._dialogo_borrar = None
        self.destroy()

# ───────────────────────────── aplicación ─────────────────────────────

class App(tk.Tk):
    def __init__(self, bd: Boveda):
        super().__init__()
        self.bd = bd
        self.tema = bd.leer_tema()
        self.c = TEMAS[self.tema]
        self.gran = "Mes"
        self.sel = inicio_periodo(date.today(), self.gran)      # período que se está mirando
        self.panel = "egreso"                                   # "egreso" | "ingreso" | "deudas"
        self.filtro, self.busqueda = "periodo", ""
        self.orden = "fecha_desc"
        self.monto_min: float | None = None
        self.monto_max: float | None = None
        self._timer_montos = None
        self.vista = "evolucion"                                # "evolucion" | "distribucion"
        self.torta_tipo, self.torta_por = "egreso", "categoria"
        self.movs: list[Movimiento] = []
        self.deudas: list[Deuda] = []
        self.ancla: tuple[date, float] | None = None          # el saldo que cargaste a mano
        self.saldos_banco: dict[date, float] = {}               # saldo del banco al cierre de cada día
        self.aprendidas: dict[str, str] = {}
        self.titular = ""                                       # tu nombre, para reconocer transferencias propias
        self.tarjetas: list[Tarjeta] = []
        self.tarjetas_deuda: list[TarjetaDeuda] = []
        self._importador: Importador | None = None
        self._dialogo_saldo: DialogoSaldo | None = None
        self._dialogo_borrar: DialogoBorrar | None = None
        self.modo_seleccion = False                             # lista con casillas para borrar varios
        self.seleccionados: set[int] = set()
        self._deshacer: dict | None = None                      # lo último que se borró (para deshacer)
        self._timer_busqueda = None
        self._estimados: list[Movimiento] = []

        self.title("Gestor de Finanzas")
        ancho_pantalla, alto_pantalla = self.winfo_screenwidth(), self.winfo_screenheight()
        ancho, alto = min(1240, ancho_pantalla - 60), min(780, alto_pantalla - 110)
        self.geometry(f"{ancho}x{alto}+{(ancho_pantalla - ancho) // 2}+{max(0, (alto_pantalla - alto) // 2 - 20)}")
        self.minsize(min(1020, ancho), min(640, alto))
        for evento in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(evento, self._rueda)
        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self._pantalla_clave()

    # ── infraestructura ──
    def report_callback_exception(self, tipo, valor, tb):
        """Si algo falla dentro de un botón, lo muestra en una ventana (la app empaquetada no tiene consola)."""
        if sys.stderr:
            traceback.print_exception(tipo, valor, tb)
        messagebox.showerror("Error inesperado", f"{tipo.__name__}: {valor}")

    def _estilos(self):
        c = self.c
        self.configure(bg=c["fondo"])
        estilo = ttk.Style(self)
        estilo.theme_use("clam")
        estilo.configure("TCombobox", fieldbackground=c["entrada"], background=c["boton"], foreground=c["texto"],
                         arrowcolor=c["texto"], bordercolor=c["borde"], lightcolor=c["entrada"],
                         darkcolor=c["entrada"], selectbackground=c["entrada"], selectforeground=c["texto"],
                         insertcolor=c["texto"])
        estilo.map("TCombobox", fieldbackground=[("readonly", c["entrada"])], foreground=[("readonly", c["texto"])],
                   selectbackground=[("readonly", c["entrada"])], selectforeground=[("readonly", c["texto"])])
        estilo.configure("Vertical.TScrollbar", background=c["borde"], troughcolor=c["fondo"],
                         bordercolor=c["fondo"], arrowcolor=c["texto"], lightcolor=c["borde"], darkcolor=c["borde"])
        estilo.map("Vertical.TScrollbar", background=[("active", c["suave"])])
        self.option_add("*TCombobox*Listbox.background", c["entrada"])
        self.option_add("*TCombobox*Listbox.foreground", c["texto"])
        self.option_add("*TCombobox*Listbox.selectBackground", c["acento"])
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    def _limpiar(self):
        for w in self.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        self.tarjetas, self.tarjetas_deuda = [], []

    def _rueda(self, evento):
        """Rueda del mouse: mueve la lista que está debajo del puntero."""
        try:
            w = self.winfo_containing(evento.x_root, evento.y_root)
        except (KeyError, tk.TclError):
            return
        while w is not None:
            if isinstance(w, ListaScroll):
                w.desplazar(evento)
                return
            w = getattr(w, "master", None)

    def _guardar_pendientes(self):
        for t in self.tarjetas:
            t.flush()
        for t in self.tarjetas_deuda:
            t.flush()

    def _cerrar_ventanas(self):
        if self._importador is not None:
            self._importador.cerrar()
        if self._dialogo_borrar is not None:
            self._dialogo_borrar.cerrar()
        if self._dialogo_saldo is not None:
            self._dialogo_saldo.cerrar()

    def _cerrar(self):
        self._cerrar_ventanas()
        self._guardar_pendientes()
        self.bd.cerrar()
        self.destroy()

    # ── pantalla de contraseña ──
    def _pantalla_clave(self):
        self._estilos()
        self._limpiar()
        c, nueva = self.c, self.bd.es_nueva
        caja = tk.Frame(self, bg=c["panel"], highlightthickness=1, highlightbackground=c["borde"], padx=34, pady=30)
        caja.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(caja, text="Gestor de Finanzas", bg=c["panel"], fg=c["texto"], font=FUENTE_TITULO).pack()
        aviso = ("Creá una contraseña para proteger tus datos.\nSi la olvidás, no se pueden recuperar."
                 if nueva else "Escribí tu contraseña para abrir tus datos.")
        tk.Label(caja, text=aviso, bg=c["panel"], fg=c["suave"], font=FUENTE, justify="center").pack(pady=(6, 18))
        self.var_clave, self.var_clave2 = tk.StringVar(), tk.StringVar()
        primero = self._campo_clave(caja, "Contraseña", self.var_clave)
        if nueva:
            self._campo_clave(caja, "Repetí la contraseña", self.var_clave2)
        self.l_error = tk.Label(caja, text="", bg=c["panel"], fg=c["error"], font=FUENTE_CHICA, wraplength=280)
        self.l_error.pack()
        Boton(caja, "Crear contraseña y entrar" if nueva else "Abrir", self._entrar, c["acento"], "#ffffff",
              c["acento_hover"], pady=8).pack(fill="x", pady=(10, 0))
        primero.focus_set()

    def _campo_clave(self, caja, texto, var):
        c = self.c
        tk.Label(caja, text=texto, bg=c["panel"], fg=c["suave"], font=FUENTE_CHICA, anchor="w").pack(fill="x")
        e = tk.Entry(caja, textvariable=var, show="•", width=30, bg=c["entrada"], fg=c["texto"],
                     insertbackground=c["texto"], relief="flat", highlightthickness=1,
                     highlightbackground=c["borde"], highlightcolor=c["acento"], font=FUENTE)
        e.pack(fill="x", ipady=5, pady=(2, 10))
        e.bind("<Return>", lambda ev: self._entrar())
        return e

    def _error(self, texto):
        self.l_error.config(text=texto, fg=self.c["error"])

    def _entrar(self):
        clave = self.var_clave.get()
        if self.bd.es_nueva:
            if len(clave) < 6:
                self._error("Usá al menos 6 caracteres.")
                return
            if clave != self.var_clave2.get():
                self._error("Las contraseñas no coinciden. Escribilas de nuevo.")
                return
        elif not clave:
            self._error("Escribí tu contraseña.")
            return
        self.l_error.config(text="Verificando…", fg=self.c["suave"])
        self.update_idletasks()
        try:
            self.bd.desbloquear(clave)
        except ClaveIncorrecta:
            self.var_clave.set("")
            self._error("La contraseña no es correcta. Probá de nuevo.")
            return
        self.movs = self.bd.listar()
        self.deudas = self.bd.listar_deudas()
        self.ancla = self.bd.leer_ancla()
        self.saldos_banco = {date.fromisoformat(k): float(v)
                             for k, v in (self.bd.leer_config("saldos_banco", {}) or {}).items()}
        self.aprendidas = self.bd.leer_config("aprendidas", {}) or {}
        self.titular = self.bd.leer_config("titular", "") or ""
        self._categorizar_viejos()
        self._construir()

    def _categorizar_viejos(self):
        """Los movimientos de versiones anteriores no tenían categoría: se les sugiere una (una sola vez)."""
        cambiados = []
        for m in self.movs:
            if not m.categoria and m.nombre:
                sugerida = categorizar(m.nombre, m.motivo, m.tipo, self.aprendidas)
                if sugerida not in ("Otros gastos", "Otros ingresos"):
                    m.categoria = sugerida
                    cambiados.append(m)
        if cambiados:
            self.bd.actualizar_varios(cambiados)

    # ── pantalla principal ──
    def _construir(self):
        self._estilos()
        self._limpiar()
        c = self.c

        encabezado = tk.Frame(self, bg=c["fondo"])
        encabezado.pack(fill="x", padx=20, pady=(16, 10))
        tk.Label(encabezado, text="Gestor de Finanzas", bg=c["fondo"], fg=c["texto"], font=FUENTE_TITULO).pack(
            side="left")
        Boton(encabezado, "☀  Modo claro" if self.tema == "oscuro" else "☾  Modo oscuro", self.alternar_tema,
              c["boton"], c["texto"], c["boton_hover"]).pack(side="right")
        Boton(encabezado, "Importar movimientos", self.abrir_importador, c["boton"], c["texto"],
              c["boton_hover"]).pack(side="right", padx=(0, 8))
        Boton(encabezado, "Borrar datos", self.abrir_borrar, c["fondo"], c["suave"], c["boton_hover"]).pack(
            side="right", padx=(0, 8))

        cuerpo = tk.Frame(self, bg=c["fondo"])
        cuerpo.pack(fill="both", expand=True, padx=20, pady=(0, 18))
        cuerpo.grid_columnconfigure(1, weight=1)
        cuerpo.grid_rowconfigure(0, weight=1)
        izquierda = tk.Frame(cuerpo, bg=c["fondo"])
        izquierda.grid(row=0, column=0, sticky="ns", padx=(0, 18))
        derecha = tk.Frame(cuerpo, bg=c["fondo"])
        derecha.grid(row=0, column=1, sticky="nsew")
        self._armar_izquierda(izquierda)
        self._armar_derecha(derecha)
        self._marcar_torta()
        self._elegir_vista(self.vista, refrescar=False)
        self._elegir_gran(self.gran, mantener=True, lista=False)
        self._elegir_panel(self.panel)

    def _armar_izquierda(self, izquierda):
        c = self.c
        fila_tabs = tk.Frame(izquierda, bg=c["fondo"])
        fila_tabs.pack(fill="x", pady=(0, 8))
        self.b_panel = {}
        for clave, texto in (("egreso", "Egresos"), ("ingreso", "Ingresos"), ("deudas", "Deudas")):
            boton = Boton(fila_tabs, texto, lambda k=clave: self._elegir_panel(k), c["boton"], c["suave"],
                          c["boton_hover"], padx=12)
            boton.pack(side="left", padx=(0, 6))
            self.b_panel[clave] = boton
        self.b_mas = Boton(fila_tabs, "+  Nuevo", self._agregar, c["acento"], "#ffffff", c["acento_hover"])
        self.b_mas.pack(side="right")

        # filtros (egresos e ingresos)
        self.zona_filtros = tk.Frame(izquierda, bg=c["fondo"])
        self.var_filtro = tk.StringVar(value=next(t for t, k in FILTROS if k == self.filtro))
        combo = ttk.Combobox(self.zona_filtros, textvariable=self.var_filtro, values=[t for t, _ in FILTROS],
                             state="readonly", width=19, font=FUENTE_CHICA)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda e: self._elegir_filtro(
            next(k for t, k in FILTROS if t == self.var_filtro.get())))
        self.var_busqueda = tk.StringVar(value=self.busqueda)
        buscar = tk.Entry(self.zona_filtros, textvariable=self.var_busqueda, bg=c["entrada"], fg=c["texto"],
                          insertbackground=c["texto"], relief="flat", highlightthickness=1,
                          highlightbackground=c["borde"], highlightcolor=c["acento"], font=FUENTE_CHICA)
        buscar.pack(side="left", fill="x", expand=True, padx=(8, 0), ipady=3)
        self.l_buscar = tk.Label(self.zona_filtros, text="Buscar", bg=c["fondo"], fg=c["suave"], font=FUENTE_CHICA)
        self.l_buscar.pack(side="left", padx=(6, 0))
        Boton(self.zona_filtros, "Seleccionar", self.entrar_seleccion, c["boton"], c["texto"], c["boton_hover"],
              fuente=FUENTE_CHICA, padx=8, pady=3).pack(side="left", padx=(8, 0))

        # segunda fila: ordenar y rango de montos
        self.zona_orden = tk.Frame(izquierda, bg=c["fondo"])
        self.var_orden = tk.StringVar(value=next(t for t, k in ORDENES if k == self.orden))
        combo = ttk.Combobox(self.zona_orden, textvariable=self.var_orden, values=[t for t, _ in ORDENES],
                             state="readonly", width=21, font=FUENTE_CHICA)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda e: self._elegir_orden(
            next(k for t, k in ORDENES if t == self.var_orden.get())))
        tk.Label(self.zona_orden, text="Monto entre", bg=c["fondo"], fg=c["suave"], font=FUENTE_CHICA).pack(
            side="left", padx=(10, 4))
        self.var_min = tk.StringVar(value=numero(self.monto_min) if self.monto_min is not None else "")
        self.var_max = tk.StringVar(value=numero(self.monto_max) if self.monto_max is not None else "")
        self.e_min = self._entrada_monto(self.zona_orden, self.var_min)
        tk.Label(self.zona_orden, text="y", bg=c["fondo"], fg=c["suave"], font=FUENTE_CHICA).pack(side="left", padx=4)
        self.e_max = self._entrada_monto(self.zona_orden, self.var_max)
        self.l_total_lista = tk.Label(izquierda, bg=c["fondo"], fg=c["suave"], font=FUENTE_CHICA, anchor="w")

        # barra del modo selección (borrar varios)
        self.zona_seleccion = tk.Frame(izquierda, bg=c["fondo"])
        self.l_sel = tk.Label(self.zona_seleccion, bg=c["fondo"], fg=c["texto"], font=FUENTE_NEG, anchor="w")
        self.l_sel.pack(side="left")
        Boton(self.zona_seleccion, "Listo", self.salir_seleccion, c["boton"], c["texto"], c["boton_hover"],
              fuente=FUENTE_CHICA, padx=8, pady=3).pack(side="right")
        Boton(self.zona_seleccion, "Borrar", self.borrar_seleccionados, c["egreso"], "#ffffff",
              mezclar(c["egreso"], "#000000", 0.15), fuente=FUENTE_CHICA, padx=10, pady=3).pack(side="right", padx=(0, 6))
        Boton(self.zona_seleccion, "Ninguno", self.seleccionar_ninguno, c["boton"], c["texto"], c["boton_hover"],
              fuente=FUENTE_CHICA, padx=8, pady=3).pack(side="right", padx=(0, 6))
        self.b_sel_todos = Boton(self.zona_seleccion, "Todos", self.seleccionar_visibles, c["boton"], c["texto"],
                                 c["boton_hover"], fuente=FUENTE_CHICA, padx=8, pady=3)
        self.b_sel_todos.pack(side="right", padx=(0, 6))
        self.var_busqueda.trace_add("write", lambda *a: self._programar_busqueda())

        # resumen de deudas
        self.zona_deudas = tk.Frame(izquierda, bg=c["panel"], highlightthickness=1, highlightbackground=c["borde"],
                                    padx=14, pady=10)
        self.l_deuda_mes = tk.Label(self.zona_deudas, bg=c["panel"], fg=c["texto"], font=FUENTE_NEG, anchor="w")
        self.l_deuda_mes.pack(fill="x")
        self.l_deuda_pagar = tk.Label(self.zona_deudas, bg=c["panel"], fg=c["egreso"], font=FUENTE, anchor="w")
        self.l_deuda_pagar.pack(fill="x")
        self.l_deuda_cobrar = tk.Label(self.zona_deudas, bg=c["panel"], fg=c["ingreso"], font=FUENTE, anchor="w")
        self.l_deuda_cobrar.pack(fill="x")
        self.l_deuda_total = tk.Label(self.zona_deudas, bg=c["panel"], fg=c["suave"], font=FUENTE_CHICA, anchor="w",
                                      justify="left", wraplength=360)
        self.l_deuda_total.pack(fill="x", pady=(6, 0))

        self.lista = ListaScroll(izquierda, c, "")
        self.lista.pack(fill="both", expand=True)

    def _armar_derecha(self, derecha):
        c = self.c
        selector = tk.Frame(derecha, bg=c["fondo"])
        selector.pack(fill="x", pady=(0, 10))
        tk.Label(selector, text="Ver por", bg=c["fondo"], fg=c["suave"], font=FUENTE).pack(side="left", padx=(0, 10))
        self.b_gran = {}
        for g in GRANULARIDADES:
            boton = Boton(selector, g, lambda g=g: self._elegir_gran(g), c["boton"], c["texto"], c["boton_hover"],
                          padx=12, pady=4)
            boton.pack(side="left", padx=(0, 6))
            self.b_gran[g] = boton

        resumen = tk.Frame(derecha, bg=c["panel"], highlightthickness=1, highlightbackground=c["borde"],
                           padx=18, pady=14)
        resumen.pack(fill="x", pady=(0, 12))
        cabecera = tk.Frame(resumen, bg=c["panel"])
        cabecera.pack(fill="x")
        Boton(cabecera, "◀", lambda: self.mover_periodo(-1), c["boton"], c["texto"], c["boton_hover"],
              padx=8, pady=1).pack(side="left")
        self.l_periodo = tk.Label(cabecera, bg=c["panel"], fg=c["texto"], font=FUENTE_NEG)
        self.l_periodo.pack(side="left", padx=8)
        Boton(cabecera, "▶", lambda: self.mover_periodo(1), c["boton"], c["texto"], c["boton_hover"],
              padx=8, pady=1).pack(side="left")
        self.l_actual = tk.Label(cabecera, bg=c["panel"], fg=c["suave"], font=FUENTE_CHICA)
        self.l_actual.pack(side="left", padx=(10, 0))
        self.var_ir = tk.StringVar(value="Ir a un mes con datos")
        self.combo_ir = ttk.Combobox(cabecera, textvariable=self.var_ir, values=[], state="readonly", width=24,
                                     font=FUENTE_CHICA)
        self.combo_ir.pack(side="right")
        self.combo_ir.bind("<<ComboboxSelected>>", lambda e: self._ir_seleccionado())
        self._meses_ir: dict[str, date] = {}
        self.b_hoy = Boton(cabecera, "Volver a hoy", self.volver_a_hoy, c["panel"], c["acento"], c["boton_hover"],
                           fuente=FUENTE_CHICA, padx=6, pady=1)
        cifras = tk.Frame(resumen, bg=c["panel"])
        cifras.pack(fill="x", pady=(8, 10))
        self.v_ing = self._cifra(cifras, 0, "Ingresos", c["ingreso"])
        self.v_egr = self._cifra(cifras, 1, "Egresos", c["egreso"])
        self.v_bal = self._cifra(cifras, 2, "Balance", c["texto"])
        self.l_arrastre = tk.Label(resumen, bg=c["panel"], fg=c["texto"], font=FUENTE, anchor="w", justify="left",
                                   wraplength=620)
        self.l_arrastre.pack(fill="x", pady=(0, 8))
        self.progreso = Barra(resumen, c)
        self.progreso.pack(fill="x")
        self.l_ratio = tk.Label(resumen, bg=c["panel"], fg=c["texto"], font=FUENTE, anchor="w", justify="left",
                                wraplength=620)
        self.l_ratio.pack(fill="x", pady=(8, 0))
        pie = tk.Frame(resumen, bg=c["panel"])
        pie.pack(fill="x", pady=(6, 0))
        self.l_saldo = tk.Label(pie, bg=c["panel"], fg=c["texto"], font=FUENTE_NEG, anchor="w")
        self.l_saldo.pack(side="left")
        self.b_saldo = Boton(pie, "", self.abrir_saldo, c["panel"], c["acento"], c["boton_hover"],
                             fuente=FUENTE_CHICA, padx=6, pady=1)
        self.b_saldo.pack(side="left", padx=(8, 0))

        pestanias = tk.Frame(derecha, bg=c["fondo"])
        pestanias.pack(fill="x", pady=(0, 8))
        self.b_vista = {}
        for clave, texto in (("evolucion", "Evolución"), ("distribucion", "Distribución"),
                             ("balance", "Balance general")):
            boton = Boton(pestanias, texto, lambda k=clave: self._elegir_vista(k), c["boton"], c["texto"],
                          c["boton_hover"], padx=12, pady=4)
            boton.pack(side="left", padx=(0, 6))
            self.b_vista[clave] = boton
        self.opciones_torta = tk.Frame(pestanias, bg=c["fondo"])
        self.b_torta = {}
        self.var_por = tk.StringVar(value=next(t for t, k in AGRUPAR if k == self.torta_por))
        combo = ttk.Combobox(self.opciones_torta, textvariable=self.var_por, values=[t for t, _ in AGRUPAR],
                             state="readonly", width=13, font=FUENTE_CHICA)
        combo.pack(side="right")
        combo.bind("<<ComboboxSelected>>", lambda e: self._elegir_torta(
            "por:" + next(k for t, k in AGRUPAR if t == self.var_por.get())))
        tk.Label(self.opciones_torta, text="Agrupar por", bg=c["fondo"], fg=c["suave"], font=FUENTE_CHICA).pack(
            side="right", padx=(16, 6))
        for clave, texto in (("tipo:ingreso", "Ingresos"), ("tipo:egreso", "Egresos")):
            boton = Boton(self.opciones_torta, texto, lambda k=clave: self._elegir_torta(k), c["boton"], c["texto"],
                          c["boton_hover"], fuente=FUENTE_CHICA, padx=10, pady=4)
            boton.pack(side="right", padx=(6, 0))
            self.b_torta[clave] = boton

        zona_graficos = tk.Frame(derecha, bg=c["fondo"])
        zona_graficos.pack(fill="both", expand=True)
        zona_graficos.grid_rowconfigure(0, weight=1)
        zona_graficos.grid_columnconfigure(0, weight=1)
        self.grafico = Grafico(zona_graficos, c)
        self.grafico.al_elegir = self.elegir_periodo
        self.grafico.grid(row=0, column=0, sticky="nsew")
        self.torta = Torta(zona_graficos, self)
        self.torta.grid(row=0, column=0, sticky="nsew")
        self.vista_balance = VistaBalance(zona_graficos, self)
        self.vista_balance.grid(row=0, column=0, sticky="nsew")

    def _cifra(self, padre, columna, titulo, color):
        c = self.c
        marco = tk.Frame(padre, bg=c["panel"])
        marco.grid(row=0, column=columna, sticky="w")
        padre.grid_columnconfigure(columna, weight=1, uniform="cifra")
        tk.Label(marco, text=titulo, bg=c["panel"], fg=c["suave"], font=FUENTE_CHICA).pack(anchor="w")
        valor = tk.Label(marco, bg=c["panel"], fg=color, font=FUENTE_CIFRA)
        valor.pack(anchor="w")
        return valor

    # ── lista de la izquierda ──
    def _elegir_panel(self, panel):
        c = self.c
        self._guardar_pendientes()
        self.panel = panel
        colores = {"egreso": c["egreso"], "ingreso": c["ingreso"], "deudas": c["acento"]}
        for clave, boton in self.b_panel.items():
            if clave == panel:
                boton.colorear(c["panel"], colores[clave], c["panel"])
            else:
                boton.colorear(c["boton"], c["suave"], c["boton_hover"])
        self.b_mas.config(text={"egreso": "+  Nuevo egreso", "ingreso": "+  Nuevo ingreso",
                                "deudas": "+  Nueva deuda"}[panel])
        if panel == "deudas":
            self.modo_seleccion = False
            self.seleccionados.clear()
        self._mostrar_barras()
        self._mostrar_lista()
        self._resumir_deudas()

    def _entrada_monto(self, padre, var):
        c = self.c
        e = tk.Entry(padre, textvariable=var, width=9, bg=c["entrada"], fg=c["texto"], insertbackground=c["texto"],
                     relief="flat", highlightthickness=1, highlightbackground=c["borde"], highlightcolor=c["acento"],
                     font=FUENTE_CHICA)
        e.pack(side="left", ipady=3)
        var.trace_add("write", lambda *a: self._programar_montos())
        return e

    def _programar_montos(self):
        if self._timer_montos is not None:
            self.after_cancel(self._timer_montos)
        self._timer_montos = self.after(400, self._leer_montos)

    def _leer_montos(self):
        """Lee el rango "Monto entre X y Y" (vacío = sin límite). Un valor inválido se marca en rojo."""
        self._timer_montos = None
        valores = []
        for var, entrada in ((self.var_min, self.e_min), (self.var_max, self.e_max)):
            texto = var.get().strip()
            try:
                valores.append(parse_monto(texto) if texto else None)
                entrada.config(highlightbackground=self.c["borde"])
            except ValueError:
                valores.append(None)
                entrada.config(highlightbackground=self.c["error"])
        self.monto_min, self.monto_max = valores
        if self.monto_min is not None and self.monto_max is not None and self.monto_min > self.monto_max:
            self.monto_min, self.monto_max = self.monto_max, self.monto_min     # "entre 5000 y 1000" = entre 1000 y 5000
        self._mostrar_lista()

    def _elegir_orden(self, orden):
        self.orden = orden
        self.var_orden.set(next(t for t, k in ORDENES if k == orden))
        self._mostrar_lista()

    def _mostrar_barras(self):
        """Arriba de la lista: filtros, barra de selección o resumen de deudas, según corresponda."""
        for zona in (self.zona_filtros, self.zona_orden, self.l_total_lista, self.zona_seleccion, self.zona_deudas):
            zona.pack_forget()
        if self.panel == "deudas":
            self.zona_deudas.pack(fill="x", pady=(0, 10), before=self.lista)
        elif self.modo_seleccion:
            self.zona_seleccion.pack(fill="x", pady=(0, 10), before=self.lista)
            self._contar_seleccion()
        else:
            self.zona_filtros.pack(fill="x", pady=(0, 6), before=self.lista)
            self.zona_orden.pack(fill="x", pady=(0, 4), before=self.lista)
            self.l_total_lista.pack(fill="x", pady=(0, 6), before=self.lista)

    # ── seleccionar y borrar varios ──
    def entrar_seleccion(self):
        self.modo_seleccion = True
        self.seleccionados.clear()
        self._mostrar_barras()
        self._mostrar_lista()

    def salir_seleccion(self):
        self.modo_seleccion = False
        self.seleccionados.clear()
        self._mostrar_barras()
        self._mostrar_lista()

    def marcar(self, id_, si):
        if si:
            self.seleccionados.add(id_)
        else:
            self.seleccionados.discard(id_)
        self._contar_seleccion()

    def _contar_seleccion(self):
        n = len(self.seleccionados)
        self.l_sel.config(text="Tocá los que quieras borrar" if not n else
                          f"{n} seleccionado{'s' if n != 1 else ''}", fg=self.c["texto"])
        self.b_sel_todos.config(text=f"Todos ({len(self.visibles())})")

    def seleccionar_visibles(self):
        """Marca todo lo que muestra la lista con el filtro y la búsqueda actuales (aunque no entre en pantalla)."""
        self.seleccionados |= {m.id for m in self.visibles()}
        self._mostrar_lista()
        self._contar_seleccion()

    def seleccionar_ninguno(self):
        self.seleccionados.clear()
        for t in self.tarjetas:
            if t.var_sel is not None:
                t.var_sel.set(False)
        self._contar_seleccion()

    def borrar_seleccionados(self):
        n = len(self.seleccionados)
        if not n:
            self.l_sel.config(text="No hay nada seleccionado", fg=self.c["aviso"])
            return
        if not messagebox.askyesno("Borrar", f"¿Borrar {n} movimiento{'s' if n != 1 else ''}?\n"
                                             "Vas a poder deshacerlo mientras no cierres la app.", parent=self):
            return
        borrados = [m for m in self.movs if m.id in self.seleccionados]
        self.bd.eliminar_varios([m.id for m in borrados])
        self.movs = [m for m in self.movs if m.id not in self.seleccionados]
        self._deshacer = {"texto": f"Borraste {n} movimiento{'s' if n != 1 else ''}", "movs": borrados}
        self.salir_seleccion()
        self.refrescar()

    def abrir_borrar(self):
        if self._dialogo_borrar is not None:
            self._dialogo_borrar.lift()
            return
        self._guardar_pendientes()
        self._dialogo_borrar = DialogoBorrar(self)

    def resetear(self, que: list[str]):
        """Borra lo elegido en "Borrar datos" y guarda una copia para poder deshacer."""
        copia: dict = {"movs": [], "deudas": []}
        partes = []
        if "movimientos" in que or "periodo" in que:
            if "movimientos" in que:
                borrar = list(self.movs)
                partes.append(f"{len(borrar)} movimiento{'s' if len(borrar) != 1 else ''}")
            else:
                borrar = [m for m in self.movs if ocurre_en(m, self.sel, self.gran)]
                partes.append(f"{len(borrar)} movimiento{'s' if len(borrar) != 1 else ''} de "
                              f"{nombre_periodo(self.sel, self.gran).lower()}")
            ids = {m.id for m in borrar}
            self.bd.eliminar_varios(ids)
            self.movs = [m for m in self.movs if m.id not in ids]
            copia["movs"] = borrar
        if "deudas" in que:
            copia["deudas"] = list(self.deudas)
            self.bd.eliminar_deudas_varias([d.id for d in self.deudas])
            partes.append(f"{len(self.deudas)} deuda{'s' if len(self.deudas) != 1 else ''}")
            self.deudas = []
        if "saldo" in que and (self.ancla or self.saldos_banco):
            copia["ancla"], copia["saldos_banco"] = self.ancla, dict(self.saldos_banco)
            self.saldos_banco = {}
            self.bd.guardar_config("saldos_banco", None)
            self.poner_ancla(None)
            partes.append("tus saldos reales")
        if "aprendido" in que:
            copia["aprendidas"], copia["titular"] = dict(self.aprendidas), self.titular
            self.aprendidas, self.titular = {}, ""
            self.bd.guardar_config("aprendidas", None)
            self.bd.guardar_config("titular", None)
            partes.append("lo aprendido")
        texto = ", ".join(partes[:-1]) + (" y " if len(partes) > 1 else "") + partes[-1] if partes else "nada"
        self._deshacer = {"texto": f"Borraste {texto}", **copia}
        self.modo_seleccion = False
        self.seleccionados.clear()
        self._mostrar_barras()
        self._mostrar_lista()
        self._resumir_deudas()
        self.refrescar()

    def deshacer(self):
        """Vuelve a poner lo último que se borró."""
        d = self._deshacer
        if not d:
            return
        self._deshacer = None
        if d.get("movs"):
            nuevos = [m.copia() for m in d["movs"]]
            for viejo, nuevo in zip(d["movs"], nuevos):
                nuevo.ref = viejo.ref                     # copia() limpia el número de operación; acá se conserva
            self.bd.agregar_varios(nuevos)
            self.movs += nuevos
        for deuda in d.get("deudas", []):
            deuda.id = None
            self.bd.agregar_deuda(deuda)
            self.deudas.append(deuda)
        if d.get("saldos_banco"):
            self.saldos_banco = d["saldos_banco"]
            self.bd.guardar_config("saldos_banco", {k.isoformat(): v for k, v in self.saldos_banco.items()})
        if d.get("ancla"):
            self.poner_ancla(d["ancla"])
        if "aprendidas" in d:
            self.aprendidas = d["aprendidas"]
            self.bd.guardar_config("aprendidas", self.aprendidas)
            if d.get("titular"):
                self.guardar_titular(d["titular"])
        self._mostrar_lista()
        self._resumir_deudas()
        self.refrescar()

    def _elegir_filtro(self, filtro):
        self.filtro = filtro
        self.var_filtro.set(next(t for t, k in FILTROS if k == filtro))
        self._mostrar_lista()

    def _programar_busqueda(self):
        if self._timer_busqueda is not None:
            self.after_cancel(self._timer_busqueda)
        self._timer_busqueda = self.after(300, self._buscar)

    def _buscar(self):
        self._timer_busqueda = None
        self.busqueda = self.var_busqueda.get()
        self.l_buscar.config(text="Buscar" if not self.busqueda else "")
        self._mostrar_lista()

    def visibles(self) -> list[Movimiento]:
        """Los movimientos que muestra la lista ahora, del más nuevo al más viejo."""
        texto = normalizar(self.busqueda.strip())
        res = []
        for m in self.movs:
            if m.tipo != self.panel:
                continue
            if self.filtro == "periodo" and not ocurre_en(m, self.sel, self.gran):
                continue
            if self.filtro == "repiten" and not m.se_repite:
                continue
            if texto and texto not in normalizar(f"{m.nombre} {m.motivo} {m.categoria} {m.medio}"):
                continue
            res.append(m)
        if self.monto_min is not None:
            res = [m for m in res if m.cantidad >= self.monto_min]
        if self.monto_max is not None:
            res = [m for m in res if m.cantidad <= self.monto_max]
        por_fecha = lambda m: (m.inicio, m.hora, m.id or 0)            # noqa: E731
        if self.orden == "monto_desc":
            res.sort(key=lambda m: (m.cantidad, por_fecha(m)), reverse=True)
        elif self.orden == "monto_asc":
            res.sort(key=por_fecha, reverse=True)
            res.sort(key=lambda m: m.cantidad)                        # estable: a igual monto, el más nuevo primero
        elif self.orden == "fecha_asc":
            res.sort(key=por_fecha)
        else:
            res.sort(key=por_fecha, reverse=True)
        return res

    def _mostrar_lista(self):
        c = self.c
        self._guardar_pendientes()
        self.lista.limpiar()
        self.tarjetas, self.tarjetas_deuda = [], []
        if self._deshacer:
            aviso = tk.Label(self.lista.interior, bg=c["fondo"], fg=c["acento"], font=FUENTE_NEG, anchor="w",
                             cursor="hand2", text=f"↩ {self._deshacer['texto']}. Tocá acá para deshacer.",
                             justify="left", wraplength=360)
            aviso.pack(fill="x", pady=(0, 8))
            aviso.bind("<Button-1>", lambda e: self.deshacer())
        if self.panel == "deudas":
            for d in sorted(self.deudas, key=lambda d: (d.saldada, d.tipo, d.primera)):
                t = TarjetaDeuda(self.lista.interior, self, d)
                t.pack(fill="x", pady=(0, 8))
                self.tarjetas_deuda.append(t)
            self.lista.actualizar_vacio("Anotá lo que debés y lo que te deben.\n"
                                        "Tocá «+  Nueva deuda» para agregar la primera.")
            self.lista.al_inicio()
            return

        # aviso: movimientos que se repiten para siempre (la causa típica de proyecciones gigantes)
        sin_fin = [m for m in self.movs if m.tipo == self.panel and m.se_repite and not m.duracion]
        if sin_fin and self.filtro != "repiten":
            total_mes = sum(m.equivalente_mensual() for m in sin_fin)
            aviso = tk.Label(self.lista.interior, bg=c["fondo"], fg=c["aviso"], font=FUENTE_CHICA, anchor="w",
                             justify="left", wraplength=360, cursor="hand2",
                             text=f"↻ {len(sin_fin)} {'se repite' if len(sin_fin) == 1 else 'se repiten'} todos "
                                  f"los meses sin fecha de fin (≈ {dinero(total_mes)} por mes en la proyección). "
                                  "Tocá acá para revisarlos.")
            aviso.pack(fill="x", pady=(0, 8))
            aviso.bind("<Button-1>", lambda e: self._elegir_filtro("repiten"))

        visibles = self.visibles()
        if self.filtro == "periodo":          # lo que se repite cuenta las veces que cae en el período
            suma = sum(m.cantidad * sum(1 for _ in ocurrencias(m, fin_periodo(self.sel, self.gran), self.sel))
                       for m in visibles)
        else:
            suma = sum(m.cantidad for m in visibles)
        filtrado = self.busqueda.strip() or self.monto_min is not None or self.monto_max is not None
        self.l_total_lista.config(
            text=(f"{len(visibles)} movimiento{'s' if len(visibles) != 1 else ''}, suman {dinero(suma)}"
                  + ("  (con filtros)" if filtrado else "")) if visibles else "",
            fg=self.c["acento"] if filtrado else self.c["suave"])
        dia_anterior = None
        for m in visibles[:MAX_TARJETAS]:
            if (self.orden.startswith("fecha") and self.filtro != "repiten" and not m.se_repite
                    and m.inicio != dia_anterior):
                dia_anterior = m.inicio
                tk.Label(self.lista.interior, text=f"{DIAS[m.inicio.weekday()].capitalize()} {m.inicio:%d/%m/%Y}",
                         bg=c["fondo"], fg=c["suave"], font=FUENTE_CHICA, anchor="w").pack(fill="x", pady=(4, 2))
            t = Tarjeta(self.lista.interior, self, m)
            t.pack(fill="x", pady=(0, 6))
            self.tarjetas.append(t)
        if len(visibles) > MAX_TARJETAS:
            tk.Label(self.lista.interior, bg=c["fondo"], fg=c["suave"], font=FUENTE_CHICA, wraplength=360,
                     text=f"Mostrando {MAX_TARJETAS} de {len(visibles)}. Usá «Buscar» o elegí un período más corto.",
                     justify="left", anchor="w").pack(fill="x", pady=(4, 8))
        nombre = "egresos" if self.panel == "egreso" else "ingresos"
        if self.busqueda.strip():
            vacio = f"No hay {nombre} que coincidan con «{self.busqueda.strip()}»."
        elif self.monto_min is not None or self.monto_max is not None:
            vacio = f"No hay {nombre} en ese rango de montos."
        elif self.filtro == "periodo":
            vacio = (f"No hay {nombre} en {nombre_periodo(self.sel, self.gran).lower().replace('año ', 'el año ')}.\n"
                     f"Tocá «+» o importá tus movimientos.")
        elif self.filtro == "repiten":
            vacio = f"No hay {nombre} que se repitan."
        else:
            vacio = f"Todavía no cargaste {nombre}.\nTocá «+» o importá tus movimientos."
        self.lista.actualizar_vacio(vacio)
        self.lista.al_inicio()

    def _poner_arriba(self, widget):
        """Ubica una tarjeta nueva arriba de todo en la lista."""
        hijos = [w for w in self.lista.interior.pack_slaves() if w is not widget and w is not self.lista.vacio]
        if hijos:
            widget.pack(fill="x", pady=(0, 8), before=hijos[0])
        else:
            widget.pack(fill="x", pady=(0, 8))
        self.lista.actualizar_vacio()
        self.lista.al_inicio()

    def _fecha_nueva(self) -> date:
        """Fecha para algo nuevo: hoy, o el primer día del período que estás mirando si es otro."""
        hoy = date.today()
        return hoy if inicio_periodo(hoy, self.gran) == self.sel else self.sel

    def _agregar(self):
        if self.panel == "deudas":
            d = Deuda(tipo="debo", primera=_sumar_meses(date.today(), 1, date.today().day))
            self.bd.agregar_deuda(d)
            self.deudas.append(d)
            t = TarjetaDeuda(self.lista.interior, self, d)
            self.tarjetas_deuda.append(t)
            self._poner_arriba(t)
            t.entrada_persona.focus_set()
            self._resumir_deudas()
            self.refrescar()
            return
        mov = Movimiento(tipo=self.panel, inicio=self._fecha_nueva())
        self.bd.agregar(mov)
        self.movs.append(mov)
        t = Tarjeta(self.lista.interior, self, mov, abierta=True)
        self.tarjetas.append(t)
        self._poner_arriba(t)
        t.entrada_nombre.focus_set()
        self.refrescar()

    def duplicar(self, tarjeta):
        """Crea un movimiento igual, arriba de la lista y abierto para editar."""
        tarjeta.flush()
        mov = tarjeta.mov.copia()
        self.bd.agregar(mov)
        self.movs.append(mov)
        t = Tarjeta(self.lista.interior, self, mov, abierta=True)
        self.tarjetas.append(t)
        self._poner_arriba(t)
        t.entrada_nombre.focus_set()
        self.refrescar()

    def mov_cambiado(self, mov):
        self.bd.actualizar(mov)
        for i, m in enumerate(self.movs):
            if m.id == mov.id:
                self.movs[i] = mov
                break
        self.refrescar()

    def aprender(self, mov, categoria_anterior) -> int:
        """El usuario cambió la categoría de algo: se recuerda para ese nombre y se aplica a los demás
        movimientos con el mismo nombre que tenían la categoría vieja. Devuelve cuántos cambió."""
        clave = f"{mov.tipo}:{normalizar(mov.nombre).strip()}"
        self.aprendidas[clave] = mov.categoria
        self.bd.guardar_config("aprendidas", self.aprendidas)
        cambiados = 0
        for m in self.movs:
            if (m.id != mov.id and m.tipo == mov.tipo and normalizar(m.nombre).strip() == clave.split(":", 1)[1]
                    and m.categoria in (categoria_anterior, "")):
                m.categoria = mov.categoria
                self.bd.actualizar(m)
                cambiados += 1
        if cambiados:
            for t in self.tarjetas:
                if t.mov.id != mov.id and normalizar(t.mov.nombre).strip() == clave.split(":", 1)[1]:
                    t._pintar_cabecera()
                    if t.v is not None:
                        t.v["categoria"].set(t.mov.categoria)
        return cambiados

    def eliminar_tarjeta(self, tarjeta):
        self.bd.eliminar(tarjeta.mov.id)
        self.movs = [m for m in self.movs if m.id != tarjeta.mov.id]
        self.tarjetas.remove(tarjeta)
        tarjeta.destroy()
        self.lista.actualizar_vacio()
        self.refrescar()

    def importar(self, movimientos):
        """Agrega lo importado y muestra el período más reciente que se importó."""
        if not movimientos:
            return
        self.bd.agregar_varios(movimientos)
        self.movs.extend(movimientos)
        tipos = {m.tipo for m in movimientos}
        if self.panel not in tipos:
            self.panel = "egreso" if "egreso" in tipos else "ingreso"
        reciente = max(m.inicio for m in movimientos)
        self.sel = inicio_periodo(reciente, self.gran)
        self._elegir_panel(self.panel)
        self.refrescar()

    # ── deudas ──
    def deuda_cambiada(self, deuda):
        self.bd.actualizar_deuda(deuda)
        for i, d in enumerate(self.deudas):
            if d.id == deuda.id:
                self.deudas[i] = deuda
                break
        self._resumir_deudas()
        self.refrescar()

    def eliminar_deuda(self, tarjeta):
        self.bd.eliminar_deuda(tarjeta.deuda.id)
        self.deudas = [d for d in self.deudas if d.id != tarjeta.deuda.id]
        self.tarjetas_deuda.remove(tarjeta)
        tarjeta.destroy()
        self.lista.actualizar_vacio()
        self._resumir_deudas()
        self.refrescar()

    def _resumir_deudas(self):
        hoy = date.today()
        prox = _sumar_meses(hoy.replace(day=1), 1, 1)
        pagar, n_pagar = cuotas_en_mes(self.deudas, "debo", prox.year, prox.month)
        cobrar, n_cobrar = cuotas_en_mes(self.deudas, "me_deben", prox.year, prox.month)
        self.l_deuda_mes.config(text=f"El mes que viene ({MESES[prox.month - 1]})")
        self.l_deuda_pagar.config(text=f"Pagás {dinero(pagar)}" + (f" en {n_pagar} cuota{'s' if n_pagar != 1 else ''}"
                                                                   if n_pagar else ""))
        self.l_deuda_cobrar.config(text=f"Cobrás {dinero(cobrar)}" + (f" en {n_cobrar} cuota{'s' if n_cobrar != 1 else ''}"
                                                                      if n_cobrar else ""))
        debes = sum(d.restante() for d in self.deudas if d.tipo == "debo")
        te_deben = sum(d.restante() for d in self.deudas if d.tipo == "me_deben")
        vencido = sum(v[2] for d in self.deudas if d.tipo == "debo" for v in d.vencidas(hoy))
        sin_cobrar = sum(v[2] for d in self.deudas if d.tipo == "me_deben" for v in d.vencidas(hoy))
        texto = f"En total debés {dinero(debes)} y te deben {dinero(te_deben)}."
        if vencido:
            texto += f"\n⚠ Tenés {dinero(vencido)} vencido sin pagar."
        if sin_cobrar:
            texto += f"\n⚠ Te deben {dinero(sin_cobrar)} de cuotas ya vencidas."
        self.l_deuda_total.config(text=texto, fg=self.c["error"] if vencido else self.c["suave"])

    def guardar_titular(self, nombre):
        self.titular = nombre
        self.bd.guardar_config("titular", nombre)

    # ── saldo real ──
    def abrir_saldo(self, sugerido=None):
        if self._dialogo_saldo is not None:
            self._dialogo_saldo.cerrar()
        self._dialogo_saldo = DialogoSaldo(self, sugerido)

    def anclas(self) -> list[tuple[date, float]]:
        """Todos los saldos reales conocidos: los del banco (de los resúmenes) y el que cargaste a mano
        (si coinciden en el día, gana el tuyo)."""
        todos = dict(self.saldos_banco)
        if self.ancla:
            todos[self.ancla[0]] = self.ancla[1]
        return sorted(todos.items())

    def guardar_saldos_banco(self, saldos: dict):
        """Guarda el saldo de cierre de cada día que trae un resumen (se suman a los que ya había)."""
        self.saldos_banco.update(saldos)
        self.bd.guardar_config("saldos_banco", {d.isoformat(): v for d, v in self.saldos_banco.items()})
        self.refrescar()

    def poner_ancla(self, ancla):
        self.ancla = ancla
        self.bd.guardar_ancla(ancla)
        self.refrescar()

    def ofrecer_saldo(self, saldo):
        """Después de importar un resumen que trae el saldo de la cuenta, abre "Tu saldo real" con ese
        dato cargado. No se guarda solo: el resumen muestra solo lo disponible en Mercado Pago, y las
        transferencias entre tus cuentas, reservas y dólares no se cuentan como ingreso ni gasto, así que
        el saldo tiene que ser TODA tu plata para que las cuentas cierren."""
        if self.ancla and self.ancla[0] > saldo[0]:
            return
        self.abrir_saldo(sugerido=saldo)

    # ── período elegido ──
    def _elegir_gran(self, g, mantener=False, lista=True):
        c = self.c
        if not mantener or g != self.gran:
            self.sel = inicio_periodo(date.today(), g)
        self.gran = g
        for nombre, boton in self.b_gran.items():
            if nombre == g:
                boton.colorear(c["panel"], c["acento"], c["panel"])
            else:
                boton.colorear(c["boton"], c["texto"], c["boton_hover"])
        self._periodo_cambiado(lista)

    def _periodo_cambiado(self, lista=True):
        if lista and self.panel != "deudas" and self.filtro == "periodo":
            self._mostrar_lista()
        self.refrescar()

    def mover_periodo(self, n):
        self.sel = periodo_siguiente(self.sel, self.gran) if n > 0 else periodo_anterior(self.sel, self.gran)
        self._periodo_cambiado()

    def elegir_periodo(self, inicio):
        self.sel = inicio
        self._periodo_cambiado()

    def ir_a_mes(self, mes: date):
        """Muestra un mes (cambia la vista a «Mes» si hace falta)."""
        if self.gran != "Mes":
            self._elegir_gran("Mes", lista=False)
        self.sel = mes.replace(day=1)
        self._periodo_cambiado()

    def _ir_seleccionado(self):
        mes = self._meses_ir.get(self.var_ir.get())
        self.var_ir.set("Ir a un mes con datos")
        if mes is not None:
            self.ir_a_mes(mes)

    def _actualizar_ir(self):
        """Los meses con movimientos cargados, para saltar directo."""
        self._meses_ir = {f"{nombre_periodo(mes, 'Mes')} ({n} mov.)": mes for mes, n in meses_con_datos(self.movs)}
        self.combo_ir.config(values=list(self._meses_ir))

    def volver_a_hoy(self):
        self.sel = inicio_periodo(date.today(), self.gran)
        self._periodo_cambiado()

    # ── evolución / distribución ──
    def _elegir_vista(self, vista, refrescar=True):
        c = self.c
        self.vista = vista
        # Ojo: Canvas.tkraise() sube dibujos DENTRO del canvas; para subir el widget va Misc.tkraise.
        tk.Misc.tkraise({"evolucion": self.grafico, "distribucion": self.torta,
                         "balance": self.vista_balance}[vista])
        for clave, boton in self.b_vista.items():
            if clave == vista:
                boton.colorear(c["panel"], c["acento"], c["panel"])
            else:
                boton.colorear(c["boton"], c["texto"], c["boton_hover"])
        if vista == "distribucion":
            self.opciones_torta.pack(side="right")
        else:
            self.opciones_torta.pack_forget()
        if refrescar:
            self.refrescar()

    def _elegir_torta(self, clave):
        que, valor = clave.split(":")
        if que == "tipo":
            self.torta_tipo = valor
        else:
            self.torta_por = valor
            self.var_por.set(next(t for t, k in AGRUPAR if k == valor))
        self._marcar_torta()
        self.refrescar()

    def _marcar_torta(self):
        c = self.c
        for clave, boton in self.b_torta.items():
            valor = clave.split(":")[1]
            if valor == self.torta_tipo:
                boton.colorear(c["panel"], c["egreso"] if valor == "egreso" else c["ingreso"], c["panel"])
            else:
                boton.colorear(c["boton"], c["suave"], c["boton_hover"])

    # ── importar / tema ──
    def abrir_importador(self):
        if self._importador is not None:
            self._importador.lift()
            return
        self._importador = Importador(self)

    def alternar_tema(self):
        self._cerrar_ventanas()
        self._guardar_pendientes()
        self.tema = "oscuro" if self.tema == "claro" else "claro"
        self.c = TEMAS[self.tema]
        self.bd.guardar_tema(self.tema)
        self._construir()

    # ── resumen y gráficos ──
    def movimientos_con_proyeccion(self) -> list[Movimiento]:
        """Lo cargado, más las cuotas de deudas que todavía no vencieron, más el gasto variable estimado
        desde el mes que viene (así la proyección no supone que no vas a gastar nada)."""
        hoy = date.today()
        self._estimados = estimado_variable(self.movs, hoy)
        return self.movs + cuotas_futuras(self.deudas, hoy) + self._estimados

    def refrescar(self):
        """Recalcula el resumen y los gráficos con lo que hay cargado."""
        c, hoy = self.c, date.today()
        self._actualizar_ir()
        movs = self.movimientos_con_proyeccion()
        actual = inicio_periodo(hoy, self.gran)
        anclas = self.anclas() or None
        self.grafico.nombre_linea = "Saldo en cuenta" if anclas else "Plata acumulada"
        self.grafico.mostrar(serie(movs, self.gran, hoy, anclas), self.gran, self.sel)
        ingresos, egresos = totales_periodo(movs, self.sel, self.gran)
        balance = round(ingresos - egresos, 2)

        self.l_periodo.config(text="Hoy" if self.gran == "Día" and self.sel == hoy else
                              nombre_periodo(self.sel, self.gran))
        if self.sel == actual:
            self.l_actual.config(text=nombre_periodo(hoy, "Día") if self.gran == "Día" else "período actual")
            self.b_hoy.pack_forget()
        else:
            self.l_actual.config(text="proyección" if self.sel > actual else "")
            self.b_hoy.pack(side="right")
        self.v_ing.config(text=dinero(ingresos))
        self.v_egr.config(text=dinero(egresos))
        self.v_bal.config(text=dinero(balance),
                          fg=c["texto"] if balance == 0 else (c["ingreso"] if balance > 0 else c["egreso"]))

        # con cuánto arrancás el período (lo que te sobró antes) y con cuánto terminás
        arr = arrastre_de(movs, self.gran, self.sel, hoy, anclas)
        anterior = nombre_periodo(periodo_anterior(self.sel, self.gran), self.gran)
        anterior = "ayer" if self.gran == "Día" and self.sel == hoy else anterior[0].lower() + anterior[1:]
        if arr is None:
            self.l_arrastre.config(text="Todavía no hay movimientos reales para saber con cuánto arrancás este período.",
                                   fg=c["suave"])
        else:
            inicial, final = arr
            primero = inicio_datos_reales(movs)
            if anclas:
                texto = f"Arrancás con {dinero(inicial)} (tu plata al cierre de {anterior})."
            elif primero is not None and inicio_periodo(primero, self.gran) == self.sel:
                texto = ("Es el primer período con movimientos cargados, así que la cuenta arranca en $ 0 "
                         "(si tenías plata antes, cargá tu saldo real).")
            elif inicial > 0:
                texto = f"Arrancás con {dinero(inicial)} que te sobraron hasta {anterior}."
            else:
                texto = f"Arrancás en $ 0: no te sobró nada de {anterior}."
            es_primero = not anclas and texto.startswith("Es el primer período")
            if final >= 0:
                texto += f" Con lo que entra y sale, terminás con {dinero(final)}."
                color = c["texto"]
            elif es_primero:
                texto += f" En este período salió {dinero(-final)} más de lo que entró."
                color = c["texto"]
            else:
                texto += f" Te faltan {dinero(-final)} para cubrir lo que sale."
                color = c["egreso"]
            self.l_arrastre.config(text=texto, fg=color)

        # balance general al cierre del período
        self.vista_balance.mostrar(balance_general(movs, self.deudas, self.sel, self.gran, hoy, anclas))

        # gráfico circular del período elegido
        partes = distribucion(movs, self.torta_tipo, self.sel, self.gran, self.torta_por)
        self.torta.mostrar(partes, f"No hay {self.torta_tipo}s en este período.\n"
                                   "Usá las flechas de arriba para ver otro período.")

        # cuánto del ingreso se va en egresos
        if ingresos > 0:
            ratio = egresos / ingresos
            if ratio <= 1:
                texto = f"Los egresos son el {ratio * 100:.0f} % de los ingresos"
            else:
                texto = f"Los egresos superan a los ingresos ({ratio * 100:.0f} %)"
            color = c["ingreso"] if ratio < 0.8 else (c["aviso"] if ratio <= 1 else c["egreso"])
        elif egresos > 0:
            ratio, texto, color = 1.0, "En este período hay egresos y ningún ingreso", c["egreso"]
        else:
            ratio, texto, color = 0.0, "No hay movimientos en este período", c["ingreso"]
        if self._estimados:
            est_ing, est_egr = totales_periodo(self._estimados, self.sel, self.gran)
            if est_ing or est_egr:
                meses = self._estimados[0].motivo.split(" ")[4]
                base = "del último mes con datos" if meses == "1" else f"de los últimos {meses} meses con datos"
                texto += (f"\nProyección: incluye {dinero(est_ing)} de ingresos y {dinero(est_egr)} de gastos "
                          f"estimados (tu promedio {base}).")
        self.progreso.poner(min(ratio, 1.0), color)
        self.l_ratio.config(text=texto)

        # saldo real
        if anclas:
            saldo = saldo_en(movs, hoy, anclas)
            self.l_saldo.config(text=f"Plata hoy: {dinero(saldo)}", fg=c["texto"] if saldo >= 0 else c["egreso"])
            self.b_saldo.config(text="Corregir")
        else:
            self.l_saldo.config(text="Plata hoy: sin cargar", fg=c["suave"])
            self.b_saldo.config(text="Cargar mi saldo real")
