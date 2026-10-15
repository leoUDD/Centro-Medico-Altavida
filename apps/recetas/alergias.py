import re
import unicodedata

# Familias de medicamentos que el sistema reconoce a partir del texto libre de "Alergias" de la ficha.
# No reemplaza el criterio médico: es solo una alerta.
FAMILIAS = {
    'penicilina': ['penicilina', 'amoxicilina', 'ampicilina', 'cloxacilina', 'dicloxacilina', 'flucloxacilina',
                   'piperacilina', 'oxacilina'],
    'sulfa': ['sulfa', 'sulfametoxazol', 'cotrimoxazol', 'trimetoprima'],
    'aspirina': ['aspirina', 'acido acetilsalicilico', 'acetilsalicilico'],
    'aine': ['aine', 'antiinflamatorio', 'ibuprofeno', 'naproxeno', 'diclofenaco', 'ketoprofeno', 'ketorolaco'],
    'cefalosporina': ['cefalosporina', 'cefalexina', 'cefuroxima', 'ceftriaxona', 'cefadroxilo'],
    'macrolido': ['macrolido', 'azitromicina', 'claritromicina', 'eritromicina'],
    'quinolona': ['quinolona', 'ciprofloxacino', 'levofloxacino', 'norfloxacino'],
}


def _plano(texto):
    return unicodedata.normalize('NFD', (texto or '').casefold()).encode('ascii', 'ignore').decode()


def _menciona(plano, palabra):
    # Inicio de palabra (sin usar el escape de borde de palabra): "aine" no coincide dentro de otra palabra.
    return re.search('(?<![a-z0-9])' + re.escape(palabra), plano) is not None


def palabras_en_alerta(alergias):
    """Palabras clave de las familias que aparecen mencionadas en las alergias del paciente."""
    plano = _plano(alergias)
    palabras = set()
    for familia, miembros in FAMILIAS.items():
        if _menciona(plano, familia) or any(_menciona(plano, m) for m in miembros):
            palabras.update(miembros)
    return sorted(palabras)


def en_conflicto(medicamento, palabras):
    plano = _plano(medicamento)
    return any(_menciona(plano, p) for p in palabras)
