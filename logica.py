"""Lógica del gestor de finanzas, sin interfaz: movimientos, deudas, categorías y series por período."""
from __future__ import annotations

import calendar
import math
import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

FRECUENCIAS = ("Única vez", "Diaria", "Semanal", "Mensual", "Anual")
UNIDADES = {"Única vez": "", "Diaria": "días", "Semanal": "semanas", "Mensual": "meses", "Anual": "años"}
GRANULARIDADES = ("Día", "Semana", "Mes", "Año")
# Períodos que muestra el gráfico: (hacia atrás, hacia adelante) respecto del período actual.
VENTANAS = {"Día": (21, 9), "Semana": (10, 5), "Mes": (8, 4), "Año": (3, 2)}
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")
ANIO_MIN, ANIO_MAX = 1990, 2100
_FACTOR_MENSUAL = {"Diaria": 365.25 / 12, "Semanal": 365.25 / 7 / 12, "Mensual": 1.0, "Anual": 1 / 12}


# ───────────────────────────── categorías ─────────────────────────────

ENTRE_MIS_CUENTAS = "Entre mis cuentas"      # transferencias a/desde otra cuenta tuya
CATEGORIAS_EGRESO = ("Comida y delivery", "Supermercado", "Servicios", "Vivienda", "Transporte", "Educación",
                     "Salud", "Suscripciones", "Ocio y juegos", "Compras", "Deudas y cuotas", "Transferencias",
                     ENTRE_MIS_CUENTAS, "Otros gastos")
CATEGORIAS_INGRESO = ("Sueldo", "Transferencias recibidas", ENTRE_MIS_CUENTAS, "Rendimientos", "Devoluciones",
                      "Cobro de deudas", "Otros ingresos")
SIN_CATEGORIA = "Sin categoría"

# Palabras que se buscan en el nombre y el tipo de operación (sin tildes, en minúscula).
# El orden importa: primero los comercios conocidos, después lo genérico.
_REGLAS_EGRESO = (
    ("Comida y delivery", ("rappi", "pedidosya", "pedidos ya", "mcdonald", "burger king", "mostaza", "starbucks",
                           "havanna", "kfc", "subway", "grido", "freddo", "restaurant", "resto ", "parrilla",
                           "pizzeria", "heladeria", "cafe ", "cafeteria", "panaderia", "rotiseria")),
    ("Supermercado", ("coto", "carrefour", "jumbo", "disco ", "supermercado", "chango mas", "changomas",
                      "la anonima", "walmart", "makro", "diarco", "vital ", "autoservicio")),
    ("Servicios", ("edenor", "edesur", "metrogas", "naturgy", "camuzzi", "aysa", "absa", "personal", "movistar",
                   "claro", "telecentro", "fibertel", "telecom", "flow", "directv", "pago de servicio", "factura",
                   " gas ")),
    ("Vivienda", ("alquiler", "expensa", "cons.de prop", "cons. de prop", "consorcio", "inmobiliaria")),
    ("Transporte", ("uber", "cabify", "didi", "ypf", "shell", "axion", "puma energy", "sube", "telepase", "peaje",
                    "estacionamiento", "trenes argentinos", "subte", "nafta", "viaje", "colectivo")),
    ("Educación", ("utn", "universidad", "facultad", "colegio", "instituto", "udemy", "platzi", "coderhouse",
                   "libreria", "curso")),
    ("Salud", ("farmacia", "farmacity", "osde", "swiss medical", "galeno", "medife", "omint", "hospital",
               "clinica", "sanatorio", "odontolog", "optica")),
    ("Suscripciones", ("netflix", "spotify", "disney", "hbo", "max.com", "youtube", "google", "apple.com",
                       "primevideo", "prime video", "paramount", "crunchyroll", "chatgpt", "openai", "claude",
                       "icloud", "microsoft")),
    ("Ocio y juegos", ("steam", "playstation", "xbox", "nintendo", "epic games", "cine ", "cinema", "hoyts",
                       "cinemark", "showcase", "ticketek", "passline", "boliche", "bar ")),
    ("Deudas y cuotas", ("pago de cuota", "dinero plus", "prestamo", "credito", "cuota ", "resumen de tarjeta",
                         "pago de tarjeta")),
    ("Compras", ("mercado libre", "mercadolibre", "amazon", "shein", "temu", "tienda", "shopping", "compra")),
    ("Transferencias", ("transferencia enviada", "transferencia",)),
)
_REGLAS_INGRESO = (
    ("Sueldo", ("sueldo", "haberes", "salario", "honorarios")),
    ("Devoluciones", ("devolucion", "reintegro", "reembolso", "cashback")),
    ("Rendimientos", ("rendimiento", "interes")),
    ("Transferencias recibidas", ("transferencia recibida", "transferencia")),
)


