from __future__ import annotations

import random
from dataclasses import dataclass, field

from asignacion_estudiantes_service.domain.models import Parametria
from asignacion_estudiantes_service.domain.schemas import limpiar_texto


class AssignmentError(ValueError):
    pass


@dataclass
class Scenario:
    clinica_id: int
    institucion: str
    especialidad: str
    capacidad: int
    utilizados: list[int]


@dataclass
class Distribution:
    especialidad: str
    cantidad: int


@dataclass
class Restriction:
    estudiante_id: str
    institucion: str
    especialidad: str | None


@dataclass
class Combination:
    especialidad_1: str
    especialidad_2: str
    longitud_bloque: int


@dataclass
class AssignmentRow:
    estudiante_id: str
    periodo: int
    especialidad: str
    clinica_id: int | None
    institucion: str
    pendiente: bool = False


@dataclass
class EngineResult:
    rows: list[AssignmentRow]
    total_estudiantes: int
    total_asignaciones: int
    total_pendientes: int


@dataclass
class StudentMatrix:
    especialidades: dict[tuple[str, int], str] = field(default_factory=dict)
    instituciones: dict[tuple[str, int], str] = field(default_factory=dict)
    clinicas: dict[tuple[str, int], int | None] = field(default_factory=dict)
    pendientes: dict[tuple[str, int], bool] = field(default_factory=dict)

    def get_especialidad(self, estudiante_id: str, periodo: int) -> str:
        return self.especialidades.get((estudiante_id, periodo), "")

    def set_assignment(
        self,
        estudiante_id: str,
        periodo: int,
        especialidad: str,
        scenario: Scenario | None,
    ) -> None:
        key = (estudiante_id, periodo)
        self.especialidades[key] = especialidad
        if scenario is None:
            self.instituciones[key] = "PENDIENTE"
            self.clinicas[key] = None
            self.pendientes[key] = True
            return
        self.instituciones[key] = scenario.institucion
        self.clinicas[key] = scenario.clinica_id
        self.pendientes[key] = False
        scenario.utilizados[periodo] += 1


def run_assignment(parametria: Parametria) -> EngineResult:
    total_periodos = parametria.numero_periodos
    scenarios = [
        Scenario(
            clinica_id=item.clinica_id,
            institucion=item.clinica.nombre,
            especialidad=item.especialidad,
            capacidad=item.cantidad,
            utilizados=[0] * (total_periodos + 1),
        )
        for item in parametria.instituciones
    ]
    distributions = [
        Distribution(especialidad=item.especialidad, cantidad=item.asignacion)
        for item in parametria.distribuciones
    ]
    restrictions = [
        Restriction(
            estudiante_id=item.estudiante_id,
            institucion=item.clinica.nombre,
            especialidad=item.especialidad,
        )
        for item in parametria.restricciones
    ]
    combinations = [
        Combination(
            especialidad_1=item.especialidad_1,
            especialidad_2=item.especialidad_2,
            longitud_bloque=item.longitud_bloque,
        )
        for item in parametria.combinaciones
    ]
    estudiantes = _order_students_by_restriction_priority(
        [item.estudiante_id for item in parametria.estudiantes],
        restrictions,
        parametria.estudiantes_aleatorio,
    )

    matrix = StudentMatrix()
    for estudiante_id in estudiantes:
        _apply_combinations(
            estudiante_id,
            scenarios,
            combinations,
            restrictions,
            matrix,
            total_periodos,
            parametria.estrategia,
            parametria.institucion_residual,
        )

    _complete_assignments(
        estudiantes,
        scenarios,
        distributions,
        restrictions,
        matrix,
        total_periodos,
        False,
        parametria.instituciones_aleatorio,
        parametria.estrategia,
        parametria.institucion_residual,
    )

    rows: list[AssignmentRow] = []
    pendientes = 0
    for estudiante_id in estudiantes:
        for periodo in range(1, total_periodos + 1):
            especialidad = matrix.especialidades.get((estudiante_id, periodo))
            institucion = matrix.instituciones.get((estudiante_id, periodo))
            if not especialidad or not institucion:
                raise AssignmentError(
                    f"El estudiante {estudiante_id} quedó sin asignación en periodo {periodo}"
                )
            pendiente = matrix.pendientes.get((estudiante_id, periodo), False)
            if pendiente:
                pendientes += 1
            rows.append(
                AssignmentRow(
                    estudiante_id=estudiante_id,
                    periodo=periodo,
                    especialidad=especialidad,
                    clinica_id=matrix.clinicas.get((estudiante_id, periodo)),
                    institucion=institucion,
                    pendiente=pendiente,
                )
            )

    return EngineResult(
        rows=rows,
        total_estudiantes=len(estudiantes),
        total_asignaciones=len(rows),
        total_pendientes=pendientes,
    )


