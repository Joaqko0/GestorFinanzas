"""Almacenamiento: SQLite donde cada movimiento se guarda cifrado (AES + firma, vía Fernet).

Si abrís el archivo con cualquier visor de SQLite solo ves texto ilegible. La clave sale de tu
contraseña (PBKDF2, 480.000 vueltas); la contraseña en sí nunca se guarda.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
from datetime import date
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from logica import Deuda, Movimiento

ITERACIONES = 480_000
MARCA = b"gestor-finanzas-ok"        # se cifra al crear la contraseña para poder verificarla después


class ClaveIncorrecta(Exception):
    pass


def ruta_datos() -> Path:
    """Dónde vive el archivo de datos (se puede cambiar con la variable GESTOR_FINANZAS_DATOS)."""
    especial = os.environ.get("GESTOR_FINANZAS_DATOS")
    if especial:
        return Path(especial)
    base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "GestorFinanzas" / "finanzas.dat"


class Boveda:
    def __init__(self, ruta):
        ruta = Path(ruta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(ruta)
        self.con.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor);
            CREATE TABLE IF NOT EXISTS movimientos (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                dato BLOB NOT NULL            -- todo el movimiento, cifrado
            );
            CREATE TABLE IF NOT EXISTS deudas (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                dato BLOB NOT NULL            -- toda la deuda, cifrada
            );
            """
        )
        self.fernet: Fernet | None = None

    # ── datos de configuración ──
    def _leer_meta(self, clave):
        fila = self.con.execute("SELECT valor FROM meta WHERE clave = ?", (clave,)).fetchone()
        return fila[0] if fila else None

    def _guardar_meta(self, clave, valor):
        self.con.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES (?, ?)", (clave, valor))
        self.con.commit()

    def leer_tema(self) -> str:
        tema = self._leer_meta("tema")
        return tema if tema in ("claro", "oscuro") else "claro"

    def guardar_tema(self, tema: str):
        self._guardar_meta("tema", tema)

    # ── contraseña ──
    @property
    def es_nueva(self) -> bool:
        return self._leer_meta("sal") is None

    def desbloquear(self, contrasena: str):
        """Crea la contraseña la primera vez; después la verifica. Lanza ClaveIncorrecta si no coincide."""
        sal = self._leer_meta("sal")
        primera_vez = sal is None
        if primera_vez:
            sal = os.urandom(16)
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sal, iterations=ITERACIONES)
        fernet = Fernet(base64.urlsafe_b64encode(kdf.derive(contrasena.encode("utf-8"))))
        if primera_vez:
            self._guardar_meta("sal", sal)
            self._guardar_meta("verificacion", fernet.encrypt(MARCA))
        else:
            try:
                ok = fernet.decrypt(self._leer_meta("verificacion")) == MARCA
            except InvalidToken:
                ok = False
            if not ok:
                raise ClaveIncorrecta()
        self.fernet = fernet

    # ── configuración cifrada (saldo real, categorías aprendidas) ──
    def _cifrar_json(self, obj) -> bytes:
        return self.fernet.encrypt(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def leer_config(self, clave: str, defecto=None):
        dato = self._leer_meta(f"cfg:{clave}")
        if dato is None:
            return defecto
        try:
            return json.loads(self.fernet.decrypt(dato))
        except (InvalidToken, ValueError):
            return defecto

    def guardar_config(self, clave: str, valor):
        if valor is None:
            self.con.execute("DELETE FROM meta WHERE clave = ?", (f"cfg:{clave}",))
            self.con.commit()
        else:
            self._guardar_meta(f"cfg:{clave}", self._cifrar_json(valor))

    def leer_ancla(self) -> tuple[date, float] | None:
        """Tu saldo real de un día: (día, plata). None si nunca lo cargaste."""
        a = self.leer_config("ancla")
        return (date.fromisoformat(a[0]), float(a[1])) if a else None

    def guardar_ancla(self, ancla: tuple[date, float] | None):
        self.guardar_config("ancla", [ancla[0].isoformat(), ancla[1]] if ancla else None)

    # ── movimientos y deudas (INSERT / SELECT / UPDATE / DELETE) ──
    def _insertar(self, tabla: str, obj) -> int:
        cur = self.con.execute(f"INSERT INTO {tabla} (dato) VALUES (?)", (self._cifrar_json(obj.a_dict()),))
        obj.id = cur.lastrowid
        return obj.id

    def agregar(self, mov: Movimiento) -> int:
        self._insertar("movimientos", mov)
        self.con.commit()
        return mov.id

    def agregar_varios(self, movs: list[Movimiento]):
        """Muchos de una vez (importaciones): una sola escritura a disco."""
        for mov in movs:
            self._insertar("movimientos", mov)
        self.con.commit()

    def actualizar(self, mov: Movimiento):
        self.con.execute("UPDATE movimientos SET dato = ? WHERE id = ?", (self._cifrar_json(mov.a_dict()), mov.id))
        self.con.commit()

    def actualizar_varios(self, movs: list[Movimiento]):
        for mov in movs:
            self.con.execute("UPDATE movimientos SET dato = ? WHERE id = ?", (self._cifrar_json(mov.a_dict()), mov.id))
        self.con.commit()

    def eliminar_varios(self, ids):
        """Borra muchos movimientos en una sola escritura a disco."""
        self.con.executemany("DELETE FROM movimientos WHERE id = ?", [(i,) for i in ids])
        self.con.commit()

    def eliminar_deudas_varias(self, ids):
        self.con.executemany("DELETE FROM deudas WHERE id = ?", [(i,) for i in ids])
        self.con.commit()

    def eliminar(self, id_: int):
        self.con.execute("DELETE FROM movimientos WHERE id = ?", (id_,))
        self.con.commit()

    def listar(self) -> list[Movimiento]:
        """Todos los movimientos, del más nuevo al más viejo."""
        filas = self.con.execute("SELECT id, dato FROM movimientos ORDER BY id DESC").fetchall()
        return [Movimiento.desde_dict(json.loads(self.fernet.decrypt(dato)), id_) for id_, dato in filas]

    def agregar_deuda(self, deuda: Deuda) -> int:
        self._insertar("deudas", deuda)
        self.con.commit()
        return deuda.id

    def actualizar_deuda(self, deuda: Deuda):
        self.con.execute("UPDATE deudas SET dato = ? WHERE id = ?", (self._cifrar_json(deuda.a_dict()), deuda.id))
        self.con.commit()

    def eliminar_deuda(self, id_: int):
        self.con.execute("DELETE FROM deudas WHERE id = ?", (id_,))
        self.con.commit()

    def listar_deudas(self) -> list[Deuda]:
        filas = self.con.execute("SELECT id, dato FROM deudas ORDER BY id DESC").fetchall()
        return [Deuda.desde_dict(json.loads(self.fernet.decrypt(dato)), id_) for id_, dato in filas]

    def cerrar(self):
        self.con.close()