def normalizar(texto: str) -> str:
    """'Educación  UTN' -> 'educacion  utn' (sin tildes, minúscula)."""
    t = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def categorizar(nombre: str, detalle: str, tipo: str, aprendidas: dict[str, str] | None = None) -> str:
    """Categoría sugerida. Primero lo que el usuario ya corrigió para ese nombre, después palabras clave."""
    if aprendidas:
        propia = aprendidas.get(f"{tipo}:{normalizar(nombre).strip()}")
        if propia:
            return propia
    texto = f" {normalizar(nombre)} {normalizar(detalle)} "
    for categoria, claves in (_REGLAS_INGRESO if tipo == "ingreso" else _REGLAS_EGRESO):
        if any(c in texto for c in claves):
            return categoria
    return "Otros ingresos" if tipo == "ingreso" else "Otros gastos"


# ───────────────────────────── modelo ─────────────────────────────

@dataclass
class Movimiento:
    """Un ingreso o un egreso, puntual o que se repite."""
    tipo: str                        # "ingreso" | "egreso"
    nombre: str = ""
    cantidad: float = 0.0            # monto de cada repetición
    frecuencia: str = "Única vez"    # lo normal en finanzas personales: un gasto pasa una vez
    duracion: int = 0                # cuántas veces se repite (0 = sin fin)
    motivo: str = ""
    inicio: date = field(default_factory=date.today)
    hora: str = ""                   # hora de la operación, "HH:MM" (opcional)
    medio: str = ""                  # medio de pago: "Mastercard prepaga", "Efectivo"... (opcional)
    categoria: str = ""              # "Comida y delivery", "Servicios"... (vacío = sin categoría)
    ref: str = ""                    # número de operación del banco (para no importar dos veces)
    id: int | None = None

    @property
    def se_repite(self) -> bool:
        return self.frecuencia != "Única vez"

    def repeticiones(self) -> int | None:
        """Cuántas veces ocurre; None si no termina nunca."""
        if self.frecuencia == "Única vez":
            return 1
        return self.duracion or None

    def total(self) -> float | None:
        n = self.repeticiones()
        return None if n is None else round(self.cantidad * n, 2)

    def equivalente_mensual(self) -> float:
        return round(self.cantidad * _FACTOR_MENSUAL.get(self.frecuencia, 0.0), 2)

    def ultima_fecha(self) -> date | None:
        n = self.repeticiones()
        return None if n is None else _fecha_k(self, n - 1)

    def a_dict(self) -> dict:
        return {"v": 2, "tipo": self.tipo, "nombre": self.nombre, "cantidad": self.cantidad,
                "frecuencia": self.frecuencia, "duracion": self.duracion, "motivo": self.motivo,
                "inicio": self.inicio.isoformat(), "hora": self.hora, "medio": self.medio,
                "categoria": self.categoria, "ref": self.ref}

    @classmethod
    def desde_dict(cls, d: dict, id: int | None = None) -> Movimiento:
        return cls(tipo=d["tipo"], nombre=d.get("nombre", ""), cantidad=float(d.get("cantidad", 0)),
                   frecuencia=d.get("frecuencia", "Mensual"), duracion=int(d.get("duracion", 0)),
                   motivo=d.get("motivo", ""), inicio=date.fromisoformat(d["inicio"]),
                   hora=d.get("hora", ""), medio=d.get("medio", ""), categoria=d.get("categoria", ""),
                   ref=d.get("ref", ""), id=id)

    def copia(self) -> Movimiento:
        """Un movimiento igual a este pero sin id ni número de operación (para duplicar una sección)."""
        m = Movimiento.desde_dict(self.a_dict())
        m.ref = ""
        return m


@dataclass
class Deuda:
    """Plata que debés (tipo "debo") o que te deben ("me_deben"), en cuotas mensuales."""
    tipo: str = "debo"               # "debo" | "me_deben"
    persona: str = ""                # a quién le debés / quién te debe
    total: float = 0.0               # monto total a pagar (con intereses si los hay)
    cuotas: int = 1
    pagadas: int = 0
    primera: date = field(default_factory=date.today)   # vencimiento de la primera cuota
    motivo: str = ""
    id: int | None = None

    @property
    def valor_cuota(self) -> float:
        return round(self.total / max(1, self.cuotas), 2)

    @property
    def saldada(self) -> bool:
        return self.pagadas >= self.cuotas

    def monto_cuota(self, k: int) -> float:
        """La última cuota absorbe el redondeo, así la suma da exacto el total."""
        if k == self.cuotas - 1:
            return round(self.total - self.valor_cuota * (self.cuotas - 1), 2)
        return self.valor_cuota

    def vencimiento(self, k: int) -> date:
        return _sumar_meses(self.primera, k, self.primera.day)

    def pendientes(self) -> list[tuple[int, date, float]]:
        """(número de cuota, vencimiento, monto) de las cuotas que faltan."""
        return [(k, self.vencimiento(k), self.monto_cuota(k)) for k in range(self.pagadas, self.cuotas)]

    def restante(self) -> float:
        return round(sum(m for _, _, m in self.pendientes()), 2)

    def vencidas(self, hoy: date) -> list[tuple[int, date, float]]:
        return [p for p in self.pendientes() if p[1] < hoy]

    def a_dict(self) -> dict:
        return {"v": 1, "tipo": self.tipo, "persona": self.persona, "total": self.total, "cuotas": self.cuotas,
                "pagadas": self.pagadas, "primera": self.primera.isoformat(), "motivo": self.motivo}

    @classmethod
    def desde_dict(cls, d: dict, id: int | None = None) -> Deuda:
        return cls(tipo=d.get("tipo", "debo"), persona=d.get("persona", ""), total=float(d.get("total", 0)),
                   cuotas=int(d.get("cuotas", 1)), pagadas=int(d.get("pagadas", 0)),
                   primera=date.fromisoformat(d["primera"]), motivo=d.get("motivo", ""), id=id)


