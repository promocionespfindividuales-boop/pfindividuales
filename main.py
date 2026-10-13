"""API de domiciliación — PF Individuales / Presta Fácil.

Flujo:
 1. Operaciones crea una liga por trabajador (POST /api/admin/ligas) y se la envía.
 2. El trabajador abre /d/{token}, captura CLABE, banco y tarjeta, y acepta la autorización.
 3. La tarjeta se tokeniza en el navegador con el procesador (Openpay/Conekta);
    a este servidor solo llegan el token, últimos 4 dígitos y marca. La CLABE se guarda cifrada.
"""
import csv
import io
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import config, db
from .bancos import BANCOS, banco_de_clabe, clabe_valida

config.validar()
db.inicializar()
fernet = Fernet(config.ENCRYPTION_KEY.encode())

app = FastAPI(title="PF Individuales · Domiciliación", version="1.0.0",
              docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.middleware("http")
async def cabeceras_seguridad(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith(("/api/", "/d/", "/admin")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def ahora() -> datetime:
    return datetime.now(timezone.utc)


PERIODICIDADES = {"semanal": "semanal", "catorcenal": "catorcenal",
                  "quincenal": "quincenal", "mensual": "mensual"}


def texto_autorizacion(liga) -> str:
    monto = (f"hasta ${liga['monto_descuento']:,.2f} MXN" if liga["monto_descuento"]
             else "por el importe de las amortizaciones de mi crédito")
    periodo = liga["periodicidad"] or "conforme al calendario de pagos de mi crédito"
    contacto = " ".join(x for x in (config.EMPRESA_TELEFONO, config.EMPRESA_CORREO) if x)
    return (
        f"Autorizo a {config.EMPRESA_RAZON_SOCIAL} ({config.EMPRESA_NOMBRE}) a realizar cargos "
        f"recurrentes a la tarjeta y/o cuenta CLABE registradas en este formulario, {monto}, "
        f"con periodicidad {periodo}, para cubrir los pagos de mi crédito, incluyendo, en su caso, "
        f"la comisión del servicio de cobro. Esta autorización permanecerá vigente hasta la "
        f"liquidación total del crédito. Puedo solicitar su cancelación en cualquier momento "
        f"ante {config.EMPRESA_NOMBRE}{' (' + contacto + ')' if contacto else ''} o ante mi banco."
    )


# ───────────────────────── Seguridad admin ─────────────────────────

def requiere_admin(x_api_key: str = Header(default="")):
    if not secrets.compare_digest(x_api_key, config.ADMIN_API_KEY):
        raise HTTPException(401, "API key inválida")


# ───────────────────────── Modelos ─────────────────────────

class LigaIn(BaseModel):
    nombre: str = Field(min_length=3, max_length=120)
    num_empleado: str | None = Field(default=None, max_length=40)
    empresa: str | None = Field(default=None, max_length=120)
    telefono: str | None = Field(default=None, max_length=20)
    correo: str | None = Field(default=None, max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    monto_descuento: float | None = Field(default=None, gt=0, le=1_000_000)
    periodicidad: Literal["semanal", "catorcenal", "quincenal", "mensual"] | None = None
    dias_vigencia: int = Field(default=config.DIAS_VIGENCIA_DEFAULT, ge=1, le=60)


class DomiciliacionIn(BaseModel):
    titular: str = Field(min_length=3, max_length=120)
    clabe: str
    banco: str = Field(min_length=2, max_length=60)
    tarjeta_token: str = Field(min_length=4, max_length=120)
    tarjeta_ultimos4: str
    tarjeta_marca: str | None = Field(default=None, max_length=30)
    device_session_id: str | None = Field(default=None, max_length=120)
    acepto_terminos: bool

    @field_validator("clabe")
    @classmethod
    def _clabe(cls, v: str) -> str:
        v = re.sub(r"\s", "", v)
        if not clabe_valida(v):
            raise ValueError("CLABE inválida: verifica los 18 dígitos")
        return v

    @field_validator("tarjeta_ultimos4")
    @classmethod
    def _ult4(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}", v):
            raise ValueError("Últimos 4 dígitos inválidos")
        return v

    @field_validator("tarjeta_token")
    @classmethod
    def _token(cls, v: str) -> str:
        # Defensa: si alguien intenta mandar un número de tarjeta en lugar de token, se rechaza.
        if re.fullmatch(r"[\d\s-]{12,23}", v):
            raise ValueError("Se recibió un número de tarjeta en lugar de un token")
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", v):
            raise ValueError("Token de tarjeta inválido")
        return v


# ───────────────────────── Utilidades ─────────────────────────

def obtener_liga(con, token: str):
    liga = con.execute("SELECT * FROM ligas WHERE token = ?", (token,)).fetchone()
    if not liga:
        raise HTTPException(404, "La liga no existe")
    if liga["estado"] == "completada":
        raise HTTPException(409, "Esta liga ya fue utilizada")
    if liga["estado"] == "revocada":
        raise HTTPException(410, "Esta liga fue cancelada")
    if datetime.fromisoformat(liga["expira_en"]) < ahora():
        raise HTTPException(410, "Esta liga expiró; solicita una nueva a tu asesor")
    return liga


def url_liga(token: str) -> str:
    return f"{config.PUBLIC_BASE_URL}/d/{token}"


def estado_real(liga) -> str:
    if liga["estado"] == "pendiente" and datetime.fromisoformat(liga["expira_en"]) < ahora():
        return "expirada"
    return liga["estado"]


# ───────────────────────── Páginas ─────────────────────────

@app.get("/d/{token}", include_in_schema=False)
def pagina_formulario(token: str):
    return FileResponse(config.STATIC_DIR / "form.html")


@app.get("/admin", include_in_schema=False)
def pagina_admin():
    return FileResponse(config.STATIC_DIR / "admin.html")


@app.get("/api/salud")
def salud():
    return {"ok": True, "procesador": config.PROCESADOR}


# ───────────────────────── API pública (trabajador) ─────────────────────────

@app.get("/api/bancos")
def bancos():
    return [{"clave": k, "nombre": v} for k, v in sorted(BANCOS.items(), key=lambda x: x[1])]


@app.get("/api/ligas/{token}")
def info_liga(token: str):
    with db.tx() as con:
        liga = obtener_liga(con, token)
    return {
        "nombre": liga["nombre"],
        "empresa": liga["empresa"],
        "monto_descuento": liga["monto_descuento"],
        "periodicidad": liga["periodicidad"],
        "expira_en": liga["expira_en"],
        "texto_autorizacion": texto_autorizacion(liga),
        "financiera": config.EMPRESA_NOMBRE,
        "procesador": config.procesador_publico(),
    }


@app.post("/api/ligas/{token}", status_code=201)
def registrar(token: str, datos: DomiciliacionIn, request: Request):
    if not datos.acepto_terminos:
        raise HTTPException(422, "Debes aceptar la autorización de domiciliación")
    if config.PROCESADOR == "demo" and not datos.tarjeta_token.startswith("demo_"):
        raise HTTPException(422, "Token de tarjeta no válido para el modo demo")

    with db.tx() as con:
        liga = obtener_liga(con, token)
        banco_clabe = banco_de_clabe(datos.clabe)
        banco = banco_clabe or datos.banco.strip().upper()
        con.execute(
            """INSERT INTO domiciliaciones
               (liga_id, titular, clabe_cifrada, clabe_ultimos4, banco, procesador,
                tarjeta_token, tarjeta_ultimos4, tarjeta_marca, device_session_id,
                acepto_terminos, texto_autorizacion, ip, user_agent, registrada_en)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (liga["id"], datos.titular.strip(),
             fernet.encrypt(datos.clabe.encode()).decode(), datos.clabe[-4:], banco,
             config.PROCESADOR, datos.tarjeta_token, datos.tarjeta_ultimos4,
             (datos.tarjeta_marca or "").lower() or None, datos.device_session_id,
             1, texto_autorizacion(liga),
             request.headers.get("x-forwarded-for", request.client.host if request.client else None),
             request.headers.get("user-agent", "")[:300], ahora().isoformat()),
        )
        con.execute("UPDATE ligas SET estado = 'completada' WHERE id = ?", (liga["id"],))
    return {"ok": True, "mensaje": "Tus datos se registraron correctamente"}


# ───────────────────────── API administrativa ─────────────────────────

@app.post("/api/admin/ligas", status_code=201, dependencies=[Depends(requiere_admin)])
def crear_liga(datos: LigaIn):
    token = secrets.token_urlsafe(24)
    creada = ahora()
    with db.tx() as con:
        con.execute(
            """INSERT INTO ligas (token, nombre, num_empleado, empresa, telefono, correo,
               monto_descuento, periodicidad, creada_en, expira_en)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (token, datos.nombre.strip(), datos.num_empleado, datos.empresa, datos.telefono,
             datos.correo, datos.monto_descuento, datos.periodicidad, creada.isoformat(),
             (creada + timedelta(days=datos.dias_vigencia)).isoformat()),
        )
    return {"token": token, "url": url_liga(token),
            "expira_en": (creada + timedelta(days=datos.dias_vigencia)).isoformat()}


@app.get("/api/admin/ligas", dependencies=[Depends(requiere_admin)])
def listar_ligas(estado: str | None = None):
    with db.tx() as con:
        filas = con.execute(
            """SELECT l.*, d.banco, d.clabe_ultimos4, d.tarjeta_ultimos4, d.tarjeta_marca,
                      d.registrada_en
               FROM ligas l LEFT JOIN domiciliaciones d ON d.liga_id = l.id
               ORDER BY l.id DESC""").fetchall()
    res = []
    for f in filas:
        e = estado_real(f)
        if estado and e != estado:
            continue
        res.append({
            "id": f["id"], "nombre": f["nombre"], "num_empleado": f["num_empleado"],
            "empresa": f["empresa"], "telefono": f["telefono"], "estado": e,
            "url": url_liga(f["token"]) if e == "pendiente" else None,
            "creada_en": f["creada_en"], "expira_en": f["expira_en"],
            "banco": f["banco"], "clabe_ultimos4": f["clabe_ultimos4"],
            "tarjeta": f"{(f['tarjeta_marca'] or '').upper()} •••• {f['tarjeta_ultimos4']}"
                       if f["tarjeta_ultimos4"] else None,
            "registrada_en": f["registrada_en"],
        })
    return res


@app.get("/api/admin/ligas/{liga_id}", dependencies=[Depends(requiere_admin)])
def detalle(liga_id: int):
    """Incluye la CLABE completa (descifrada) para operación."""
    with db.tx() as con:
        liga = con.execute("SELECT * FROM ligas WHERE id = ?", (liga_id,)).fetchone()
        if not liga:
            raise HTTPException(404, "No existe")
        d = con.execute("SELECT * FROM domiciliaciones WHERE liga_id = ?", (liga_id,)).fetchone()
    out = {k: liga[k] for k in liga.keys() if k != "token"}
    out["estado"] = estado_real(liga)
    if d:
        out["domiciliacion"] = {
            "titular": d["titular"], "clabe": fernet.decrypt(d["clabe_cifrada"]).decode(),
            "banco": d["banco"], "procesador": d["procesador"], "tarjeta_token": d["tarjeta_token"],
            "tarjeta_ultimos4": d["tarjeta_ultimos4"], "tarjeta_marca": d["tarjeta_marca"],
            "device_session_id": d["device_session_id"],
            "texto_autorizacion": d["texto_autorizacion"], "ip": d["ip"],
            "user_agent": d["user_agent"], "registrada_en": d["registrada_en"],
        }
    return out


@app.post("/api/admin/ligas/{liga_id}/revocar", dependencies=[Depends(requiere_admin)])
def revocar(liga_id: int):
    with db.tx() as con:
        cur = con.execute("UPDATE ligas SET estado='revocada' WHERE id=? AND estado='pendiente'",
                          (liga_id,))
    if cur.rowcount == 0:
        raise HTTPException(409, "Solo se pueden revocar ligas pendientes")
    return {"ok": True}


@app.get("/api/admin/export.csv", dependencies=[Depends(requiere_admin)])
def exportar():
    with db.tx() as con:
        filas = con.execute(
            """SELECT l.nombre, l.num_empleado, l.empresa, l.monto_descuento, l.periodicidad,
                      d.* FROM domiciliaciones d JOIN ligas l ON l.id = d.liga_id
               ORDER BY d.registrada_en""").fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["nombre", "num_empleado", "empresa", "titular", "banco", "clabe",
                "procesador", "tarjeta_token", "tarjeta_marca", "tarjeta_ultimos4",
                "monto_descuento", "periodicidad", "registrada_en", "ip"])
    for f in filas:
        w.writerow([f["nombre"], f["num_empleado"], f["empresa"], f["titular"], f["banco"],
                    fernet.decrypt(f["clabe_cifrada"]).decode(), f["procesador"],
                    f["tarjeta_token"], f["tarjeta_marca"], f["tarjeta_ultimos4"],
                    f["monto_descuento"], f["periodicidad"], f["registrada_en"], f["ip"]])
    nombre = f"domiciliaciones_{ahora():%Y%m%d}.csv"
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
