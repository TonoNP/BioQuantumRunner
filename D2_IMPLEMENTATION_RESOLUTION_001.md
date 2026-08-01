# D2-IMP-001 — Precisión del baseline histórico

**Estado:** Aprobada  
**Fase:** D2  
**Decisión:** Alternativa B — compatibilidad numérica histórica únicamente durante la validación

## Contexto

La precisión íntegra de `sessions_master.parquet` desplaza algunas sesiones situadas cerca de los umbrales analíticos históricos. Esto impide separar directamente los cambios causados por la migración técnica de los causados por la precisión canónica.

## Resolución

El escenario histórico de validación aplicará temporalmente las reglas de precisión utilizadas por `sessions.csv`:

- `distance_km` redondeada a dos decimales;
- `duration_s` redondeada a segundos enteros;
- `pace_sec_per_km` y las métricas de eficiencia recalculadas desde esos dos valores.

Estas reglas se aplicarán exclusivamente al baseline histórico de validación, limitado al periodo que finaliza el 2025-10-19.

## Restricciones

- El pipeline productivo D2 utilizará siempre la precisión íntegra de `sessions_master.parquet`.
- La vista canónica y el baseline canónico completo no aplicarán redondeos heredados.
- No se modificarán `sessions_master`, los artefactos de D1, `sessions.csv` ni los archivos fuente Polar.
- Los valores históricos precalculados no se reutilizarán como fuente analítica.

## Finalidad de la validación

La comparación deberá distinguir explícitamente:

1. diferencias producidas por la migración del pipeline;
2. diferencias producidas por la mayor precisión de los datos canónicos;
3. diferencias producidas por la ampliación temporal del dataset.

## Poblaciones históricas de referencia

- modelo HR/ritmo: 550 sesiones;
- análisis semanal: 1,025 sesiones;
- mejor forma de 10 km o más: 571 sesiones;
- tiradas largas de 16 km o más: 128 sesiones.