def cuotas_en_mes(deudas, tipo: str, anio: int, mes: int) -> tuple[float, int]:
    """(monto, cantidad) de cuotas pendientes de ese tipo que vencen en ese mes."""
    total, n = 0.0, 0
    for d in deudas:
        if d.tipo != tipo:
            continue
        for _, venc, monto in d.pendientes():
            if venc.year == anio and venc.month == mes:
                total += monto
                n += 1
    return round(total, 2), n


def cuotas_futuras(deudas, hoy: date) -> list[Movimiento]:
    """Las cuotas que todavía no vencieron, como movimientos, para sumarlas a la proyección."""
    movs = []
    for d in deudas:
        for k, venc, monto in d.pendientes():
            if venc > hoy and monto > 0:
                movs.append(Movimiento(
                    tipo="egreso" if d.tipo == "debo" else "ingreso", nombre=d.persona or "Sin nombre",
                    cantidad=monto, frecuencia="Única vez", inicio=venc, motivo=f"Cuota {k + 1} de {d.cuotas}",
                    categoria="Deudas y cuotas" if d.tipo == "debo" else "Cobro de deudas"))
    return movs


# ─────────────────────────── repeticiones ───────────────────────────

def _sumar_meses(f: date, n: int, dia: int) -> date:
    """f + n meses, usando `dia` como día del mes (se recorta si el mes es más corto)."""
    m = f.month - 1 + n
    anio, mes = f.year + m // 12, m % 12 + 1
    return date(anio, mes, min(dia, calendar.monthrange(anio, mes)[1]))


def _fecha_k(mov: Movimiento, k: int) -> date:
    i = mov.inicio
    if mov.frecuencia == "Diaria":
        return i + timedelta(days=k)
    if mov.frecuencia == "Semanal":
        return i + timedelta(weeks=k)
    if mov.frecuencia == "Mensual":
        return _sumar_meses(i, k, i.day)
    if mov.frecuencia == "Anual":
        return _sumar_meses(i, 12 * k, i.day)
    return i                         # Única vez


def _primer_k_desde(mov: Movimiento, desde: date) -> int:
    """Índice de la primera repetición que cae en `desde` o después (sin recorrer las anteriores)."""
    if desde <= mov.inicio:
        return 0
    if mov.frecuencia == "Única vez":
        return 1                     # ya pasó: no hay ninguna desde `desde`
    dias = (desde - mov.inicio).days
    if mov.frecuencia == "Diaria":
        k = dias
    elif mov.frecuencia == "Semanal":
        k = dias // 7
    elif mov.frecuencia == "Mensual":
        k = (desde.year - mov.inicio.year) * 12 + desde.month - mov.inicio.month - 1
    else:
        k = desde.year - mov.inicio.year - 1
    k = max(0, k)
    while _fecha_k(mov, k) < desde:
        k += 1
    return k


def ocurrencias(mov: Movimiento, hasta: date, desde: date | None = None):
    """Fechas en que ocurre el movimiento, en orden, entre `desde` y `hasta` (inclusive)."""
    n = mov.repeticiones()
    k = _primer_k_desde(mov, desde) if desde else 0
    while n is None or k < n:
        f = _fecha_k(mov, k)
        if f > hasta:
            return
        yield f
        k += 1


# Un movimiento que se repite es un PLAN (el sueldo de cada mes, el alquiler...). Si en esa fecha ya
# cargaste o importaste el movimiento real, el plan no se cuenta otra vez: si no, el sueldo aparecía
# dos veces (la sección "Sueldo" + la transferencia que llegó). "Parecido" = mismo tipo, monto ±15 % y
# fecha cercana (± estos días según la frecuencia). Lo diario no se compara: es demasiado frecuente.
_TOLERANCIA_DIAS = {"Semanal": 3, "Mensual": 6, "Anual": 10}
TOLERANCIA_MONTO = 0.15


