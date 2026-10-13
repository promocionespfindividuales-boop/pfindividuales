# PF Individuales · Domiciliación

Ligas seguras para que los trabajadores registren **CLABE, banco y tarjeta de débito** y acepten la autorización de cargos recurrentes.

## Cómo funciona

1. Operaciones entra a `/admin`, captura al trabajador (nombre, empresa, monto, periodicidad) y genera una liga.
2. La liga se envía por WhatsApp (botón incluido) o correo. Es **única, de un solo uso y caduca** (7 días por defecto).
3. El trabajador abre la liga en su celular, captura sus datos y acepta la autorización.
4. En el panel ves el estado (pendiente / completada / expirada / revocada), el detalle con la CLABE y exportas a CSV.

## Seguridad de los datos

| Dato | Qué se guarda |
|---|---|
| Número de tarjeta, CVV, vencimiento | **Nada.** Se tokenizan en el navegador directo con el procesador (Openpay o Conekta). Solo se guardan el token, los últimos 4 dígitos y la marca. |
| CLABE | Cifrada (AES/Fernet) con `ENCRYPTION_KEY`. Solo se descifra en el panel o en el CSV. |
| Consentimiento | El texto exacto aceptado, la fecha y hora, la IP y el dispositivo, como evidencia ante aclaraciones. |

Así no necesitas certificarte en PCI DSS para almacenar tarjetas. Los cargos se hacen con el **token** desde la API privada del procesador.

> El texto de autorización está en `app/main.py → texto_autorizacion()`. Revísalo con tu área legal o tu contrato de crédito antes de producción.

## Correr localmente

```bash
pip install -r requirements.txt
cp .env.example .env    # llena ADMIN_API_KEY y ENCRYPTION_KEY
set -a; source .env; set +a
uvicorn app.main:app --reload
```

- Panel: http://localhost:8000/admin
- Documentación de la API: http://localhost:8000/api/docs
- Pruebas: `pytest -q`

En modo `PROCESADOR=demo` la tarjeta solo se valida (Luhn y marca) y se genera un token falso. Úsalo para probar el flujo.

## Conectar el procesador

**Openpay:** en `.env` pon `PROCESADOR=openpay`, `OPENPAY_MERCHANT_ID` y `OPENPAY_PUBLIC_KEY` (la **pública** `pk_...`). Deja `OPENPAY_SANDBOX=true` hasta terminar de probar. Además del token, se guarda el `device_session_id` antifraude.

**Conekta:** `PROCESADOR=conekta` y `CONEKTA_PUBLIC_KEY` (la `key_...` pública).

Las llaves **privadas** nunca van en este servidor. Pertenecen al sistema que ejecuta los cobros.

## Producción

- **HTTPS obligatorio.** Por ejemplo Railway, Render o un VPS con Nginx y Let's Encrypt.
- `PUBLIC_BASE_URL` = tu dominio real (con él se arman las ligas).
- Respalda `domiciliacion.db` **y** `ENCRYPTION_KEY`. Sin la llave, las CLABE no se pueden descifrar.
- Usa una `ADMIN_API_KEY` larga y no la compartas por chat.

## Endpoints

| Método | Ruta | Uso |
|---|---|---|
| GET | `/d/{token}` | Formulario del trabajador |
| GET / POST | `/api/ligas/{token}` | Info de la liga / registrar datos |
| GET | `/api/bancos` | Catálogo de bancos por CLABE |
| POST | `/api/admin/ligas` | Crear liga *(X-API-Key)* |
| GET | `/api/admin/ligas` | Listar (filtro `?estado=`) |
| GET | `/api/admin/ligas/{id}` | Detalle con CLABE descifrada |
| POST | `/api/admin/ligas/{id}/revocar` | Cancelar liga pendiente |
| GET | `/api/admin/export.csv` | Exportar domiciliaciones |
