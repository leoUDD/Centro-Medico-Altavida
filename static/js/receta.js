// Formulario de receta: agregar/quitar medicamentos, alerta de alergia y vista previa en vivo.
(function () {
  const app = document.getElementById('receta-app');
  if (!app) return;
  const contenedor = document.getElementById('items');
  const plantilla = document.getElementById('item-vacio');
  const total = app.querySelector('input[name="items-TOTAL_FORMS"]');
  const palabras = JSON.parse(document.getElementById('palabras-alerta').textContent || '[]');

  const plano = (t) => (t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const enConflicto = (t) => palabras.some((p) => new RegExp('(?<![a-z0-9])' + p).test(plano(t)));
  const campo = (fila, nombre) => fila.querySelector('[name$="-' + nombre + '"]');
  const filas = () => Array.from(contenedor.querySelectorAll('[data-item]')).filter((f) => !f.hidden);

  function celda(texto, negrita) {
    const d = document.createElement('div');
    if (negrita) {
      const s = document.createElement('strong');
      s.textContent = negrita;
      d.appendChild(s);
      d.appendChild(document.createElement('br'));
    }
    d.appendChild(document.createTextNode(texto));
    return d;
  }

  function actualizar() {
    filas().forEach((fila, i) => {
      fila.querySelector('[data-numero]').textContent = 'Medicamento ' + (i + 1);
      fila.querySelector('[data-quitar]').setAttribute('aria-label', 'Quitar medicamento ' + (i + 1));
      fila.querySelector('[data-alerta-alergia]').hidden = !enConflicto(campo(fila, 'medicamento').value);
    });
    const lista = document.getElementById('vp-items');
    lista.textContent = '';
    filas().forEach((fila, i) => {
      const v = (n) => campo(fila, n).value.trim();
      if (!v('medicamento')) return;
      const detalle = [v('dosis'), v('frecuencia'), 'vía ' + campo(fila, 'via').value.toLowerCase(), v('duracion') && 'por ' + v('duracion')]
        .filter(Boolean).join(', ');
      lista.appendChild(celda(detalle + '.', (i + 1) + '. ' + v('medicamento')));
    });
    const diag = app.querySelector('[name="diagnostico"]');
    const opcion = diag.options[diag.selectedIndex];
    document.getElementById('vp-diag').textContent = diag.value ? opcion.text.split(' · ')[0] : '—';
    document.getElementById('vp-ind').textContent = app.querySelector('[name="indicaciones"]').value;
  }

  document.getElementById('agregar').addEventListener('click', () => {
    const n = parseInt(total.value, 10);
    const html = plantilla.innerHTML.replace(/__prefix__/g, n).replace(/__n__/g, n + 1);
    contenedor.insertAdjacentHTML('beforeend', html);
    total.value = n + 1;
    const nueva = contenedor.lastElementChild;
    const via = campo(nueva, 'via');
    if (via && !via.value) via.selectedIndex = 0;
    actualizar();
    campo(nueva, 'medicamento').focus();
  });

  contenedor.addEventListener('click', (e) => {
    const boton = e.target.closest('[data-quitar]');
    if (!boton) return;
    const fila = boton.closest('[data-item]');
    if (filas().length === 1) return; // siempre debe quedar al menos un medicamento
    fila.querySelector('input[name$="-DELETE"]').checked = true;
    fila.hidden = true;
    actualizar();
  });

  app.addEventListener('input', actualizar);
  app.addEventListener('change', actualizar);
  actualizar();
})();