class _Reales:
    """Índice de los movimientos de una sola vez, para saber si un plan ya está cubierto."""

    def __init__(self, movimientos):
        self.por_tipo: dict[str, list[tuple[date, float]]] = {}
        for m in movimientos:
            if not m.se_repite and m.cantidad:
                self.por_tipo.setdefault(m.tipo, []).append((m.inicio, m.cantidad))
        for lista in self.por_tipo.values():
            lista.sort()

    def cubre(self, plan: Movimiento, fecha: date) -> bool:
        dias = _TOLERANCIA_DIAS.get(plan.frecuencia)
        if not dias or not plan.cantidad:
            return False
        lista = self.por_tipo.get(plan.tipo, [])
        i = bisect_right(lista, (fecha - timedelta(days=dias),))
        limite = fecha + timedelta(days=dias)
        while i < len(lista) and lista[i][0] <= limite:
            if abs(lista[i][1] - plan.cantidad) <= TOLERANCIA_MONTO * plan.cantidad:
                return True
            i += 1
        return False


def eventos(movimientos, desde: date, hasta: date, reales: _Reales | None = None):
    """(fecha, movimiento) de todo lo que pasa entre `desde` y `hasta`, sin contar los planes
    que ya tienen su movimiento real."""
    reales = reales or _Reales(movimientos)
    for m in movimientos:
        for f in ocurrencias(m, hasta, desde):
            if m.se_repite and reales.cubre(m, f):
                continue
            yield f, m


def veces_cubierto(plan: Movimiento, movimientos, hasta: date) -> int:
    """Cuántas repeticiones del plan (hasta `hasta`) ya tienen su movimiento real cargado."""
    if not plan.se_repite:
        return 0
    reales = _Reales(movimientos)
    return sum(1 for f in ocurrencias(plan, hasta) if reales.cubre(plan, f))


ESTIMADO = "Gastos variables (estimado)"
ESTIMADO_INGRESOS = "Ingresos variables (estimado)"
_ESTIMADOS = (ESTIMADO, ESTIMADO_INGRESOS)


def gasto_variable_mensual(movimientos, hoy: date, meses: int = 3) -> tuple[float, int]:
    """Promedio por mes de lo que gastaste de verdad en los últimos `meses` meses completos, sin contar
    lo que ya está planificado (un alquiler mensual cargado como plan no se suma dos veces).
    Devuelve (promedio, cuántos meses con datos se usaron)."""
    return variable_mensual(movimientos, hoy, "egreso", meses)


def variable_mensual(movimientos, hoy: date, tipo: str, meses: int = 3) -> tuple[float, int]:
    """Promedio por mes de los ingresos o egresos reales (según `tipo`) de los últimos `meses` meses
    completos, sin contar lo que corresponde a un plan (sueldo, alquiler...). Los meses sin ningún
    movimiento cargado no cuentan (no se sabe qué pasó); los que tienen datos pero nada de ese tipo,
    cuentan como 0. Devuelve (promedio, cuántos meses con datos se usaron)."""
    mes_actual = hoy.replace(day=1)
    desde, hasta = _sumar_meses(mes_actual, -meses, 1), mes_actual - timedelta(days=1)
    planes = []
    for p in movimientos:
        dias = _TOLERANCIA_DIAS.get(p.frecuencia)
        if p.tipo == tipo and p.se_repite and dias and p.cantidad:
            planes += [(f, p.cantidad, dias) for f in ocurrencias(p, hasta + timedelta(days=dias),
                                                                     desde - timedelta(days=dias))]
    reales = [m for m in movimientos if not m.se_repite and desde <= m.inicio <= hasta and m.cantidad]
    # Cada vencimiento planificado se lleva UN movimiento real: el de monto más parecido (así una compra
    # grande cerca del alquiler no se confunde con el alquiler si el pago real también está).
    pagos_de_planes: set[int] = set()
    for f, monto, dias in planes:
        candidatos = [(abs(m.cantidad - monto), i) for i, m in enumerate(reales)
                      if i not in pagos_de_planes and m.tipo == tipo and abs((f - m.inicio).days) <= dias
                      and abs(m.cantidad - monto) <= TOLERANCIA_MONTO * monto]
        if candidatos:
            pagos_de_planes.add(min(candidatos)[1])
    gastado: dict[tuple[int, int], float] = {}
    con_datos: set[tuple[int, int]] = set()
    for i, m in enumerate(reales):
        mes = (m.inicio.year, m.inicio.month)
        con_datos.add(mes)
        if m.tipo != tipo or m.nombre in _ESTIMADOS or i in pagos_de_planes:
            continue
        gastado[mes] = gastado.get(mes, 0.0) + m.cantidad
    if not con_datos:
        return 0.0, 0
    return round(sum(gastado.values()) / len(con_datos), 2), len(con_datos)


