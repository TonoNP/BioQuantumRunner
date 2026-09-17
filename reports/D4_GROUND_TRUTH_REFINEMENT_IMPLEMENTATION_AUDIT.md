# Auditoría de implementación del refinamiento D4 Ground Truth

Fecha: 2026-09-16
Estado: implementación controlada, sin staging, commit ni push

## 1. Estado inicial observado

- `HEAD`: `ac0374f5db9d042ab19220fb665bfb5bc9849e99`.
- El staging estaba vacío.
- Existían cambios locales preexistentes en `app.py`, `notebooks/01_polar_mock_to_training_session.ipynb.ipynb` y `notebooks/race_predictor_v2.ipynb`, además de archivos no versionados ajenos a esta implementación.
- La infraestructura D4 Ground Truth v1 ya era append-only, multi-runner, temporalmente consultable, reproducible y protegía `locked_test`.

## 2. Requisitos ya satisfechos sin cambios

- Identidad permanente de runner y source session.
- Separación entre sesión registrada y workout group.
- Revisiones y cadenas `supersedes`.
- Consultas as-of de decisiones v1.
- Gold Core y Gold Extended separados.
- Preservación de abstención por dimensión en v1.
- UUID deterministas para objetos reproducibles y UUID de evento para decisiones humanas.
- Hashes lógicos separados de hashes binarios.
- Manifests y receipts reproducibles.
- Prohibición de `locked_test` para entrenamiento, calibración, selección, active learning y optimización arquitectónica.

## 3. Brechas reales encontradas

1. Una decisión v1 compartía procedencia entre varias dimensiones.
2. Gold v1 comparaba filas multidimensionales completas y no distinguía complementariedad de contradicción por dimensión.
3. Las memberships v1 no conservaban procedencia y temporalidad completas.
4. `evidence_type` no estaba validado mediante un catálogo materializado.
5. No existía una representación explícita de `missing_annotation` distinta de un claim `unknown`.
6. No había una migración aditiva que reconociera la granularidad insuficiente de procedencia histórica.

## 4. Cambios implementados

### Archivos modificados

- `src/ground_truth_addendum/contracts.py`: añade versiones v2, dimensiones, clases epistemológicas, estados de membership y reason codes sin alterar constantes v1.
- `src/ground_truth_addendum/store.py`: añade tablas, constraints, triggers, APIs as-of y composición Gold v2, preservando las tablas v1.
- `tests/test_d4_ground_truth_addendum.py`: amplía exclusivamente la expectativa del esquema aditivo.

### Archivos creados

- `src/ground_truth_addendum/refinement.py`: invariantes estado/valor y composición Gold determinista por dimensión.
- `src/ground_truth_addendum/migration_v1_to_v2.py`: proyección aditiva, idempotente y reproducible de decisiones v1 a claims v2.
- `tests/test_d4_ground_truth_refinement.py`: pruebas sintéticas del refinamiento.
- `reports/D4_GROUND_TRUTH_REFINEMENT_IMPLEMENTATION_AUDIT.md`: presente auditoría.

## 5. Justificación científica

- `semantic_claim` es la unidad mínima: una dimensión no puede apropiarse del nivel de evidencia de otra.
- `claim_kind` distingue observación instrumental, reporte humano, interpretación del fabricante e inferencia analítica.
- El catálogo versionado diferencia, entre otras fuentes, registro humano contemporáneo y reporte retrospectivo sin importar datos privados.
- `evidence_records` y vínculos de evidencia conservan procedencia y permiten soporte, contradicción, contexto o mera procedencia.
- Gold se compone por sujeto y dimensión. Claims complementarios coexisten; contradicciones generan `CONFLICT_UNRESOLVED` y nunca consenso artificial.
- La ausencia de claim continúa significando `missing_annotation`; un claim `unknown` es una decisión explícita distinta.
- Las memberships v2 son decisiones append-only con autor, razón, incertidumbre, clase epistemológica, evidencia y cuatro tiempos.
- La migración v1 no inventa atomicidad histórica: utiliza `legacy_unclassified` y `legacy_decision_wide`.

## 6. Pruebas ejecutadas

### Validación de sintaxis

`python -m compileall` sobre código y pruebas D4 Ground Truth: aprobada.

### Smoke test funcional

Validó inicialización de esquema, claims atómicos, Gold Core/Extended, append-only y bloqueo de `locked_test`: `REFINEMENT_SMOKE_OK`.

### Pruebas específicas

Comando:

`python -m pytest tests/test_d4_ground_truth_refinement.py tests/test_d4_ground_truth_addendum.py -q`

Resultado: **53 passed**.

### Regresión global

Comando:

`python -m pytest -q`

Resultado: **93 passed, 2 failed**.

Las dos fallas son preexistentes y corresponden exclusivamente al hash local de `notebooks/race_predictor_v2.ipynb` frente al baseline D3:

- `tests/test_d3_race_prediction.py::test_frozen_artifacts_match_d3_baseline`
- `tests/test_d4_session_classification.py::test_d1_d2_d3_frozen_paths_remain_unchanged`

No se actualizó ningún baseline ni hash para ocultarlas.

### Reproducibilidad sintética

Dos construcciones independientes confirmaron igualdad de:

- schema manifest;
- population manifest;
- Gold Core logical hash;
- Gold Extended logical hash.

Ambas registraron cero sesiones reales y cero unidades reales seleccionadas.

## 7. Integridad y restricciones

- D1, D2 y D3 no fueron modificadas por esta implementación.
- La arquitectura D4 v1 permanece disponible y sus tablas históricas no se reescriben.
- `locked_test` conserva todas sus prohibiciones.
- No se escribió Ground Truth real.
- No se creó el workout real del 2025-10-01.
- No se seleccionaron unidades reales.
- No se importó ni digitalizó ningún diario humano.
- No se entrenó ningún modelo.
- No se ejecutó active learning real.
- No se modificaron `app.py` ni notebooks.
- No hubo staging, commit ni push.

## 8. Riesgos y cuestiones abiertas

- La gobernanza final de adjudicación entre múltiples revisores sigue pendiente.
- `component_role` conserva deliberadamente su vocabulario limitado.
- No se implementó un producto Gold específico a nivel workout.
- Los claims migrados desde v1 conservan evidencia decision-wide; esa limitación histórica no puede resolverse sin evidencia adicional.
- El entorno Conda `bioquantum` no contiene `pytest`; las pruebas se ejecutaron con el Python base existente que sí lo incluye, sin instalar ni modificar paquetes.

## 9. Dictamen

La implementación es aditiva, reproducible y científicamente conservadora. Representa conocimiento, ausencia de anotación, incertidumbre, abstención y conflicto sin fusionar sesiones ni fabricar consenso. Queda lista para revisión humana previa a cualquier staging o uso con Ground Truth real.

**D4_GROUND_TRUTH_REFINEMENT_READY_FOR_REVIEW**
