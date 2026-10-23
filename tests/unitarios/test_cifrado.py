import base64

from cryptography.exceptions import InvalidTag
from django.test import SimpleTestCase, override_settings

from apps.seguridad.cifrado import LlaveDesconocida, cifrar, descifrar, identificador_de
from apps.seguridad.indice import indice_correo, indice_rut

CTX = 'pacientes.paciente.sexo'


def llave_nueva(semilla):
    return base64.urlsafe_b64encode(bytes([semilla]) * 32).decode()


class CifradoTests(SimpleTestCase):
    def test_se_recupera_el_texto_original(self):
        self.assertEqual(descifrar(cifrar('12.345.678-9', CTX), CTX), '12.345.678-9')

    def test_el_texto_cifrado_no_contiene_el_original(self):
        self.assertNotIn('12.345.678-9', cifrar('12.345.678-9', CTX))

    def test_mismo_texto_produce_resultados_distintos(self):
        self.assertNotEqual(cifrar('alergia a penicilina', CTX), cifrar('alergia a penicilina', CTX))

    def test_dato_alterado_es_rechazado(self):
        token = cifrar('dato', CTX)
        alterado = token[:-4] + ('AAAA' if token[-4:] != 'AAAA' else 'BBBB')
        with self.assertRaises(InvalidTag):
            descifrar(alterado, CTX)

    def test_un_dato_copiado_a_otra_columna_no_se_puede_leer(self):
        token = cifrar('Penicilina', 'fichas_clinicas.historialmedico.alergias')
        with self.assertRaises(InvalidTag):
            descifrar(token, 'fichas_clinicas.historialmedico.enfermedades')

    def test_las_llaves_de_identidad_y_clinica_no_son_intercambiables(self):
        token = cifrar('15.482.331-K', 'pacientes.identidadpaciente.rut', proposito='identidad')
        with self.assertRaises((InvalidTag, LlaveDesconocida)):
            descifrar(token, 'pacientes.identidadpaciente.rut', proposito='clinica')

    def test_el_token_indica_con_que_llave_se_cifro(self):
        token = cifrar('dato', CTX)
        self.assertRegex(identificador_de(token), r'^[0-9a-f]{8}$')

    def test_rotacion_de_llave_los_datos_antiguos_siguen_legibles(self):
        from django.conf import settings
        token_viejo = cifrar('dato clínico', CTX)
        viejo = settings.LLAVES_CIFRADO['clinica']['actual']
        nuevas = {'clinica': {'actual': llave_nueva(7), 'anterior': viejo}, 'identidad': settings.LLAVES_CIFRADO['identidad']}
        with override_settings(LLAVES_CIFRADO=nuevas):
            self.assertEqual(descifrar(token_viejo, CTX), 'dato clínico')
            token_nuevo = cifrar('otro dato', CTX)
            self.assertNotEqual(identificador_de(token_nuevo), identificador_de(token_viejo))
        sin_anterior = {'clinica': {'actual': llave_nueva(7), 'anterior': ''}, 'identidad': settings.LLAVES_CIFRADO['identidad']}
        with override_settings(LLAVES_CIFRADO=sin_anterior), self.assertRaises(LlaveDesconocida):
            descifrar(token_viejo, CTX)


class IndiceCiegoTests(SimpleTestCase):
    def test_es_deterministico_y_normaliza(self):
        self.assertEqual(indice_rut('15.482.331-k'), indice_rut('15482331K'))
        self.assertEqual(indice_correo(' Ana@Correo.CL '), indice_correo('ana@correo.cl'))

    def test_no_revela_el_dato_y_los_dominios_son_independientes(self):
        self.assertNotIn('15482331', indice_rut('15482331K'))
        self.assertNotEqual(indice_rut('abc'), indice_correo('abc'))