def estimado_variable(movimientos, hoy: date) -> list[Movimiento]:
    """Planes diarios con tus ingresos y gastos variables promedio, desde el mes que viene, para que la
    proyección siga la tendencia real: ni supone que no vas a gastar nada, ni que no te va a entrar nada.
    Lista vacía si no hay datos para estimarlo."""
    res = []
    for tipo, nombre in (("egreso", ESTIMADO), ("ingreso", ESTIMADO_INGRESOS)):
        promedio, meses = variable_mensual(movimientos, hoy, tipo)
        if promedio <= 0:
            continue
        res.append(Movimiento(tipo=tipo, nombre=nombre, cantidad=round(promedio / 30.4375, 2), frecuencia="Diaria",
                              duracion=366 * 3, inicio=_sumar_meses(hoy.replace(day=1), 1, 1), categoria=nombre,
                              motivo=f"Promedio de tus últimos {meses} {'mes' if meses == 1 else 'meses'}: "
                                     f"{dinero(promedio)} por mes"))
    return res


def meses_con_datos(movimientos) -> list[tuple[date, int]]:
    """(primer día del mes, cuántos movimientos reales) de cada mes que tiene datos, del más nuevo al más viejo."""
    cuenta: dict[date, int] = {}
    for m in movimientos:
        if not m.se_repite:
            mes = m.inicio.replace(day=1)
            cuenta[mes] = cuenta.get(mes, 0) + 1
    return sorted(cuenta.items(), reverse=True)

def neto_entre(movimientos, desde: date, hasta: date) -> float:
    """Ingresos menos egresos con fecha entre `desde` y `hasta` (inclusive)."""
    if hasta < desde:
        return 0.0
    total = 0.0
    for _, m in eventos(movimientos, desde, hasta):
        total += m.cantidad if m.tipo == "ingreso" else -m.cantidad
    return round(total, 2)


def lista_anclas(ancla) -> list[tuple[date, float]]:
    """Los saldos reales conocidos, ordenados por día. Acepta uno solo (día, plata), una lista o None.
    Pueden ser el que cargaste a mano y los saldos diarios que traen los resúmenes del banco."""
    if not ancla:
        return []
    if isinstance(ancla, tuple) and len(ancla) == 2 and isinstance(ancla[0], date):
        return [ancla]
    return sorted(ancla)


def inicio_de_datos(movimientos, ancla) -> date:
    """Desde qué día se puede saber tu saldo: el día anterior a tu primer movimiento real (de una sola
    vez) o el del primer saldo real conocido, lo que sea antes. Para atrás, solo habría planes."""
    primer_ancla = lista_anclas(ancla)[0][0]
    reales = [m.inicio for m in movimientos if not m.se_repite]
    primero = min(reales) - timedelta(days=1) if reales else primer_ancla
    return min(primero, primer_ancla)


def saldo_en(movimientos, fecha: date, ancla) -> float | None:
    """Plata que tenías (o vas a tener) al final de `fecha`, partiendo de un saldo real conocido.

    `ancla` = un saldo real (día, plata) o una lista de ellos (por ejemplo, el saldo del banco al
    cierre de cada día que trajo un resumen). Se parte del saldo conocido más cercano ANTES de esa
    fecha (o del primero, si la fecha es anterior a todos) y se suma o resta solo lo que pasó en el
    medio. Así un error o un movimiento que no se cuenta (reservas, dólares) no se arrastra: se
    corrige en cada saldo conocido. Sin saldos reales no se puede saber: None.
    """
    anclas = lista_anclas(ancla)
    if not anclas:
        return None
    previas = [a for a in anclas if a[0] <= fecha]
    dia, monto = previas[-1] if previas else anclas[0]
    if fecha >= dia:
        return round(monto + neto_entre(movimientos, dia + timedelta(days=1), fecha), 2)
    return round(monto - neto_entre(movimientos, fecha + timedelta(days=1), dia), 2)


# ─────────────────────── períodos y series ───────────────────────

def inicio_periodo(f: date, g: str) -> date:
    if g == "Día":
        return f
    if g == "Semana":
        return f - timedelta(days=f.weekday())        # lunes
    if g == "Mes":
        return f.replace(day=1)
    return f.replace(month=1, day=1)


def periodo_siguiente(f: date, g: str) -> date:
    if g == "Día":
        return f + timedelta(days=1)
    if g == "Semana":
        return f + timedelta(days=7)
    if g == "Mes":
        return _sumar_meses(f, 1, 1)
    return f.replace(year=f.year + 1)


def periodo_anterior(f: date, g: str) -> date:
    if g == "Día":
        return f - timedelta(days=1)
    if g == "Semana":
        return f - timedelta(days=7)
    if g == "Mes":
        return _sumar_meses(f, -1, 1)
    return f.replace(year=f.year - 1)


def fin_periodo(f: date, g: str) -> date:
    return periodo_siguiente(f, g) - timedelta(days=1)


@dataclass(frozen=True)
class Punto:
    inicio: date          # primer día del período
    ingresos: float
    egresos: float
    acumulado: float | None   # la línea del gráfico (ver `serie`); None = sin datos para saberlo
    futuro: bool          # True si el período empieza después de hoy (proyección)

    @property
    def balance(self) -> float:
        return round(self.ingresos - self.egresos, 2)


