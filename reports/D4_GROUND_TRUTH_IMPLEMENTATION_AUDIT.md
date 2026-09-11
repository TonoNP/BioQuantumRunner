# BioQuantumRunner — D4 Ground Truth Addendum

## Auditoría final de implementación controlada

**Fecha:** 22 de agosto de 2026  
**Estado:** Implementación local para revisión; sin staging, commit ni push  
**Datos utilizados:** exclusivamente sintéticos

---

## 1. Resultado ejecutivo

La infraestructura contractual autorizada quedó implementada como una capa aditiva e independiente. SQLite funciona como autoridad transaccional inicial; Parquet materializa snapshots analíticos y JSON canónico conserva recibos de publicación.

No se seleccionaron unidades reales, no se etiquetaron sesiones reales, no se generó ground truth real, no se entrenaron modelos y no se ejecutó active learning.

La nueva suite obtiene **26/26 pruebas aprobadas**. La suite completa obtiene **66 aprobadas y 2 fallidas**. Las dos fallas corresponden exclusivamente al mismo cambio local preexistente en `notebooks/race_predictor_v2.ipynb`: su hash actual no coincide con el baseline D3 publicado. El archivo no fue modificado durante esta implementación y las pruebas existentes no fueron alteradas para ocultar la incidencia.

---

## 2. Archivos creados

### Código

- `src/ground_truth_addendum/__init__.py`
- `src/ground_truth_addendum/canonical.py`
- `src/ground_truth_addendum/compatibility.py`
- `src/ground_truth_addendum/contracts.py`
- `src/ground_truth_addendum/ids.py`
- `src/ground_truth_addendum/publication.py`
- `src/ground_truth_addendum/store.py`
- `scripts/build_ground_truth_addendum_synthetic.py`

### Pruebas y fixtures

- `tests/test_d4_ground_truth_addendum.py`
- `tests/fixtures/d4_frozen_manifest.json`
- `tests/fixtures/preimplementation_local_manifest.json`

### Auditoría

- `reports/D4_GROUND_TRUTH_IMPLEMENTATION_AUDIT.md`

## 3. Archivos modificados

Ningún archivo preexistente fue modificado por esta implementación.

Permanecen fuera del alcance los cambios locales preexistentes en:

- `app.py`;
- `notebooks/01_polar_mock_to_training_session.ipynb.ipynb`;
- `notebooks/race_predictor_v2.ipynb`;
- la implementación D4 y sus reportes locales previos.

---

## 4. Artefactos sintéticos generados

Directorio: `reports/d4_ground_truth_synthetic/`

- `ground_truth_synthetic.sqlite`;
- `validation_summary.json`;
- `publications/gold_core.parquet`;
- `publications/gold_core.receipt.json`;
- `publications/gold_extended.parquet`;
- `publications/gold_extended.receipt.json`;
- nueve snapshots Parquet, uno por tabla SQLite.

Los artefactos contienen:

- 3 sesiones sintéticas;
- 2 unidades de revisión sintéticas;
- 3 hilos de anotación sintéticos;
- 4 decisiones sintéticas;
- 2 publicaciones sintéticas;
- 0 sesiones reales;
- 0 unidades reales seleccionadas;
- 0 workout groups persistidos en el artefacto canónico sintético.

La operación de workout group se validó mediante fixture temporal de prueba y preservó `source_file` y `source_sha256`.

---

## 5. Esquema SQLite final

Se implementaron nueve tablas:

1. `ground_truth_source_sessions`;
2. `ground_truth_sampling_batches`;
3. `ground_truth_review_units`;
4. `ground_truth_review_unit_memberships`;
5. `ground_truth_annotation_threads`;
6. `ground_truth_session_decisions`;
7. `ground_truth_workout_groups`;
8. `ground_truth_group_memberships`;
9. `ground_truth_publications`.

`ground_truth_source_sessions` es una referencia técnica inmutable de identidad, no una copia modificable de `sessions_master`. En esta validación contiene únicamente identidades sintéticas.

### Relaciones principales