def _order_students_by_restriction_priority(
    estudiantes: list[str], restrictions: list[Restriction], randomize_within_group: bool
) -> list[str]:
    specific = {
        restriction.estudiante_id for restriction in restrictions if restriction.especialidad
    }
    general = {
        restriction.estudiante_id
        for restriction in restrictions
        if not restriction.especialidad and restriction.estudiante_id not in specific
    }
    groups = [
        [estudiante_id for estudiante_id in estudiantes if estudiante_id in specific],
        [estudiante_id for estudiante_id in estudiantes if estudiante_id in general],
        [
            estudiante_id
            for estudiante_id in estudiantes
            if estudiante_id not in specific and estudiante_id not in general
        ],
    ]
    if randomize_within_group:
        for group in groups:
            random.shuffle(group)
    return [estudiante_id for group in groups for estudiante_id in group]


def _apply_combinations(
    estudiante_id: str,
    scenarios: list[Scenario],
    combinations: list[Combination],
    restrictions: list[Restriction],
    matrix: StudentMatrix,
    total_periodos: int,
    estrategia: str,
    institucion_residual: str,
) -> None:
    if not combinations:
        return

    plan, found = _find_global_block_plan(
        estudiante_id,
        combinations,
        scenarios,
        matrix,
        total_periodos,
        institucion_residual,
    )
    if not found:
        raise AssignmentError(
            f"No existe una distribución global de bloques consecutivos para {estudiante_id}"
        )

    for idx, item in enumerate(plan):
        inicio, fin, esp1, esp2 = item
        combination = combinations[idx]
        if combination.longitud_bloque == 4:
            _assign_x4(
                estudiante_id,
                inicio,
                esp1,
                scenarios,
                restrictions,
                matrix,
                estrategia,
                institucion_residual,
            )
        else:
            _assign_pair(
                estudiante_id,
                inicio,
                fin,
                esp1,
                esp2,
                scenarios,
                restrictions,
                matrix,
                estrategia,
                institucion_residual,
            )


def _find_global_block_plan(
    estudiante_id: str,
    combinations: list[Combination],
    scenarios: list[Scenario],
    matrix: StudentMatrix,
    total_periodos: int,
    institucion_residual: str,
) -> tuple[list[tuple[int, int, str, str]], bool]:
    best_score = float("-inf")
    best_plan: list[tuple[int, int, str, str]] = []

    def recurse(
        idx: int,
        occupied: set[int],
        current: list[tuple[int, int, str, str]],
        score: float,
    ) -> None:
        nonlocal best_score, best_plan
        if idx >= len(combinations):
            if score > best_score:
                best_score = score
                best_plan = list(current)
            return

        combo = combinations[idx]
        if combo.longitud_bloque == 4:
            for inicio in range(1, total_periodos - 2):
                periodos = set(range(inicio, inicio + 4))
                if periodos & occupied:
                    continue
                if not all(
                    _period_compatible(matrix, estudiante_id, periodo, combo.especialidad_1)
                    for periodo in periodos
                ):
                    continue
                local = sum(
                    _capacity_remaining(scenarios, combo.especialidad_1, periodo)
                    for periodo in periodos
                )
                if _common_institution_for_x4(scenarios, combo.especialidad_1, inicio):
                    local += 12000
                current.append((inicio, inicio + 3, combo.especialidad_1, combo.especialidad_1))
                recurse(idx + 1, occupied | periodos, current, score + local)
                current.pop()
            return

        candidates = [
            (combo.especialidad_1, combo.especialidad_2),
            (combo.especialidad_2, combo.especialidad_1),
        ]
        if limpiar_texto(combo.especialidad_1) == limpiar_texto(combo.especialidad_2):
            candidates = candidates[:1]

        for esp1, esp2 in candidates:
            for inicio in range(1, total_periodos):
                periodos = {inicio, inicio + 1}
                if periodos & occupied:
                    continue
                if not _period_compatible(matrix, estudiante_id, inicio, esp1):
                    continue
                if not _period_compatible(matrix, estudiante_id, inicio + 1, esp2):
                    continue
                local = _capacity_remaining(scenarios, esp1, inicio) * 10
                local += _capacity_remaining(scenarios, esp2, inicio + 1) * 10
                if _common_institution_available(scenarios, esp1, inicio, esp2, inicio + 1):
                    local += 20000
                if _residual_available(scenarios, esp1, inicio, institucion_residual):
                    local += 500
                current.append((inicio, inicio + 1, esp1, esp2))
                recurse(idx + 1, occupied | periodos, current, score + local)
                current.pop()

    recurse(0, set(), [], 0.0)
    return best_plan, bool(best_plan) or not combinations


