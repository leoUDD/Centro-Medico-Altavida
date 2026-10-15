from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.fichas_clinicas.models import AccesoFicha, Diagnostico, HistorialMedico
from apps.pacientes.models import Paciente
from apps.recetas.alergias import en_conflicto, palabras_en_alerta
from apps.recetas.models import Receta
from apps.usuarios.models import Usuario

CLAVE = 'Clave-Muy-Segura-123'


class AlergiasTests(SimpleTestCase):
    def test_familia_penicilina(self):
        palabras = palabras_en_alerta('Alergia a la Penicilina')
        self.assertTrue(en_conflicto('Amoxicilina 500 mg', palabras))
        self.assertFalse(en_conflicto('Atorvastatina 20 mg', palabras))

    def test_sin_alergias_conocidas(self):
        self.assertEqual(palabras_en_alerta('Ninguna conocida'), [])
        self.assertEqual(palabras_en_alerta(''), [])

    def test_ibuprofeno_no_se_confunde_con_otras_palabras(self):
        palabras = palabras_en_alerta('AINE')
        self.assertTrue(en_conflicto('Ibuprofeno 400 mg', palabras))
        self.assertFalse(en_conflicto('Cafeína 100 mg', palabras))


def _datos(medicamento='Atorvastatina 20 mg', **extra):
    datos = {
        'items-TOTAL_FORMS': '1', 'items-INITIAL_FORMS': '0', 'items-MIN_NUM_FORMS': '1', 'items-MAX_NUM_FORMS': '20',
        'items-0-medicamento': medicamento, 'items-0-dosis': '1 comprimido', 'items-0-frecuencia': 'Cada noche',
        'items-0-duracion': '90 días', 'items-0-via': 'Oral', 'indicaciones': 'Control en 3 meses',
    }
    datos.update(extra)
    return datos


class RecetasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.medico = Usuario.objects.create_user('med', email='med@c.cl', password=CLAVE, rol=Usuario.Rol.MEDICO)
        cls.otro = Usuario.objects.create_user('otro', email='otro@c.cl', password=CLAVE, rol=Usuario.Rol.MEDICO)
        cls.paciente = Paciente.objects.create(
            rut='15482331K', nombres='María José', apellidos='Fuentes Soto', fecha_nacimiento='1985-03-12',
        )
        HistorialMedico.objects.create(paciente=cls.paciente, alergias='Penicilina')
        cls.dx = Diagnostico.objects.create(
            paciente=cls.paciente, medico=cls.medico, codigo_cie10='E78.5', diagnostico='Hiperlipidemia',
        )

    def setUp(self):
        self.client.force_login(self.medico)
        self.url_nueva = reverse('recetas:nueva', args=[self.paciente.pk])

    def test_formulario_muestra_alerta_de_alergia(self):
        r = self.client.get(self.url_nueva)
        self.assertContains(r, 'Alergia registrada: Penicilina')
        self.assertContains(r, 'E78.5 · Hiperlipidemia')

    def test_guardar_borrador_no_pide_clave(self):
        r = self.client.post(self.url_nueva, _datos(diagnostico=self.dx.pk, accion='borrador'))
        receta = Receta.objects.get()
        self.assertRedirects(r, reverse('recetas:editar', args=[receta.pk]), fetch_redirect_response=False)
        self.assertEqual(receta.estado, 'BORRADOR')
        self.assertEqual(receta.items.get().medicamento, 'Atorvastatina 20 mg')

    def test_emitir_con_clave_firma_la_receta(self):
        r = self.client.post(self.url_nueva, _datos(diagnostico=self.dx.pk, accion='emitir', clave=CLAVE))
        receta = Receta.objects.get()
        self.assertRedirects(r, reverse('recetas:detalle', args=[receta.pk]), fetch_redirect_response=False)
        self.assertTrue(receta.emitida)
        self.assertTrue(receta.firma_valida)
        self.assertTrue(AccesoFicha.objects.filter(accion='RECETA', paciente=self.paciente).exists())
        # Alterar el contenido invalida la firma.
        item = receta.items.get()
        item.dosis = '10 comprimidos'
        item.save()
        self.assertFalse(Receta.objects.get().firma_valida)

    def test_emitir_con_clave_incorrecta(self):
        r = self.client.post(self.url_nueva, _datos(diagnostico=self.dx.pk, accion='emitir', clave='mala'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'La contraseña no es correcta')
        self.assertFalse(Receta.objects.exists())

    def test_medicamento_en_conflicto_exige_confirmacion(self):
        datos = _datos('Amoxicilina 500 mg', diagnostico=self.dx.pk, accion='emitir', clave=CLAVE)
        r = self.client.post(self.url_nueva, datos)
        self.assertContains(r, 'alérgico')
        self.assertFalse(Receta.objects.exists())
        r = self.client.post(self.url_nueva, {**datos, 'confirmo_alergia': 'on'})
        self.assertTrue(Receta.objects.get().emitida)

    def test_exige_diagnostico_y_un_medicamento(self):
        r = self.client.post(self.url_nueva, _datos(accion='borrador'))
        self.assertIn('diagnostico', r.context['form'].errors)
        vacio = {k: v for k, v in _datos(diagnostico=self.dx.pk, accion='borrador').items() if not k.startswith('items-0')}
        r = self.client.post(self.url_nueva, vacio)
        self.assertFalse(Receta.objects.exists())

    def test_editar_borrador_y_emitida_es_inmutable(self):
        self.client.post(self.url_nueva, _datos(diagnostico=self.dx.pk, accion='borrador'))
        receta = Receta.objects.get()
        url = reverse('recetas:editar', args=[receta.pk])
        self.assertContains(self.client.get(url), 'Atorvastatina 20 mg')
        datos = _datos('Metformina 850 mg', diagnostico=self.dx.pk, accion='emitir', clave=CLAVE)
        datos.update({'items-INITIAL_FORMS': '1'})
        self.client.post(url, datos)
        receta.refresh_from_db()
        self.assertTrue(receta.emitida)
        self.assertEqual(receta.items.get().medicamento, 'Metformina 850 mg')
        self.assertRedirects(self.client.get(url), reverse('recetas:detalle', args=[receta.pk]), fetch_redirect_response=False)

    def test_otro_medico_no_edita_borrador_ajeno(self):
        self.client.post(self.url_nueva, _datos(diagnostico=self.dx.pk, accion='borrador'))
        receta = Receta.objects.get()
        self.client.force_login(self.otro)
        r = self.client.get(reverse('recetas:editar', args=[receta.pk]))
        self.assertRedirects(r, reverse('recetas:detalle', args=[receta.pk]), fetch_redirect_response=False)

    def test_pacientes_no_acceden(self):
        pac = Usuario.objects.create_user('pac', email='pac@c.cl', password=CLAVE)
        self.client.force_login(pac)
        self.assertEqual(self.client.get(self.url_nueva).status_code, 403)
        self.assertEqual(self.client.post(self.url_nueva, _datos()).status_code, 403)