def serie(movimientos, g: str, hoy: date | None = None, ancla: tuple[date, float] | None = None) -> list[Punto]:
    """Ingresos, egresos y la línea del gráfico por período, alrededor de hoy.

    - Con `ancla` (tu saldo real de un día), `acumulado` es la plata que tenías/vas a tener al final
      de cada período: saldo real + lo que entró − lo que salió desde ese día.
      Antes de tus datos reales (el día anterior a tu primer movimiento de una sola vez, o el día del
      ancla si es anterior) no se sabe cuánta plata tenías: ahí `acumulado` es None y no se dibuja.
    - Sin ancla, `acumulado` es la plata acumulada con ARRASTRE: lo que te sobra en un período es con
      lo que arrancás el siguiente (ver `arrastres`). Arranca en tu primer movimiento real.
    Nunca se arrastra todo el historial viejo: eso daba saldos imposibles.
    """
    hoy = hoy or date.today()
    atras, adelante = VENTANAS[g]
    actual = inicio_periodo(hoy, g)
    inicios = [actual]
    f = actual
    for _ in range(atras):
        f = periodo_anterior(f, g)
        inicios.insert(0, f)
    f = actual
    for _ in range(adelante):
        f = periodo_siguiente(f, g)
        inicios.append(f)
    ultimo_dia = fin_periodo(inicios[-1], g)

    ing, egr = [0.0] * len(inicios), [0.0] * len(inicios)
    for f, m in eventos(movimientos, inicios[0], ultimo_dia):
        i = bisect_right(inicios, f) - 1
        if m.tipo == "ingreso":
            ing[i] += m.cantidad
        else:
            egr[i] += m.cantidad

    puntos = []
    if ancla:
        desde_cuando = inicio_de_datos(movimientos, ancla)
        for i, ini in enumerate(inicios):
            fin = fin_periodo(ini, g)
            valor = saldo_en(movimientos, fin, ancla) if fin >= desde_cuando else None
            puntos.append(Punto(ini, round(ing[i], 2), round(egr[i], 2), valor, ini > hoy))
    else:
        finales = {ini: fin for ini, _, fin in arrastres(movimientos, g, inicios[-1], hoy)}
        for i, ini in enumerate(inicios):
            puntos.append(Punto(ini, round(ing[i], 2), round(egr[i], 2), finales.get(ini), ini > hoy))
    return puntos


def inicio_datos_reales(movimientos) -> date | None:
    """Fecha de tu primer movimiento real (de una sola vez). Los planes no cuentan."""
    reales = [m.inicio for m in movimientos if not m.se_repite]
    return min(reales) if reales else None


def arrastres(movimientos, g: str, hasta: date, hoy: date | None = None) -> list[tuple[date, float, float]]:
    """(inicio del período, con cuánto arrancás, con cuánto terminás) para cada período, desde el de tu
    primer movimiento real hasta `hasta` (inclusive). Sin movimientos reales, arranca en el período de hoy.

    Lo que te sobra en un período pasa al siguiente. Si un período gastás más de lo que entra, usás lo
    que venías arrastrando; si no alcanza, el período termina en negativo (te faltó plata) pero el
    siguiente arranca en 0: no se arrastra plata que no existe."""
    hoy = hoy or date.today()
    primero = inicio_datos_reales(movimientos) or hoy
    inicios = [inicio_periodo(primero, g)]
    hasta = inicio_periodo(hasta, g)
    while inicios[-1] < hasta:
        inicios.append(periodo_siguiente(inicios[-1], g))
    if inicios[0] > hasta:
        return []
    neto = [0.0] * len(inicios)
    for f, m in eventos(movimientos, inicios[0], fin_periodo(inicios[-1], g)):
        neto[bisect_right(inicios, f) - 1] += m.cantidad if m.tipo == "ingreso" else -m.cantidad
    res, arranque = [], 0.0
    for ini, n in zip(inicios, neto):
        final = round(arranque + n, 2)
        res.append((ini, round(arranque, 2), final))
        arranque = max(0.0, final)
    return res


def arrastre_de(movimientos, g: str, inicio: date, hoy: date | None = None,
                ancla: tuple[date, float] | None = None) -> tuple[float, float] | None:
    """(con cuánto arrancás, con cuánto terminás) el período que empieza en `inicio`.
    Con saldo real: tu saldo al cierre del período anterior y al cierre de este. None si no hay datos."""
    hoy = hoy or date.today()
    if ancla:
        if fin_periodo(inicio, g) < inicio_de_datos(movimientos, ancla):
            return None
        return (saldo_en(movimientos, inicio - timedelta(days=1), ancla),
                saldo_en(movimientos, fin_periodo(inicio, g), ancla))
    lista = arrastres(movimientos, g, inicio, hoy)
    if not lista or lista[-1][0] != inicio_periodo(inicio, g):
        return None
    return lista[-1][1], lista[-1][2]


# ─────────────────────────── balance general ───────────────────────────

