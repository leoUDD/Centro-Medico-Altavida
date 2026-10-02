from cryptography.exceptions import InvalidTag
from django.test import SimpleTestCase

from apps.seguridad.cifrado import cifrar, descifrar


class CifradoTests(SimpleTestCase):
    def test_se_recupera_el_texto_original(self):
        self.assertEqual(descifrar(cifrar('12.345.678-9')), '12.345.678-9')

    def test_el_texto_cifrado_no_contiene_el_original(self):
        self.assertNotIn('12.345.678-9', cifrar('12.345.678-9'))

    def test_mismo_texto_produce_resultados_distintos(self):
        self.assertNotEqual(cifrar('alergia a penicilina'), cifrar('alergia a penicilina'))

    def test_dato_alterado_es_rechazado(self):
        token = cifrar('dato')
        alterado = token[:-4] + ('AAAA' if token[-4:] != 'AAAA' else 'BBBB')
        with self.assertRaises(InvalidTag):
            descifrar(alterado)
