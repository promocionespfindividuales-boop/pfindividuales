"""Configuración por variables de entorno (ver .env.example)."""
import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

DB_PATH = _env("DB_PATH", str(BASE_DIR / "domiciliacion.db"))

# URL pública donde vive el formulario (para armar las ligas)
PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

# Llave del panel administrativo (header X-API-Key)
ADMIN_API_KEY = _env("ADMIN_API_KEY")

# Llave Fernet para cifrar CLABE en la base de datos.
# Generar con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY = _env("ENCRYPTION_KEY")

# Datos de la financiera que aparecen en la autorización
EMPRESA_NOMBRE = _env("EMPRESA_NOMBRE", "PF Individuales")
EMPRESA_RAZON_SOCIAL = _env("EMPRESA_RAZON_SOCIAL", "Presta Fácil")
EMPRESA_TELEFONO = _env("EMPRESA_TELEFONO", "")
EMPRESA_CORREO = _env("EMPRESA_CORREO", "")

# Procesador de cobro: openpay | conekta | demo
# La tarjeta se tokeniza en el navegador; el número nunca llega a este servidor.
PROCESADOR = _env("PROCESADOR", "demo").lower()
OPENPAY_MERCHANT_ID = _env("OPENPAY_MERCHANT_ID")
OPENPAY_PUBLIC_KEY = _env("OPENPAY_PUBLIC_KEY")
OPENPAY_SANDBOX = _env("OPENPAY_SANDBOX", "true").lower() == "true"
CONEKTA_PUBLIC_KEY = _env("CONEKTA_PUBLIC_KEY")

DIAS_VIGENCIA_DEFAULT = int(_env("DIAS_VIGENCIA_DEFAULT", "7"))


def validar():
    faltan = [n for n in ("ADMIN_API_KEY", "ENCRYPTION_KEY") if not globals()[n]]
    if faltan:
        raise RuntimeError(f"Faltan variables de entorno: {', '.join(faltan)}")
    if PROCESADOR not in ("openpay", "conekta", "demo"):
        raise RuntimeError("PROCESADOR debe ser openpay, conekta o demo")
    if PROCESADOR == "openpay" and not (OPENPAY_MERCHANT_ID and OPENPAY_PUBLIC_KEY):
        raise RuntimeError("Faltan OPENPAY_MERCHANT_ID / OPENPAY_PUBLIC_KEY")
    if PROCESADOR == "conekta" and not CONEKTA_PUBLIC_KEY:
        raise RuntimeError("Falta CONEKTA_PUBLIC_KEY")


def procesador_publico() -> dict:
    """Solo llaves PÚBLICAS; nunca exponer llaves privadas."""
    if PROCESADOR == "openpay":
        return {"tipo": "openpay", "merchant_id": OPENPAY_MERCHANT_ID,
                "public_key": OPENPAY_PUBLIC_KEY, "sandbox": OPENPAY_SANDBOX}
    if PROCESADOR == "conekta":
        return {"tipo": "conekta", "public_key": CONEKTA_PUBLIC_KEY}
    return {"tipo": "demo"}