def deuda_pendiente_al(d: Deuda, dia: date, hoy: date) -> float:
    """Cuánto queda de la deuda al final de `dia`.
    - Fecha pasada: lo que vencía después de ese día (según el plan de cuotas).
    - Hoy o futuro: las cuotas sin pagar que vencen después de ese día, más las que ya vencieron y
      siguen sin pagar (las que vencen entre hoy y ese día ya se restan en la proyección de la plata)."""
    if dia < hoy:
        return round(sum(d.monto_cuota(k) for k in range(d.cuotas) if d.vencimiento(k) > dia), 2)
    return round(sum(m for _, v, m in d.pendientes() if v > dia or v <= hoy), 2)


@dataclass
class BalanceGeneral:
    dia: date
    caja: float | None                     # plata en tus cuentas (None si no se puede saber)
    nombre_caja: str                       # "Caja y bancos" o "Plata acumulada"
    creditos: list[tuple[str, float]]      # quién te debe y cuánto
    deudas: list[tuple[str, float]]        # a quién le debés y cuánto
    resultado: float                       # ingresos − egresos del período

    @property
    def total_creditos(self) -> float:
        return round(sum(v for _, v in self.creditos), 2)

    @property
    def activo(self) -> float:
        return round((self.caja or 0) + self.total_creditos, 2)

    @property
    def pasivo(self) -> float:
        return round(sum(v for _, v in self.deudas), 2)

    @property
    def patrimonio(self) -> float:
        return round(self.activo - self.pasivo, 2)

    @property
    def patrimonio_anterior(self) -> float:
        """Lo que ya tenías antes del período: patrimonio neto menos el resultado del período."""
        return round(self.patrimonio - self.resultado, 2)


def balance_general(movimientos, deudas, inicio: date, g: str, hoy: date | None = None,
                    ancla: tuple[date, float] | None = None) -> BalanceGeneral:
    """Estado de tu patrimonio al cierre del período que empieza en `inicio`:
    activo (plata + lo que te deben) − pasivo (lo que debés) = patrimonio neto."""
    hoy = hoy or date.today()
    dia = fin_periodo(inicio, g)
    arr = arrastre_de(movimientos, g, inicio, hoy, ancla)
    caja = arr[1] if arr else None
    ing, egr = totales_periodo(movimientos, inicio, g)

    def agrupar(tipo):
        sumas: dict[str, float] = {}
        for d in deudas:
            if d.tipo == tipo:
                v = deuda_pendiente_al(d, dia, hoy)
                if v > 0:
                    nombre = d.persona.strip() or "Sin nombre"
                    sumas[nombre] = sumas.get(nombre, 0.0) + v
        return sorted(((k, round(v, 2)) for k, v in sumas.items()), key=lambda kv: -kv[1])

    return BalanceGeneral(dia=dia, caja=caja, nombre_caja="Caja y bancos" if ancla else "Plata acumulada",
                          creditos=agrupar("me_deben"), deudas=agrupar("debo"), resultado=round(ing - egr, 2))


def totales_periodo(movimientos, inicio: date, g: str) -> tuple[float, float]:
    """(ingresos, egresos) de un período cualquiera."""
    ing = egr = 0.0
    for _, m in eventos(movimientos, inicio, fin_periodo(inicio, g)):
        if m.tipo == "ingreso":
            ing += m.cantidad
        else:
            egr += m.cantidad
    return round(ing, 2), round(egr, 2)


def clave_grupo(m: Movimiento, por: str) -> str:
    if por == "hora":
        return franja_horaria(m.hora)
    if por == "medio":
        return m.medio.strip() or "Sin medio de pago"
    if por == "categoria":
        return m.categoria.strip() or SIN_CATEGORIA
    texto = (m.motivo if por == "motivo" else m.nombre).strip()
    return texto or ("Sin motivo" if por == "motivo" else "Sin nombre")


def distribucion(movimientos, tipo: str, inicio: date, g: str, por: str = "categoria",
                 maximo: int = 7) -> list[tuple[str, float]]:
    """Cuánto suma cada categoría (o nombre, motivo, hora, medio) en el período, de mayor a menor.

    Si hay más de `maximo` partes, las más chicas se juntan en "Otros (n)".
    """
    sumas: dict[str, float] = {}
    for _, m in eventos(movimientos, inicio, fin_periodo(inicio, g)):
        if m.tipo != tipo or not m.cantidad:
            continue
        clave = clave_grupo(m, por)
        sumas[clave] = sumas.get(clave, 0.0) + m.cantidad
    partes = sorted(((k, round(v, 2)) for k, v in sumas.items()), key=lambda kv: (-kv[1], kv[0].lower()))
    if len(partes) > maximo:
        resto = partes[maximo - 1:]
        partes = partes[:maximo - 1] + [(f"Otros ({len(resto)})", round(sum(v for _, v in resto), 2))]
    return partes


def ocurre_en(m: Movimiento, inicio: date, g: str) -> bool:
    return next(iter(ocurrencias(m, fin_periodo(inicio, g), inicio)), None) is not None