def _assign_x4(
    estudiante_id: str,
    inicio: int,
    especialidad: str,
    scenarios: list[Scenario],
    restrictions: list[Restriction],
    matrix: StudentMatrix,
    estrategia: str,
    institucion_residual: str,
) -> None:
    restriction = _restriction_for_student(restrictions, estudiante_id, especialidad)
    if restriction is not None:
        for periodo in range(inicio, inicio + 4):
            scenario = _scenario_for_restriction(
                scenarios,
                especialidad,
                periodo,
                restriction,
                estrategia,
                institucion_residual,
            )
            matrix.set_assignment(estudiante_id, periodo, especialidad, scenario)
        return

    common = _select_common_x4(scenarios, especialidad, inicio, estrategia, institucion_residual)
    if common is not None:
        for periodo in range(inicio, inicio + 4):
            matrix.set_assignment(estudiante_id, periodo, especialidad, common)
        return

    for periodo in range(inicio, inicio + 4):
        scenario = _select_scenario(
            scenarios, especialidad, periodo, estrategia, institucion_residual
        )
        matrix.set_assignment(estudiante_id, periodo, especialidad, scenario)


def _assign_pair(
    estudiante_id: str,
    periodo_1: int,
    periodo_2: int,
    especialidad_1: str,
    especialidad_2: str,
    scenarios: list[Scenario],
    restrictions: list[Restriction],
    matrix: StudentMatrix,
    estrategia: str,
    institucion_residual: str,
) -> None:
    restriction_1 = _restriction_for_student(restrictions, estudiante_id, especialidad_1)
    restriction_2 = _restriction_for_student(restrictions, estudiante_id, especialidad_2)

    if restriction_1 is not None or restriction_2 is not None:
        scenario_1 = (
            _scenario_for_restriction(
                scenarios,
                especialidad_1,
                periodo_1,
                restriction_1,
                estrategia,
                institucion_residual,
            )
            if restriction_1 is not None
            else _select_scenario(
                scenarios, especialidad_1, periodo_1, estrategia, institucion_residual
            )
        )
        scenario_2 = (
            _scenario_for_restriction(
                scenarios,
                especialidad_2,
                periodo_2,
                restriction_2,
                estrategia,
                institucion_residual,
            )
            if restriction_2 is not None
            else _select_scenario(
                scenarios, especialidad_2, periodo_2, estrategia, institucion_residual
            )
        )
        matrix.set_assignment(estudiante_id, periodo_1, especialidad_1, scenario_1)
        matrix.set_assignment(estudiante_id, periodo_2, especialidad_2, scenario_2)
        return

    same_1, same_2 = _select_same_institution_pair(
        scenarios,
        especialidad_1,
        periodo_1,
        especialidad_2,
        periodo_2,
        estrategia,
        institucion_residual,
    )
    if same_1 is not None and same_2 is not None:
        matrix.set_assignment(estudiante_id, periodo_1, especialidad_1, same_1)
        matrix.set_assignment(estudiante_id, periodo_2, especialidad_2, same_2)
        return

    matrix.set_assignment(
        estudiante_id,
        periodo_1,
        especialidad_1,
        _select_scenario(scenarios, especialidad_1, periodo_1, estrategia, institucion_residual),
    )
    matrix.set_assignment(
        estudiante_id,
        periodo_2,
        especialidad_2,
        _select_scenario(scenarios, especialidad_2, periodo_2, estrategia, institucion_residual),
    )


