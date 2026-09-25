# Asignacion Estudiantes Service

Backend FastAPI para cargar parametría académica, persistirla en una base relacional y ejecutar la asignación de estudiantes a instituciones por periodo.

## Endpoints principales

- `POST /parametrias`: carga instituciones, restricciones, configuración, distribución de periodos, combinaciones y estudiantes.
- `GET /parametrias`: lista parametrías cargadas.
- `GET /parametrias/{parametria_id}`: consulta una parametría completa.
- `PUT /parametrias/{parametria_id}`: reemplaza una parametría completa y elimina sus resultados anteriores.
- `DELETE /parametrias/{parametria_id}`: elimina una parametría y sus resultados asociados.
- `POST /asignaciones/parametrias/{parametria_id}/ejecutar`: ejecuta el motor de asignación y guarda resultados.
- `GET /asignaciones/ejecuciones/{ejecucion_id}`: consulta resumen de una ejecución.
- `GET /asignaciones/ejecuciones/{ejecucion_id}/resultados`: consulta asignaciones por estudiante y periodo.
- `GET /catalogos/clinicas`: lista clínicas registradas.
- `GET /catalogos/estudiantes`: lista estudiantes registrados.

## Desarrollo local

```bash
poetry config virtualenvs.in-project true
poetry install
cp .env.example .env
make run-api
```

La base por defecto queda en `data/asignacion.db` usando SQLite.

## Ejemplo de carga

```json
{
  "nombre": "Escenario inicial",
  "instituciones": [
    {"institucion": "CLINICA DE TENJO", "especialidad": "MEDICINA FAMILIAR", "cantidad": 5}
  ],
  "restricciones": [
    {"estudiante": "352043", "institucion": "CLINICA DE TENJO", "especialidad": "MEDICINA FAMILIAR"}
  ],
  "asignacion": {
    "numero_periodos": 8,
    "estudiantes_aleatorio": true,
    "instituciones_aleatorio": true,
    "asignacion": "CONCENTRADA",
    "institucion_residual": "CLINICA UNIVERSIDAD DE LA SABANA"
  },
  "distribucion_periodos": [
    {"especialidad": "MEDICINA FAMILIAR", "asignacion": 1}
  ],
  "combinaciones": [],
  "estudiantes": [
    {"id": "352043", "nombre": "Nombrede_estudiante", "semestre": "6"}
  ]
}
```
