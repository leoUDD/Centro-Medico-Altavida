from django.test import SimpleTestCase

from apps.seguridad.rut import formatear_rut, normalizar_rut, rut_valido


class RutTests(SimpleTestCase):
    def test_normaliza_y_formatea(self):
        self.assertEqual(normalizar_rut('15.482.331-k'), '15482331K')
        self.assertEqual(formatear_rut('15482331K'), '15.482.331-K')

    def test_valida_digito_verificador(self):
        self.assertTrue(rut_valido('12.345.678-5'))
        self.assertTrue(rut_valido('15.482.331-K'))
        self.assertFalse(rut_valido('12.345.678-9'))
        self.assertFalse(rut_valido('abc'))
        self.assertFalse(rut_valido(''))
