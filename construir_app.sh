#!/usr/bin/env bash
# Arma el programa en dist/ (Linux o Mac). En Linux hace falta el paquete python3-tk.
set -e
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q -r requirements.txt pyinstaller
.venv/bin/python -m PyInstaller --noconfirm --clean --log-level WARN \
    --onefile --windowed \
    --name "Gestor de Finanzas" \
    --add-data "icono.ico:." \
    --collect-data pdfminer \
    --collect-all pypdfium2 \
    --collect-all pypdfium2_raw \
    main.py
echo
echo "Listo: dist/Gestor de Finanzas"