def _complete_assignments(
    estudiantes: list[str],
    scenarios: list[Scenario],
    distributions: list[Distribution],
    restrictions: list[Restriction],
    matrix: StudentMatrix,
    total_periodos: int,
    random_students: bool,
    random_specialties: bool,
    estrategia: str,
    institucion_residual: str,
) -> None:
    order = list(estudiantes)
    if random_students:
        random.shuffle(order)

    for estudiante_id in order:
        pending_specialties: list[str] = []
        for distribution in distributions:
            assigned = sum(
                1
                for periodo in range(1, total_periodos + 1)
                if limpiar_texto(matrix.get_especialidad(estudiante_id, periodo))
                == limpiar_texto(distribution.especialidad)
            )
            pending_specialties.extend(
                [distribution.especialidad] * (distribution.cantidad - assigned)
            )

        if random_specialties:
            random.shuffle(pending_specialties)

        for specialty in pending_specialties:
            periodo = _best_period(scenarios, specialty, estudiante_id, matrix, total_periodos)
            if periodo == 0:
                periodo = _first_free_period(estudiante_id, matrix, total_periodos)
            if periodo == 0:
                raise AssignmentError(
                    f"No existe periodo libre para {specialty} de {estudiante_id}"
                )
            restriction = _restriction_for_student(restrictions, estudiante_id, specialty)
            scenario = (
                _scenario_for_restriction(
                    scenarios,
                    specialty,
                    periodo,
                    restriction,
                    estrategia,
                    institucion_residual,
                )
                if restriction is not None
                else _select_scenario(
                    scenarios, specialty, periodo, estrategia, institucion_residual
                )
            )
            matrix.set_assignment(estudiante_id, periodo, specialty, scenario)


def _period_compatible(
    matrix: StudentMatrix, estudiante_id: str, periodo: int, especialidad: str
) -> bool:
    current = matrix.get_especialidad(estudiante_id, periodo)
    return not current or limpiar_texto(current) == limpiar_texto(especialidad)


def _capacity_remaining(scenarios: list[Scenario], especialidad: str, periodo: int) -> int:
    return sum(
        max(0, scenario.capacidad - scenario.utilizados[periodo])
        for scenario in scenarios
        if limpiar_texto(scenario.especialidad) == limpiar_texto(especialidad)
    )


def _restriction_for_student(
    restrictions: list[Restriction], estudiante_id: str, especialidad: str
) -> Restriction | None:
    general: Restriction | None = None
    for restriction in restrictions:
        if restriction.estudiante_id != estudiante_id:
            continue
        if not restriction.especialidad:
            general = restriction
        elif limpiar_texto(restriction.especialidad) == limpiar_texto(especialidad):
            return restriction
    return general


def _provider_unique(scenarios: list[Scenario], especialidad: str) -> str:
    institutions = {
        limpiar_texto(scenario.institucion)
        for scenario in scenarios
        if limpiar_texto(scenario.especialidad) == limpiar_texto(especialidad)
    }
    return next(iter(institutions)) if len(institutions) == 1 else ""


def _find_scenario(
    scenarios: list[Scenario], institucion: str, especialidad: str, periodo: int
) -> Scenario | None:
    for scenario in scenarios:
        if limpiar_texto(scenario.institucion) != limpiar_texto(institucion):
            continue
        if limpiar_texto(scenario.especialidad) != limpiar_texto(especialidad):
            continue
        if scenario.utilizados[periodo] < scenario.capacidad:
            return scenario
    return None


def _scenario_for_restriction(
    scenarios: list[Scenario],
    especialidad: str,
    periodo: int,
    restriction: Restriction,
    estrategia: str,
    institucion_residual: str,
) -> Scenario | None:
    scenario = _find_scenario(scenarios, restriction.institucion, especialidad, periodo)
    if scenario is not None:
        return scenario

    if restriction.especialidad:
        return None

    return _select_scenario(scenarios, especialidad, periodo, estrategia, institucion_residual)


def _is_residual(institucion: str, institucion_residual: str) -> bool:
    return limpiar_texto(institucion_residual) in limpiar_texto(institucion)


def _select_residual(
    scenarios: list[Scenario], especialidad: str, periodo: int, institucion_residual: str
) -> Scenario | None:
    candidates = [
        scenario
        for scenario in scenarios
        if limpiar_texto(scenario.especialidad) == limpiar_texto(especialidad)
        and _is_residual(scenario.institucion, institucion_residual)
        and scenario.utilizados[periodo] < scenario.capacidad
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.capacidad - item.utilizados[periodo])


def _select_scenario(
    scenarios: list[Scenario],
    especialidad: str,
    periodo: int,
    estrategia: str,
    institucion_residual: str,
) -> Scenario | None:
    candidates = [
        scenario
        for scenario in scenarios
        if limpiar_texto(scenario.especialidad) == limpiar_texto(especialidad)
        and scenario.utilizados[periodo] < scenario.capacidad
    ]
    if not candidates:
        return None

    if limpiar_texto(estrategia) == "CONCENTRADA":
        normal = [
            item for item in candidates if not _is_residual(item.institucion, institucion_residual)
        ]
        if normal:
            return normal[0]
        return candidates[0]

    return min(
        candidates,
        key=lambda item: item.utilizados[periodo] / item.capacidad if item.capacidad else 1,
    )