# ──────────────────── texto, montos y fechas ────────────────────

def etiqueta_eje(f: date, g: str) -> str:
    if g in ("Día", "Semana"):
        return f"{f:%d/%m}"
    if g == "Mes":
        return f"{MESES[f.month - 1][:3]} {f:%y}"
    return str(f.year)


def nombre_periodo(f: date, g: str) -> str:
    if g == "Día":
        return f"{f:%d/%m/%Y}"
    if g == "Semana":
        return f"Semana del {f:%d/%m} al {f + timedelta(days=6):%d/%m/%Y}"
    if g == "Mes":
        return f"{MESES[f.month - 1].capitalize()} {f.year}"
    return f"Año {f.year}"


def dinero(x: float) -> str:
    """1234.5 -> '$ 1.234,50' (formato argentino; sin decimales si es entero)."""
    x = round(x, 2)
    txt = f"{abs(x):,.0f}" if x == int(x) else f"{abs(x):,.2f}"
    txt = txt.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{'-' if x < 0 else ''}$ {txt}"


def dinero_corto(x: float) -> str:
    """Para los ejes del gráfico: 1500 -> '1,5k', 2000000 -> '2M'."""
    for limite, sufijo in ((1e6, "M"), (1e3, "k")):
        if abs(x) >= limite:
            return f"{x / limite:.1f}".rstrip("0").rstrip(".").replace(".", ",") + sufijo
    return f"{x:.0f}"


def numero(x: float) -> str:
    """Número para mostrar en un campo de texto: 1500.5 -> '1500,5'."""
    return f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def parse_monto(texto: str, negativo: bool = False) -> float:
    """Acepta 1500, 1500,50, 1.500,50 y 1500.50. Vacío = 0. Con negativo=True acepta '-1500'."""
    t = texto.strip().replace("$", "").replace(" ", "")
    signo = 1
    if negativo and t[:1] in "-−–":
        signo, t = -1, t[1:]
    if not t:
        return 0.0
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        valor = float(t)
    except ValueError:
        raise ValueError("Cantidad inválida. Escribila así: 1500 o 1500,50") from None
    if not math.isfinite(valor) or valor < 0:
        raise ValueError("Cantidad inválida. Escribila así: 1500 o 1500,50")
    if valor > 1e12:
        raise ValueError("La cantidad es demasiado grande")
    return round(signo * valor, 2)


def parse_fecha(texto: str) -> date:
    t = texto.strip().replace("-", "/").replace(".", "/")
    try:
        f = datetime.strptime(t, "%d/%m/%Y").date()
    except ValueError:
        raise ValueError("Fecha inválida. Usá día/mes/año, por ejemplo 15/03/2026") from None
    if not ANIO_MIN <= f.year <= ANIO_MAX:
        raise ValueError(f"Usá un año entre {ANIO_MIN} y {ANIO_MAX}")
    return f


def parse_entero(texto: str, nombre: str, minimo: int = 0, maximo: int = 10000) -> int:
    t = texto.strip()
    if not (t.isascii() and t.isdigit()) or not minimo <= int(t) <= maximo:
        raise ValueError(f"{nombre} tiene que ser un número entero entre {minimo} y {maximo}")
    return int(t)


FRANJAS = ((6, "Madrugada (0 a 6 h)"), (12, "Mañana (6 a 12 h)"), (19, "Tarde (12 a 19 h)"),
           (24, "Noche (19 a 24 h)"))


def franja_horaria(hora: str) -> str:
    """'00:39' -> 'Madrugada (0 a 6 h)'. Sin hora -> 'Sin hora'."""
    if not hora:
        return "Sin hora"
    h = int(hora.split(":")[0])
    return next(nombre for limite, nombre in FRANJAS if h < limite)


def parse_hora(texto: str) -> str:
    """Acepta '0:39', '00:39', '13.05' o vacío. Devuelve 'HH:MM' o ''."""
    t = texto.strip().replace(".", ":").lower().removesuffix("hs").removesuffix("h").strip()
    if not t:
        return ""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError("Hora inválida. Usá horas:minutos, por ejemplo 00:39 o 18:05")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def ticks_agradables(vmin: float, vmax: float, n: int = 5) -> list[float]:
    """Valores redondos (1, 2, 2.5, 5 x 10^k) que cubren el rango [vmin, vmax]."""
    if vmax <= vmin:
        vmax = vmin + 1
    bruto = (vmax - vmin) / max(1, n)
    magnitud = 10 ** math.floor(math.log10(bruto))
    paso = 10 * magnitud
    for m in (1, 2, 2.5, 5, 10):
        if bruto <= m * magnitud:
            paso = m * magnitud
            break
    v, fin, ticks = math.floor(vmin / paso) * paso, math.ceil(vmax / paso) * paso, []
    while v <= fin + paso * 0.001:
        ticks.append(round(v, 10))
        v += paso
    return ticks
