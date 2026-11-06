"""Comprobación de salud del contenedor: consulta /healthz/ (Django + base de datos) dentro del propio contenedor.

Envía como Host el primer nombre de DJANGO_ALLOWED_HOSTS; si no, Django rechazaría la petición (400).
Sale con 0 si responde {"status": "ok"} y con 1 en cualquier otro caso.
"""

import json
import os
import sys
import urllib.request

hosts = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost").split(",") if h.strip()]
host = (hosts[0] if hosts else "localhost").lstrip(".").replace("*", "") or "localhost"
request = urllib.request.Request("http://127.0.0.1:8000/healthz/", headers={"Host": host})
try:
    with urllib.request.urlopen(request, timeout=5) as response:
        sys.exit(0 if json.load(response).get("status") == "ok" else 1)
except Exception as error:  # noqa: BLE001 - cualquier fallo significa "no sano"
    print(f"healthcheck: {error}", file=sys.stderr)
    sys.exit(1)
