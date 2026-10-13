import os
import tempfile

from cryptography.fernet import Fernet

os.environ.update(
    DB_PATH=os.path.join(tempfile.mkdtemp(), "test.db"),
    ADMIN_API_KEY="clave-test",
    ENCRYPTION_KEY=Fernet.generate_key().decode(),
    PROCESADOR="demo",
    PUBLIC_BASE_URL="https://pagos.ejemplo.mx",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.bancos import clabe_valida, digito_verificador  # noqa: E402
from app.main import app  # noqa: E402

c = TestClient(app)
H = {"X-API-Key": "clave-test"}


def clabe(prefijo="012180"):
    base = (prefijo + "0" * 17)[:17]
    base = base[:-4] + "1234"
    return base + str(digito_verificador(base))


def nueva_liga(**kw):
    r = c.post("/api/admin/ligas", headers=H, json={"nombre": "Juan Pérez López", "empresa": "Camiones Rivera",
                                                    "monto_descuento": 850.5, "periodicidad": "quincenal", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def payload(**kw):
    return {"titular": "Juan Pérez López", "clabe": clabe(), "banco": "BBVA",
            "tarjeta_token": "demo_abc123", "tarjeta_ultimos4": "4242",
            "tarjeta_marca": "visa", "acepto_terminos": True, **kw}


def test_clabe():
    assert clabe_valida(clabe())
    assert not clabe_valida(clabe()[:-1] + str((int(clabe()[-1]) + 1) % 10))
    assert not clabe_valida("123")


def test_admin_requiere_key():
    assert c.post("/api/admin/ligas", json={"nombre": "X Y Z"}).status_code == 401
    assert c.get("/api/admin/ligas", headers={"X-API-Key": "mal"}).status_code == 401


def test_flujo_completo():
    liga = nueva_liga()
    assert liga["url"].startswith("https://pagos.ejemplo.mx/d/")
    tok = liga["token"]

    info = c.get(f"/api/ligas/{tok}").json()
    assert info["nombre"] == "Juan Pérez López"
    assert "850.50" in info["texto_autorizacion"]
    assert info["procesador"] == {"tipo": "demo"}

    assert c.get(f"/d/{tok}").status_code == 200

    r = c.post(f"/api/ligas/{tok}", json=payload())
    assert r.status_code == 201, r.text

    # liga de un solo uso
    assert c.get(f"/api/ligas/{tok}").status_code == 409
    assert c.post(f"/api/ligas/{tok}", json=payload()).status_code == 409

    lista = c.get("/api/admin/ligas", headers=H).json()
    fila = next(x for x in lista if x["nombre"] == "Juan Pérez López" and x["estado"] == "completada")
    assert fila["banco"] == "BBVA MÉXICO"  # detectado por CLABE
    assert fila["url"] is None

    det = c.get(f"/api/admin/ligas/{fila['id']}", headers=H).json()
    assert det["domiciliacion"]["clabe"] == clabe()
    assert "token" not in det

    csv = c.get("/api/admin/export.csv", headers=H).text
    assert clabe() in csv


def test_clabe_no_se_guarda_en_claro():
    import sqlite3
    tok = nueva_liga(nombre="Ana Torres")["token"]
    c.post(f"/api/ligas/{tok}", json=payload(clabe=clabe("072650")))
    raw = open(os.environ["DB_PATH"], "rb").read()
    assert clabe("072650").encode() not in raw
    con = sqlite3.connect(os.environ["DB_PATH"])
    assert con.execute("SELECT count(*) FROM domiciliaciones WHERE clabe_cifrada LIKE '0726%'").fetchone()[0] == 0


def test_rechaza_numero_de_tarjeta_como_token():
    tok = nueva_liga()["token"]
    r = c.post(f"/api/ligas/{tok}", json=payload(tarjeta_token="4242424242424242"))
    assert r.status_code == 422


def test_validaciones():
    tok = nueva_liga()["token"]
    assert c.post(f"/api/ligas/{tok}", json=payload(clabe="012180000000000000")).status_code == 422
    assert c.post(f"/api/ligas/{tok}", json=payload(acepto_terminos=False)).status_code == 422
    assert c.post(f"/api/ligas/{tok}", json=payload(tarjeta_ultimos4="42a2")).status_code == 422
    assert c.post(f"/api/ligas/{tok}", json=payload(tarjeta_token="tok_real")).status_code == 422  # demo exige demo_
    assert c.get(f"/api/ligas/{tok}").status_code == 200  # sigue pendiente


def test_revocar_y_inexistente():
    liga = nueva_liga(nombre="Pedro Ruiz")
    lid = next(x["id"] for x in c.get("/api/admin/ligas", headers=H).json() if x["nombre"] == "Pedro Ruiz")
    assert c.post(f"/api/admin/ligas/{lid}/revocar", headers=H).status_code == 200
    assert c.get(f"/api/ligas/{liga['token']}").status_code == 410
    assert c.get("/api/ligas/no-existe").status_code == 404


def test_expirada():
    import sqlite3
    liga = nueva_liga(nombre="Luis Expirado")
    con = sqlite3.connect(os.environ["DB_PATH"])
    con.execute("UPDATE ligas SET expira_en='2020-01-01T00:00:00+00:00' WHERE token=?", (liga["token"],))
    con.commit()
    assert c.get(f"/api/ligas/{liga['token']}").status_code == 410
    assert any(x["estado"] == "expirada" for x in c.get("/api/admin/ligas?estado=expirada", headers=H).json())