def _common_institution_available(
    scenarios: list[Scenario], esp1: str, p1: int, esp2: str, p2: int
) -> bool:
    left = [
        scenario
        for scenario in scenarios
        if limpiar_texto(scenario.especialidad) == limpiar_texto(esp1)
        and scenario.utilizados[p1] < scenario.capacidad
    ]
    right = [
        scenario
        for scenario in scenarios
        if limpiar_texto(scenario.especialidad) == limpiar_texto(esp2)
        and scenario.utilizados[p2] < scenario.capacidad
    ]
    right_names = {limpiar_texto(item.institucion) for item in right}
    return any(limpiar_texto(item.institucion) in right_names for item in left)


def _common_institution_for_x4(scenarios: list[Scenario], especialidad: str, inicio: int) -> bool:
    return _select_common_x4(scenarios, especialidad, inicio, "BALANCEADA", "") is not None


def _select_common_x4(
    scenarios: list[Scenario],
    especialidad: str,
    inicio: int,
    estrategia: str,
    institucion_residual: str,
) -> Scenario | None:
    candidates = [
        scenario
        for scenario in scenarios
        if limpiar_texto(scenario.especialidad) == limpiar_texto(especialidad)
        and all(scenario.utilizados[p] < scenario.capacidad for p in range(inicio, inicio + 4))
    ]
    if not candidates:
        return None
    if limpiar_texto(estrategia) == "CONCENTRADA":
        normal = [
            item for item in candidates if not _is_residual(item.institucion, institucion_residual)
        ]
        if normal:
            return normal[0]
        return candidates[0]
    return min(
        candidates,
        key=lambda item: (
            sum(item.utilizados[p] / item.capacidad for p in range(inicio, inicio + 4)) / 4
            if item.capacidad
            else 1
        ),
    )


def _select_same_institution_pair(
    scenarios: list[Scenario],
    esp1: str,
    p1: int,
    esp2: str,
    p2: int,
    estrategia: str,
    institucion_residual: str,
) -> tuple[Scenario | None, Scenario | None]:
    best: tuple[Scenario | None, Scenario | None] = (None, None)
    best_score = float("-inf")
    for left in scenarios:
        if (
            limpiar_texto(left.especialidad) != limpiar_texto(esp1)
            or left.utilizados[p1] >= left.capacidad
        ):
            continue
        for right in scenarios:
            if limpiar_texto(right.institucion) != limpiar_texto(left.institucion):
                continue
            if (
                limpiar_texto(right.especialidad) != limpiar_texto(esp2)
                or right.utilizados[p2] >= right.capacidad
            ):
                continue
            o1 = left.utilizados[p1] / left.capacidad if left.capacidad else 1
            o2 = right.utilizados[p2] / right.capacidad if right.capacidad else 1
            score = -((o1 + o2) / 2)
            if limpiar_texto(estrategia) == "CONCENTRADA":
                score = (o1 + o2) / 2
                score += -1000 if _is_residual(left.institucion, institucion_residual) else 1000
            if score > best_score:
                best_score = score
                best = (left, right)
    return best


def _residual_available(
    scenarios: list[Scenario], especialidad: str, periodo: int, institucion_residual: str
) -> bool:
    return _select_residual(scenarios, especialidad, periodo, institucion_residual) is not None


def _best_period(
    scenarios: list[Scenario],
    especialidad: str,
    estudiante_id: str,
    matrix: StudentMatrix,
    total_periodos: int,
) -> int:
    best_capacity = -1
    candidates: list[int] = []
    for periodo in range(1, total_periodos + 1):
        if matrix.get_especialidad(estudiante_id, periodo):
            continue
        capacity = _capacity_remaining(scenarios, especialidad, periodo)
        if capacity <= 0:
            continue
        if capacity > best_capacity:
            best_capacity = capacity
            candidates = [periodo]
        elif capacity == best_capacity:
            candidates.append(periodo)
    return random.choice(candidates) if candidates else 0


def _first_free_period(estudiante_id: str, matrix: StudentMatrix, total_periodos: int) -> int:
    for periodo in range(1, total_periodos + 1):
        if not matrix.get_especialidad(estudiante_id, periodo):
            return periodo
    return 0
