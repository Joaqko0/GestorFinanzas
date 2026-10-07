"""Lee el texto que se copia de la actividad de Mercado Pago y lo convierte en movimientos.

Formato que entiende (cada operación), tal como sale al copiar y pegar:
    15:59                        <- hora (opcional)
    Claude Ai                    <- con quién
    Claude Ai                    <- el nombre repetido (a veces viene pegado al tipo: "Claude AiPago online")
    Pago online                  <- tipo de operación
    Mastercard prepaga           <- medio de pago (opcional)
    Aprobado                     <- estado (opcional)
    -                            <- monto: "-" es egreso, "+" es ingreso. Puede venir en una
    $                               sola línea (-$12.345,67) o partido en varias, como acá
    12.345
    ,
    67
Y entre operaciones, encabezados de fecha: "30 de septiembre", "15 de diciembre de 2025", "Hoy", "Ayer".

También lee archivos descargados (ver `leer_archivo`): el "Resumen de cuenta" de Mercado Pago en .csv
o .xlsx, y en general cualquier CSV/Excel de banco con columnas de fecha, descripción y monto.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from logica import Movimiento, categorizar, dinero, normalizar, parse_monto

_MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
          "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
_RE_FECHA = re.compile(r"^(?:[a-záéíóú]+,?\s+)?(\d{1,2})\s+de\s+([a-z]+)(?:\s+(?:de\s+)?(\d{4}))?$")
_RE_HORA = re.compile(r"^(\d{1,2}):(\d{2})(?:\s*(?:hs?\.?|am|pm))?$")
_RE_MONTO = re.compile(r"^([+\-−–])?\s*\$\s*([\d.,]+)$")
_ESTADOS = {"aprobado", "aprobada", "rechazado", "rechazada", "cancelado", "cancelada", "pendiente",
            "en proceso", "devuelto", "devuelta", "acreditado", "acreditada", "en revision", "en revisión"}
_OK = {"aprobado", "aprobada", "acreditado", "acreditada"}
# Mover plata entre tu cuenta y una reserva tuya no es ganar ni gastar.
_INTERNOS = ("dinero retirado", "dinero reservado", "reserva", "transferencia entre tus cuentas",
             "inversion", "rescate", "venta de dolar", "compra de dolar")


@dataclass
class Operacion:
    fecha: date
    hora: str = ""
    nombre: str = ""
    detalle: str = ""                 # tipo de operación: "Compra", "Transferencia enviada", ...
    estado: str = ""
    monto: float | None = None        # con signo: negativo = egreso
    extras: list[str] = field(default_factory=list)
    tachado: bool = False             # el monto venía tachado (pago que no se cobró)
    ref: str = ""                     # número de operación (solo en archivos)
    saldo: float | None = None        # saldo de la cuenta después de esta operación (solo en archivos)
    # devolución que cancela esta operación, o al revés (fuera de repr/== para no entrar en bucle)
    anulada_por: Operacion | None = field(default=None, repr=False, compare=False)

    @property
    def medio(self) -> str:
        """Medio de pago: "Mastercard prepaga", "Dinero disponible", ..."""
        return self.extras[0] if self.extras else ""

    @property
    def es_devolucion(self) -> bool:
        return "devoluci" in self.detalle.lower() or "reintegro" in self.detalle.lower()

    @property
    def tipo(self) -> str:
        return "egreso" if (self.monto or 0) < 0 else "ingreso"

    @property
    def aprobada(self) -> bool:
        if self.tachado:
            return False
        return not self.estado or self.estado.lower() in _OK

    @property
    def cuenta(self) -> bool:
        """Si corresponde importarla de entrada (el usuario igual puede cambiarlo)."""
        return self.aprobada and not self.interna and self.anulada_por is None

    @property
    def interna(self) -> bool:
        d = normalizar(self.detalle)
        return any(x in d for x in _INTERNOS)

    def a_movimiento(self, aprendidas: dict[str, str] | None = None) -> Movimiento:
        return Movimiento(tipo=self.tipo, nombre=self.nombre, cantidad=abs(self.monto or 0),
                          frecuencia="Única vez", motivo=self.detalle, inicio=self.fecha, hora=self.hora,
                          medio=self.medio, ref=self.ref,
                          categoria=categorizar(self.nombre, self.detalle, self.tipo, aprendidas))


def _huella(tipo: str, fecha: date, monto: float) -> tuple:
    return (tipo, fecha, round(abs(monto), 2))


def marcar_repetidas(ops: list[Operacion], existentes: list[Movimiento]) -> list[bool]:
    """Qué operaciones ya están cargadas.

    Primero por número de operación. Si no hay, por (tipo, día, monto), contando cuántas hay de cada
    una: si ya cargaste dos transferencias de $4.000 el mismo día y pegás tres, la tercera es nueva.
    Así no importa si antes lo pegaste a mano (con hora) y ahora lo traés del archivo (sin hora).
    """
    # Mercado Pago usa el mismo número para un pago y su devolución: el número se compara junto con el tipo.
    refs = {(m.tipo, m.ref) for m in existentes if m.ref}
    disponibles = Counter(_huella(m.tipo, m.inicio, m.cantidad) for m in existentes if not m.se_repite)
    vistas_ref = set()
    resultado = []
    for op in ops:
        clave_ref = (op.tipo, op.ref)
        if op.ref and (clave_ref in refs or clave_ref in vistas_ref):
            resultado.append(True)
            h = _huella(op.tipo, op.fecha, op.monto or 0)
            if disponibles[h] > 0:
                disponibles[h] -= 1
            continue
        if op.ref:
            vistas_ref.add(clave_ref)
        h = _huella(op.tipo, op.fecha, op.monto or 0)
        if disponibles[h] > 0:
            disponibles[h] -= 1
            resultado.append(True)
        else:
            resultado.append(False)
    return resultado


def _sin_tachado(linea: str) -> tuple[str, bool]:
    """Saca las marcas de tachado (~~texto~~ o caracteres con raya) y dice si había."""
    tachado = "~~" in linea or "̶" in linea or "̵" in linea
    return linea.replace("~~", "").replace("̶", "").replace("̵", ""), tachado


def _limpiar(linea: str) -> str:
    linea = unicodedata.normalize("NFC", linea).replace(" ", " ").replace("​", "").strip()
    linea = re.sub(r"^[*•·\-–]\s+", "", linea) if not _RE_MONTO.match(linea) else linea
    return "" if linea in ("*", "•", "·") else linea.strip()


def _fecha(texto: str, hoy: date) -> date | None:
    t = texto.lower().rstrip(".")
    if t == "hoy":
        return hoy
    if t == "ayer":
        return hoy - timedelta(days=1)
    m = _RE_FECHA.match(t)
    if not m or m.group(2) not in _MESES:
        return None
    dia, mes = int(m.group(1)), _MESES[m.group(2)]
    anio = int(m.group(3)) if m.group(3) else hoy.year
    try:
        f = date(anio, mes, dia)
    except ValueError:
        return None
    if not m.group(3) and f > hoy:           # "28 de diciembre" leído en enero: es del año pasado
        f = f.replace(year=anio - 1)
    return f


_RE_PEDAZO_MONTO = re.compile(r"^[+\-−–$\d.,\s]+$")


def _lineas(texto: str):
    """Líneas limpias como (texto, tachado).

    Al copiar desde la web, Mercado Pago parte el monto en varias líneas:
        -  /  $  /  12.345  /  ,  /  67
    Acá se vuelven a juntar en "-$12.345,67".
    """
    limpias = []
    for cruda in texto.splitlines():
        sin_raya, tachado = _sin_tachado(cruda)
        linea = _limpiar(sin_raya)
        if linea:
            limpias.append((linea, tachado))

    i = 0
    while i < len(limpias):
        j = i
        while j < len(limpias) and _RE_PEDAZO_MONTO.match(limpias[j][0]):
            j += 1
        if j - i >= 2:
            pedazos = limpias[i:j]
            junto = "".join(p.replace(" ", "") for p, _ in pedazos)
            if "$" in junto and _RE_MONTO.match(junto):
                yield junto, any(t for _, t in pedazos)
                i = j
                continue
        yield limpias[i]
        i += 1


def leer_mercadopago(texto: str, hoy: date | None = None) -> list[Operacion]:
    """Devuelve las operaciones encontradas, en el orden del texto. Ignora lo que no entiende."""
    hoy = hoy or date.today()
    fecha, actual, ops = hoy, None, []      # lo que aparece antes del primer encabezado es de hoy

    def cerrar():
        nonlocal actual
        if actual is not None and actual.monto is not None and actual.monto != 0:
            ops.append(actual)
        actual = None

    for linea, tachado in _lineas(texto):
        f = _fecha(linea, hoy)
        if f is not None:
            cerrar()
            fecha = f
            continue
        h = _RE_HORA.match(linea)
        if h:
            cerrar()
            actual = Operacion(fecha=fecha, hora=f"{int(h.group(1)):02d}:{h.group(2)}")
            continue
        mm = _RE_MONTO.match(linea)
        if mm:
            if actual is None:
                continue
            try:
                valor = parse_monto(mm.group(2))
            except ValueError:
                actual = None
                continue
            actual.monto = valor if mm.group(1) == "+" else -valor
            if mm.group(1) is None:          # sin signo: decidir por el tipo de operación
                d = actual.detalle.lower()
                entra = any(x in d for x in ("recibid", "retirado", "ingreso", "devoluci", "reintegro"))
                actual.monto = valor if entra else -valor
            actual.tachado = tachado
            cerrar()
            continue
        if actual is None:                   # copiado sin la hora: la operación empieza por el nombre
            actual = Operacion(fecha=fecha)
        if not actual.nombre:
            actual.nombre = linea
        elif not actual.detalle and linea == actual.nombre:
            continue                         # el nombre repetido en su propia línea
        elif not actual.detalle:
            # A veces viene el nombre pegado al tipo: "Mercado LibreCompra"
            resto = linea[len(actual.nombre):] if linea.startswith(actual.nombre) else linea
            actual.detalle = resto.strip() or linea
        elif linea.lower() in _ESTADOS:
            actual.estado = linea
        else:
            actual.extras.append(linea)
    cerrar()
    _emparejar_devoluciones(ops)
    return ops


def _emparejar_devoluciones(ops: list[Operacion]):
    """Una devolución del mismo monto y el mismo comercio que un pago cancelado o rechazado
    solo te devuelve esa plata: no es un ingreso. Se marcan las dos para no contarlas."""
    sin_cobrar = [o for o in ops if o.monto and o.monto < 0 and not o.aprobada]
    for dev in ops:
        if not (dev.es_devolucion and dev.monto and dev.monto > 0):
            continue
        for pago in sin_cobrar:
            if (pago.anulada_por is None and pago.nombre.lower() == dev.nombre.lower()
                    and abs(abs(pago.monto) - dev.monto) < 0.005 and abs((pago.fecha - dev.fecha).days) <= 31):
                pago.anulada_por, dev.anulada_por = dev, pago
                break


# ─────────────────────────── archivos descargados ───────────────────────────

# Nombres de columna que se reconocen (en minúscula, sin tildes; "_" cuenta como espacio).
_COLUMNAS = {
    "fecha": ("release date", "fecha", "date", "fecha de operacion", "fecha operacion", "fecha de liberacion",
              "fecha movimiento", "fecha de movimiento", "transaction date", "dia"),
    "descripcion": ("transaction type", "descripcion", "detalle", "concepto", "description", "movimiento",
                    "operacion"),
    "monto": ("transaction net amount", "monto", "importe", "valor", "amount", "net amount", "monto neto",
              "importe neto"),
    "debito": ("debito", "debitos", "egreso", "egresos", "cargo", "cargos", "retiro"),
    "credito": ("credito", "creditos", "ingreso", "ingresos", "abono", "deposito"),
    "saldo": ("partial balance", "saldo", "balance", "saldo parcial"),
    "ref": ("reference id", "id de operacion", "numero de operacion", "nro de operacion", "id", "comprobante",
            "referencia", "source id"),
}
# Cómo empieza la descripción en el resumen de cuenta -> tipo de operación. Lo que sigue es el nombre.
_PREFIJOS = ("Transferencia enviada", "Transferencia recibida", "Pago con QR", "Pago de servicios",
             "Pago de servicio", "Pago con tarjeta", "Pago online", "Pago de cuota", "Pago", "Compra", "Cobro",
             "Devolución de dinero", "Devolución de pago", "Devolución", "Dinero retirado", "Dinero reservado", "Ingreso de dinero",
             "Débito por deuda", "Venta de dólares", "Venta de dólar", "Compra de dólares", "Compra de dólar",
             "Rendimientos", "Inversión", "Rescate", "Débito automático", "Extracción", "Recarga", "Retiro")


@dataclass
class LecturaArchivo:
    ops: list[Operacion]
    saldo: tuple[date, float] | None      # último saldo informado por el archivo (día, plata)
    errores: list[str]
    titular: str = ""                     # nombre del dueño de la cuenta (lo trae el PDF)
    verificado: list[str] = field(default_factory=list)   # resúmenes que cierran exacto con sus saldos
    saldos: dict[date, float] = field(default_factory=dict)   # saldo del banco al cierre de cada día


def _norm_col(texto) -> str:
    return re.sub(r"\s+", " ", normalizar(str(texto or "")).replace("_", " ")).strip()


def _detectar_columnas(fila) -> dict[str, int] | None:
    nombres = [_norm_col(c) for c in fila]
    cols: dict[str, int] = {}
    for clave, alias in _COLUMNAS.items():
        for i, n in enumerate(nombres):
            if i in cols.values():
                continue
            if n in alias or any(n.startswith(a + " ") for a in alias if len(a) > 3):
                cols[clave] = i
                break
    if "fecha" in cols and ("monto" in cols or "debito" in cols or "credito" in cols):
        return cols
    return None


def _fecha_celda(v) -> tuple[date | None, str]:
    """(fecha, hora) de una celda: objeto fecha de Excel o texto en varios formatos."""
    if isinstance(v, datetime):
        return v.date(), (f"{v:%H:%M}" if (v.hour or v.minute) else "")
    if isinstance(v, date):
        return v, ""
    t = str(v or "").strip()
    if not t:
        return None, ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?", t)            # 2026-08-09T10:22
    if m:
        hora = f"{m.group(4)}:{m.group(5)}" if m.group(4) and (m.group(4), m.group(5)) != ("00", "00") else ""
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), hora
        except ValueError:
            return None, ""
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?", t)  # 09-08-2026 10:22
    if m:
        anio = int(m.group(3))
        anio += 2000 if anio < 100 else 0
        hora = f"{int(m.group(4)):02d}:{m.group(5)}" if m.group(4) and (int(m.group(4)), m.group(5)) != (0, "00") else ""
        try:
            return date(anio, int(m.group(2)), int(m.group(1))), hora
        except ValueError:
            return None, ""
    return None, ""


def _monto_celda(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    t = str(v).strip()
    negativo = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        valor = parse_monto(t, negativo=True)
    except ValueError:
        return None
    return -abs(valor) if negativo else valor


def _partir_descripcion(desc: str) -> tuple[str, str]:
    """'Transferencia enviada Pedro Perez' -> ('Pedro Perez', 'Transferencia enviada')."""
    d = re.sub(r"\s+", " ", desc).strip()
    dn = normalizar(d)
    for prefijo in sorted(_PREFIJOS, key=len, reverse=True):
        if dn.startswith(normalizar(prefijo)):
            resto = d[len(prefijo):].strip(" -:")
            resto = re.sub(r"^(merpago|mercadopago|mp)\s*\*\s*", "", resto, flags=re.I)   # "Merpago*lavadero"
            return (resto or d), d[:len(prefijo)]
    return d, ""


def _filas_csv(datos: bytes) -> list[list[str]]:
    for codificacion in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = datos.decode(codificacion)
            break
        except UnicodeDecodeError:
            continue
    primeras = "\n".join(texto.splitlines()[:30])
    separador = max((";", ",", "\t"), key=primeras.count)
    return list(csv.reader(io.StringIO(texto), delimiter=separador))


def _filas_xlsx(ruta: Path) -> list[list]:
    try:
        import openpyxl
    except ImportError:
        raise ValueError("Para leer archivos .xlsx falta instalar openpyxl (pip install openpyxl). "
                         "También podés descargar el resumen en .csv.") from None
    libro = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    try:
        return [list(f) for f in libro.worksheets[0].iter_rows(values_only=True)]
    finally:
        libro.close()


def leer_filas(filas: list[list]) -> LecturaArchivo:
    """Interpreta una tabla (filas de celdas) como movimientos de banco."""
    cols, inicio = None, 0
    for i, fila in enumerate(filas[:60]):
        cols = _detectar_columnas(fila)
        if cols:
            inicio = i + 1
            break
    if not cols:
        return LecturaArchivo([], None, ["No encontré las columnas de fecha y monto. "
                                         "Si es de Mercado Pago, descargá el «Resumen de cuenta» en .csv o .xlsx."])
    ops: list[Operacion] = []
    saldo: tuple[date, float] | None = None
    descartadas = 0

    def celda(fila, clave):
        i = cols.get(clave)
        return fila[i] if i is not None and i < len(fila) else None

    for fila in filas[inicio:]:
        if not fila or all(c in (None, "") for c in fila):
            continue
        fecha, hora = _fecha_celda(celda(fila, "fecha"))
        if fecha is None:
            descartadas += 1
            continue
        if "monto" in cols:
            monto = _monto_celda(celda(fila, "monto"))
        else:
            monto = (_monto_celda(celda(fila, "credito")) or 0) - abs(_monto_celda(celda(fila, "debito")) or 0)
        if not monto:
            continue
        nombre, detalle = _partir_descripcion(str(celda(fila, "descripcion") or ""))
        ref = str(celda(fila, "ref") or "").strip()
        ref = ref[:-2] if ref.endswith(".0") else ref               # números que Excel guarda como 1234.0
        op = Operacion(fecha=fecha, hora=hora, nombre=nombre or "Sin descripción", detalle=detalle,
                       monto=monto, ref=ref, saldo=_monto_celda(celda(fila, "saldo")))
        ops.append(op)
        if op.saldo is not None and (saldo is None or fecha >= saldo[0]):
            saldo = (fecha, op.saldo)
    errores = [f"{descartadas} filas sin fecha válida se salt{'ó' if descartadas == 1 else 'aron'}."] if descartadas else []
    saldos, verificado, aviso = _saldos_por_dia(ops)
    errores += aviso
    ops.sort(key=lambda o: (o.fecha, o.hora), reverse=True)
    _emparejar_devoluciones(ops)
    return LecturaArchivo(ops, saldo, errores, saldos=saldos, verificado=verificado)


def _saldos_por_dia(ops_en_orden: list[Operacion]) -> tuple[dict[date, float], list[str], list[str]]:
    """Con la columna de saldo del banco: el saldo al cierre de cada día y un control de que las filas
    encadenan (saldo anterior + valor = saldo nuevo). Si no encadenan, falta alguna operación.
    Sirve aunque el archivo venga del más viejo al más nuevo o al revés."""
    con_saldo = [o for o in ops_en_orden if o.saldo is not None and o.monto is not None]
    if len(con_saldo) < 2:
        return {}, [], []

    def cortes(lista):
        return [(a, b) for a, b in zip(lista, lista[1:]) if abs(a.saldo + b.monto - b.saldo) > 0.01]

    cronologico = con_saldo
    if len(cortes(con_saldo[::-1])) < len(cortes(con_saldo)):
        cronologico = con_saldo[::-1]                     # el archivo venía del más nuevo al más viejo
    saldos: dict[date, float] = {}
    primero = cronologico[0]
    saldos[primero.fecha - timedelta(days=1)] = round(primero.saldo - primero.monto, 2)   # saldo inicial
    for o in cronologico:
        saldos[o.fecha] = o.saldo                         # el último del día queda como cierre
    saltos = cortes(cronologico)
    if not saltos:
        return saldos, [f"{len(cronologico)} operaciones que encadenan sin saltos con el saldo del banco"], []
    a, b = saltos[0]
    return saldos, [], [f"ojo: entre el {a.fecha:%d/%m/%Y} y el {b.fecha:%d/%m/%Y} el saldo del banco salta "
                        f"{dinero(b.saldo - a.saldo - b.monto)} sin operación: puede faltar alguna "
                        f"({len(saltos)} salto{'s' if len(saltos) != 1 else ''} en total)."]


def leer_archivo(ruta) -> LecturaArchivo:
    ruta = Path(ruta)
    try:
        if ruta.suffix.lower() in (".xlsx", ".xlsm"):
            filas = _filas_xlsx(ruta)
        elif ruta.suffix.lower() in (".csv", ".txt"):
            filas = _filas_csv(ruta.read_bytes())
        elif ruta.suffix.lower() == ".pdf":
            lectura = leer_pdf(ruta)
            lectura.errores = [f"{ruta.name}: {e}" for e in lectura.errores]
            return lectura
        else:
            return LecturaArchivo([], None, [f"{ruta.name}: solo se leen archivos .pdf, .csv y .xlsx."])
    except ValueError as error:
        return LecturaArchivo([], None, [f"{ruta.name}: {error}"])
    except Exception as error:                     # archivo dañado, sin permiso, etc.
        return LecturaArchivo([], None, [f"{ruta.name}: no se pudo abrir ({error})."])
    lectura = leer_filas(filas)
    lectura.errores = [e if e.startswith(ruta.name) else f"{ruta.name}: {e}" for e in lectura.errores]
    return lectura


def leer_archivos(rutas) -> LecturaArchivo:
    """Varios archivos juntos (por ejemplo, un resumen por mes)."""
    ops, errores, saldo, titular, verificado, saldos = [], [], None, "", [], {}
    for ruta in rutas:
        lectura = leer_archivo(ruta)
        ops += lectura.ops
        errores += lectura.errores
        titular = titular or lectura.titular
        verificado += lectura.verificado
        for dia, valor in lectura.saldos.items():
            saldos.setdefault(dia, valor)
        if lectura.saldo and (saldo is None or lectura.saldo[0] >= saldo[0]):
            saldo = lectura.saldo
    ops.sort(key=lambda o: (o.fecha, o.hora), reverse=True)
    _emparejar_devoluciones(ops)
    return LecturaArchivo(ops, saldo, errores, titular, verificado, saldos)


# ─────────────────────────── resumen de cuenta en PDF ───────────────────────────

_RE_FECHA_PDF = re.compile(r"^\d{2}-\d{2}-\d{4}$")
_RE_IMPORTE_PDF = re.compile(r"^-?[\d.]+,\d{2}$")


def _renglones_pdf(palabras, tolerancia=3.0):
    """Agrupa palabras por renglón (misma altura), de arriba hacia abajo y de izquierda a derecha."""
    renglones: list[list[dict]] = []
    for w in sorted(palabras, key=lambda w: (w["top"], w["x0"])):
        if renglones and abs(renglones[-1][0]["top"] - w["top"]) <= tolerancia:
            renglones[-1].append(w)
        else:
            renglones.append([w])
    return [sorted(r, key=lambda w: w["x0"]) for r in renglones]


def _texto(renglon) -> str:
    return " ".join(w["text"] for w in renglon)


def _deducir_columnas(palabras, ancho_pagina):
    """Sin fila de títulos: deduce dónde empieza la descripción, el número de operación y el valor
    mirando los renglones que tienen fecha a la izquierda, número de operación e importes."""
    izquierda = ancho_pagina * 0.3
    x_desc, x_id, x_valor = [], [], []
    for w in palabras:
        if not (_RE_FECHA_PDF.match(w["text"]) and w["x0"] < izquierda):
            continue
        mismo = sorted((p for p in palabras if abs(p["top"] - w["top"]) <= 4 and p["x0"] > w["x1"]),
                       key=lambda p: p["x0"])
        ref = next((p for p in mismo if p["text"].isdigit() and len(p["text"]) >= 8), None)
        importe = next((p for p in mismo if _RE_IMPORTE_PDF.match(p["text"]) or p["text"] == "$"), None)
        if ref is None or importe is None:
            continue
        x_id.append(ref["x0"])
        x_valor.append(importe["x0"])
        x_desc.append(w["x1"] + 4)
    if not x_id:
        return None
    return min(x_desc), min(x_id), min(x_valor)


def leer_pdf(ruta) -> LecturaArchivo:
    """Lee el "Resumen de cuenta en pesos" de Mercado Pago en PDF.

    Cada movimiento es un renglón con fecha, ID de operación, valor y saldo. La descripción puede
    partirse en dos renglones (uno arriba y otro abajo de la fecha): cada pedazo se asigna al
    movimiento cuya fecha está más cerca en altura. Las secciones en dólares se saltean.
    """
    try:
        import pdfplumber
    except ImportError:
        return LecturaArchivo([], None, ["para leer PDF falta instalar pdfplumber (pip install pdfplumber)."])
    filas, titular = [], ""
    inicial = final = None
    en_pesos = True
    textos_sueltos: list[str] = []          # páginas que no se pudieron leer por columnas
    try:
        with pdfplumber.open(ruta) as pdf:
            for pagina in pdf.pages:
                palabras = pagina.extract_words(x_tolerance=1.5, keep_blank_chars=False)
                renglones = _renglones_pdf(palabras)
                arriba = [normalizar(_texto(r)) for r in renglones[:4]]
                if any("resumen" in t and ("dolares" in t or "tenencias" in t) for t in arriba):
                    en_pesos = False
                elif any("resumen" in t and "pesos" in t for t in arriba):
                    en_pesos = True
                    if not titular and len(renglones) > 1:
                        titular = _texto(renglones[1]).strip()
                    for r in renglones[:14]:
                        importes = [w for w in r if _RE_IMPORTE_PDF.match(w["text"])]
                        # "Saldo inicial: $ X ............ Saldo final: $ Y" vienen en el mismo renglón
                        for w in importes:
                            etiqueta = normalizar(" ".join(x["text"] for x in r if x["x0"] < w["x0"])[-40:])
                            if etiqueta.rstrip(" $").endswith("saldo inicial:"):
                                inicial = parse_monto(w["text"], negativo=True)
                            elif etiqueta.rstrip(" $").endswith("saldo final:"):
                                final = parse_monto(w["text"], negativo=True)
                if not en_pesos:
                    continue
                cabecera = None
                for r in _renglones_pdf(palabras, tolerancia=8.0):
                    textos = {normalizar(w["text"]) for w in r}
                    if {"fecha", "valor", "saldo"} <= textos and ("descripcion" in textos or "detalle" in textos):
                        cabecera = r
                        break
                if cabecera is not None:
                    col = {normalizar(w["text"]): w["x0"] for w in cabecera}
                    x_desc, x_valor = col.get("descripcion", col.get("detalle")), col["valor"]
                    alto_cab = cabecera[0]["top"]
                    x_id = next((w["x0"] for w in palabras if w["text"] == "ID" and abs(w["top"] - alto_cab) < 14),
                                x_valor - 100)
                    cuerpo = [w for w in palabras if w["top"] > alto_cab + 8]
                else:
                    columnas = _deducir_columnas(palabras, pagina.width)
                    if columnas is None:
                        textos_sueltos.append(pagina.extract_text() or "")
                        continue
                    x_desc, x_id, x_valor = columnas
                    cuerpo = palabras
                anclas = [w for w in cuerpo if _RE_FECHA_PDF.match(w["text"]) and w["x0"] < x_desc - 5]
                movs = []
                for a in anclas:
                    mismo = sorted((w for w in cuerpo if abs(w["top"] - a["top"]) <= 4), key=lambda w: w["x0"])
                    ref = next((w["text"] for w in mismo if w["text"].isdigit() and len(w["text"]) >= 8
                                and x_id - 4 <= w["x0"] < x_valor - 10), "")
                    importes = [w["text"] for w in mismo if _RE_IMPORTE_PDF.match(w["text"])]
                    if not importes:
                        continue
                    movs.append({"top": a["top"], "fecha": a["text"], "ref": ref, "valor": importes[0],
                                 "saldo": importes[-1] if len(importes) > 1 else "", "desc": []})
                # cada pedazo de descripción va con el movimiento más cercano en altura
                for w in cuerpo:
                    if not (x_desc - 3 <= w["x0"] < x_id - 3) or _RE_FECHA_PDF.match(w["text"]):
                        continue
                    cerca = min(movs, key=lambda m: abs(m["top"] - w["top"]), default=None)
                    if cerca is not None and abs(cerca["top"] - w["top"]) <= 16:
                        cerca["desc"].append(w)
                for m in movs:
                    desc = " ".join(_texto(r) for r in _renglones_pdf(m["desc"]))
                    filas.append([m["fecha"], desc, m["ref"], m["valor"], m["saldo"]])
    except Exception as error:                     # PDF dañado o de otro tipo
        return LecturaArchivo([], None, [f"no se pudo leer el PDF ({error})."])
    if not filas:
        # Otro diseño de resumen: se lee como texto, renglón por renglón.
        por_texto = leer_texto_resumen("\n".join(textos_sueltos))
        if por_texto is not None and por_texto.ops:
            por_texto.titular = titular
            return por_texto
        if not any(t.strip() for t in textos_sueltos):
            return LecturaArchivo([], None, ["el PDF no tiene texto (parece una imagen escaneada). Descargá el "
                                             "resumen de nuevo desde Mercado Pago o usá el formato .csv."])
        return LecturaArchivo([], None, ["no encontré movimientos. ¿Es el «Resumen de cuenta» de Mercado Pago?"])
    lectura = leer_filas([["RELEASE_DATE", "TRANSACTION_TYPE", "REFERENCE_ID", "TRANSACTION_NET_AMOUNT",
                           "PARTIAL_BALANCE"]] + filas)
    lectura.titular = titular
    if inicial is not None and final is not None:
        suma = round(inicial + sum(o.monto for o in lectura.ops), 2)
        if abs(suma - final) < 0.01:
            lectura.verificado.append(f"{len(lectura.ops)} movimientos que cierran exacto con el saldo final "
                                      f"del resumen ({dinero(final)})")
        else:
            lectura.errores.append(f"ojo: los movimientos leídos suman {dinero(suma - inicial)} y el resumen dice "
                                   f"{dinero(final - inicial)}. Revisá que no falte ninguno.")
    return lectura


def es_propia(op: Operacion, titular: str) -> bool:
    """Transferencia entre tus propias cuentas (el nombre de la otra parte sos vos)."""
    if not titular or "transferencia" not in normalizar(op.detalle):
        return False
    tuyo = set(normalizar(titular).split())
    otro = set(re.findall(r"[a-zñ]+", normalizar(op.nombre)))
    return len(tuyo) >= 2 and tuyo <= otro


# ─────────────────────────── resumen copiado como texto ───────────────────────────

_RE_DIA_RESUMEN = re.compile(r"^(\d{2}[-/]\d{2}[-/]\d{4})(?:\s+(.*))?$")
_RE_COLA_RESUMEN = re.compile(r"(?:^|\s)(\d{8,})\s+\$?\s*(-?\s*[\d.]+,\d{2})\s+\$?\s*(-?\s*[\d.]+,\d{2})\s*$")
_RE_RUIDO_RESUMEN = re.compile(r"^(fecha\b.*|id de la.*|operaci[oó]n|descripci[oó]n.*|valor|saldo|\d+\s*/\s*\d+|"
                               r"detalle de movimientos.*)$", re.I)


def leer_texto_resumen(texto: str) -> LecturaArchivo | None:
    """Lee el "Resumen de cuenta" copiado como texto (del PDF o de la tabla de la web).

    Entiende tres formas:
        17-09-2025  Pago Comercio Ejemplo  100000000001  $ -1.000,00  $ 9.000,00   (un renglón o con tabs)
        01-08-2026 / Transferencia enviada Persona / Ejemplo / 100000000002 $ -2.000,00 $ 7.000,00
        01-08-2026 Pago Tienda.com / 1234567 / 100000000003 $ -500,00 $ 6.500,00
    Devuelve None si el texto no tiene esa forma (entonces se prueba como actividad pegada)."""
    filas, actual = [], None
    sueltas: list[str] = []          # renglones entre operaciones (forma "sándwich": van arriba de la fecha)
    faltan_abajo = 0                 # cuántos renglones de la operación anterior quedaron abajo de su fecha
    for crudo in texto.splitlines():
        linea = re.sub(r"\s+", " ", crudo.replace("\u00a0", " ")).strip()
        if not linea or _RE_RUIDO_RESUMEN.match(linea):
            continue
        dia = _RE_DIA_RESUMEN.match(linea)
        if dia:
            actual = {"fecha": dia.group(1).replace("/", "-"), "desc": [], "arriba": sueltas}
            sueltas, faltan_abajo = [], 0
            linea = dia.group(2) or ""
            if not linea:
                continue
        if actual is None:
            if faltan_abajo and filas:                    # resto de la descripción de la anterior
                filas[-1][1] = f"{filas[-1][1]} {linea}".strip()
                faltan_abajo -= 1
            else:
                sueltas.append(linea)
            continue
        cola = _RE_COLA_RESUMEN.search(linea)
        if cola:
            antes = linea[:cola.start()].strip()
            if antes:
                actual["desc"].append(antes)
            desc = actual["desc"]
            if not desc and actual["arriba"]:
                # "sándwich": una descripción de dos renglones queda uno arriba de la fecha y otro abajo.
                # Arriba solo cuenta el renglón pegado a la fecha (lo anterior es encabezado de la página).
                desc = actual["arriba"][-1:]
                faltan_abajo = 1
            filas.append([actual["fecha"], " ".join(desc), cola.group(1),
                          cola.group(2).replace(" ", ""), cola.group(3).replace(" ", "")])
            actual = None
        else:
            actual["desc"].append(linea)
    if not filas:
        return None
    return leer_filas([["RELEASE_DATE", "TRANSACTION_TYPE", "REFERENCE_ID", "TRANSACTION_NET_AMOUNT",
                        "PARTIAL_BALANCE"]] + filas)
