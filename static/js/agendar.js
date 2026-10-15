// Al cambiar especialidad, profesional, modalidad, examen, orden o sede, se recalculan los días y horas disponibles.
(function () {
  document.querySelectorAll('#agenda-form [data-auto]').forEach(function (campo) {
    campo.addEventListener('change', function () {
      campo.form.requestSubmit();
    });
  });
})();
