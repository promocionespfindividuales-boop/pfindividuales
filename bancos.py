"""Validación de CLABE y catálogo de bancos (primeros 3 dígitos de la CLABE)."""

BANCOS = {
    "002": "BANAMEX", "006": "BANCOMEXT", "009": "BANOBRAS", "012": "BBVA MÉXICO",
    "014": "SANTANDER", "019": "BANJÉRCITO", "021": "HSBC", "030": "BAJÍO",
    "036": "INBURSA", "042": "MIFEL", "044": "SCOTIABANK", "058": "BANREGIO",
    "059": "INVEX", "060": "BANSI", "062": "AFIRME", "072": "BANORTE",
    "106": "BANK OF AMERICA", "112": "BMONEX", "113": "VE POR MÁS", "127": "AZTECA",
    "130": "COMPARTAMOS", "132": "MULTIVA", "133": "ACTINVER", "136": "INTERCAM",
    "137": "BANCOPPEL", "138": "ABC CAPITAL", "140": "CONSUBANCO", "143": "CIBANCO",
    "145": "BBASE", "152": "BANCREA", "156": "SABADELL", "166": "BANCO DEL BIENESTAR",
    "167": "HEY BANCO", "638": "NU MÉXICO", "646": "STP", "722": "MERCADO PAGO",
    "728": "SPIN BY OXXO",
}

_PESOS = (3, 7, 1)


def digito_verificador(clabe17: str) -> int:
    suma = sum((int(d) * _PESOS[i % 3]) % 10 for i, d in enumerate(clabe17))
    return (10 - suma % 10) % 10


def clabe_valida(clabe: str) -> bool:
    return (len(clabe) == 18 and clabe.isdigit()
            and digito_verificador(clabe[:17]) == int(clabe[17]))


def banco_de_clabe(clabe: str) -> str | None:
    return BANCOS.get(clabe[:3]) if clabe else None
