import re


def normalizar_rut(texto):
    """Deja el RUT sin puntos ni guion y con la K en mayúscula: '15.482.331-k' -> '15482331K'."""
    return re.sub(r'[^0-9kK]', '', texto or '').upper()


def _digito_verificador(cuerpo):
    suma, factor = 0, 2
    for digito in reversed(cuerpo):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    resto = 11 - suma % 11
    return {11: '0', 10: 'K'}.get(resto, str(resto))


def rut_valido(texto):
    rut = normalizar_rut(texto)
    if len(rut) < 2 or not rut[:-1].isdigit():
        return False
    return _digito_verificador(rut[:-1]) == rut[-1]


def formatear_rut(texto):
    """'15482331K' -> '15.482.331-K'."""
    rut = normalizar_rut(texto)
    if len(rut) < 2:
        return rut
    cuerpo = f'{int(rut[:-1]):,}'.replace(',', '.') if rut[:-1].isdigit() else rut[:-1]
    return f'{cuerpo}-{rut[-1]}'