- batch → review units → review memberships → source session;
- annotation thread → decision revisions → source session;
- workout group decision → group memberships → source session;
- publication → manifests, cutoff, hashes, versión y recibo externo.

---

## 6. Constraints y mecanismo append-only

Se implementaron:

- claves primarias y foráneas;
- unicidad de IDs;
- unicidad `annotation_thread_id + revision`;
- validación de catálogos mediante `CHECK`;
- coherencia básica de timestamps;
- integridad runner–source_file–source_sha256;
- triggers que rechazan `UPDATE` y `DELETE` en tablas históricas;
- cadena `supersedes_*` inmediata y dentro del mismo hilo;
- rechazo de hilos cuyo target no coincide con la sesión o workout;
- bloqueo irreversible de batches;
- rechazo de nuevas membresías después del bloqueo;
- rollback transaccional ante cualquier fallo.

No se utiliza `INSERT OR REPLACE` ni actualización destructiva de decisiones.

---

## 7. Estrategia de identificadores

### UUIDv5

Se utiliza para identidades reproducibles:

- sampling batches;
- review units;
- revisiones de review units;
- membresías de review units.

La estrategia está versionada como `d4-gt-id-v1` y utiliza un namespace fijo. Sus entradas son semánticas y no contienen etiquetas deportivas mutables, fisiología, demografía ni resultados futuros.

### UUIDv4

Se utiliza para identidades de eventos:

- annotation threads;
- decisiones humanas;
- decisiones de workout groups;
- decisiones de membresía;
- publicaciones.

Los fixtures sintéticos proporcionan UUIDv4 fijos para permitir repetir exactamente el mismo escenario lógico de prueba.

---

## 8. Manifests, canonización y hashes

La canonización implementada utiliza:

- UTF-8;
- Unicode NFC;
- claves ordenadas;
- orden contractual de filas;
- timestamps UTC normalizados;
- nulos explícitos;
- JSON compacto y determinista;
- prefijo de dominio;
- SHA-256 lógico.

Se distinguen expresamente:

- hash lógico del contenido científico;
- hash binario del archivo Parquet.

Campos volátiles como rutas absolutas, mtime o nombre del host no forman parte del hash lógico.

### Hashes finales del fixture

- Schema manifest: `c5f9de048741737259ca44ebbd37d86c46f39d229bc101782c1b8f8f71ac007e`
- Population manifest: `8959a8a778bdc7f00f990870c72c7f8f96dab6d027111b0caa17d479a1ab1048`
- Gold Core: `f0e90ad1fe62902a079cff79b24d1adb08d7d3d2c65bc10e9824c424ed5cea66`
- Gold Extended: `93297965f23f1d7efc7edf41a07884574b4b75901c3c547d7cf0b8fc232526bf`

---

## 9. Temporalidad y vistas `as_of`

La API normaliza timestamps a UTC y mantiene separados:

- `evidence_observed_at`;
- `decision_timestamp`;
- `effective_from`;
- `label_available_at`;
- `knowledge_cutoff`.

Una vista `as_of` selecciona la última revisión elegible de cada hilo únicamente cuando `decision_timestamp` y `label_available_at` no superan el cutoff. Una corrección posterior no altera el resultado reconstruido antes de estar disponible.

Las opiniones independientes permanecen separadas y no son resueltas mediante una selección genérica de la última fila.

---

## 10. Gold Core y Gold Extended

- `gold_core` admite únicamente `verified` elegible;
- `gold_extended` admite `verified + reported`;
- `reported` permanece explícito por fila;
- `suspected` no ingresa automáticamente;
- conflictos semánticos entre hilos independientes se preservan y quedan fuera del producto gold hasta resolución autorizada;
- abstención e incertidumbre permanecen representadas por dimensión.

El adaptador hacia D4 acepta exclusivamente una decisión ya resuelta por sesión. Rechaza múltiples hilos para impedir que la compatibilidad reinterprete silenciosamente opiniones independientes.

---

## 11. Protección de `locked_test`

La política implementada es:

- 2019–2023: `development`;
- 2024: `validation`;
- 2025–2026: `locked_test`.

El guard automático rechaza `locked_test` para:

- training;
- calibration;
- feature selection;
- rule selection;
- threshold selection;
- active learning;
- architecture optimization.

Cada propósito cuenta con una prueba negativa. La inspección `technical_integrity` está permitida y diferenciada explícitamente.

---

## 12. Pruebas ejecutadas

### Nueva suite del Addendum

Resultado: **26 aprobadas, 0 fallidas**.

Incluye pruebas positivas y negativas de:

- esquema;
- append-only;
- unicidad;
- FK;
- `supersedes_*`;
- hilos independientes;
- UUIDv5 idempotente;
- manifests y orden físico;
- temporalidad `as_of`;
- evidencia futura;
- `gold_core`/`gold_extended`;
- conservación de `reported`;
- abstención;
- los siete usos prohibidos de `locked_test`;
- bloqueo irreversible de batches;
- identidad dentro de workout groups;
- aislamiento multi-runner;
- dos construcciones completas;
- ausencia de datos reales;
- inmutabilidad de D1–D4.

### Suite completa BioQuantumRunner

Resultado final: **66 aprobadas, 2 fallidas**.

Fallos:

1. `tests/test_d3_race_prediction.py::test_frozen_artifacts_match_d3_baseline`;
2. `tests/test_d4_session_classification.py::test_d1_d2_d3_frozen_paths_remain_unchanged`.

Ambos fallan exclusivamente porque el hash actual de `notebooks/race_predictor_v2.ipynb` es `2a15ea40204555a1d298a3ce4630ff23c72c6b5deddbb59682233bdf31a60022`, mientras el baseline D3 espera `22f9f6a6c2dbcba8ce7394dea34c22b0cb1c42f473dda1ffdc33a3f6bb0fc60e`.

El cambio era preexistente. No se modificó el notebook ni las pruebas afectadas.

---

## 13. Reproducibilidad

Se ejecutaron dos construcciones independientes completas. Coincidieron exactamente:

- schema manifest;
- population manifest;
- hash lógico de Gold Core;
- hash lógico de Gold Extended;
- hashes lógicos de las nueve tablas.

Los UUIDv4 sintéticos se fijaron como entradas del fixture; no se derivaron del contenido.

---

## 14. Inmutabilidad D1–D4

La prueba específica del Addendum compara:

- el manifest congelado D1–D3;
- el manifest D4 capturado antes de implementar;
- los hashes de `app.py` y notebooks con cambios preexistentes.

Resultado: **aprobado**. D1, D2, D3 y D4 no fueron modificados por esta implementación.

`git diff --name-only` continúa mostrando exclusivamente los tres archivos modificados previamente:

- `app.py`;
- `notebooks/01_polar_mock_to_training_session.ipynb.ipynb`;
- `notebooks/race_predictor_v2.ipynb`.

---

## 15. Limitaciones y decisiones pendientes

1. SQLite es un perfil de un solo escritor; PostgreSQL no fue implementado.
2. La política final de arbitraje y jerarquía de revisores sigue deliberadamente abierta.
3. No se han definido umbrales científicos para declarar validado el patrón oro.
4. No existe interfaz gráfica ni flujo de autenticación/autorización.
5. El fixture canónico no persiste un workout compuesto; esa ruta se valida en pruebas temporales.
6. La equivalencia entre motores futuros deberá probarse mediante hashes lógicos, timestamps y vistas `as_of`.
7. Ninguna conclusión sobre precisión clasificatoria puede obtenerse de estos datos sintéticos.

---

## 16. Desviaciones respecto del diseño aprobado

No se identificaron desviaciones científicas o arquitectónicas materiales.

La tabla técnica `ground_truth_source_sessions` materializa la referencia inmutable prevista por el diseño para aplicar FK y validar identidad sin modificar `sessions_master`. No constituye ground truth real ni altera D4.

---

## 17. Estado final

La infraestructura autorizada está implementada localmente y lista para revisión humana. No está autorizada todavía para seleccionar las aproximadamente 240 unidades, capturar etiquetas reales, ejecutar active learning, entrenar modelos, realizar staging, commit o push.

