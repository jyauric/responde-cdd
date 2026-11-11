"""Catálogo de compromisos e indicadores CdD 2026.

Fuente: RM 057-2026-MINEDU, Anexo N° 4 (pp. 145-146 de la norma; pp. 149-150 del PDF).
Revisado por la founder el 10/11/2026. Se usa para reconstruir las tablas de los
Anexos 3, 4 y 5 en el Markdown y como lista de temáticas del clasificador.
"""

COMPROMISOS = {
    1: "Incorporación y gestión oportuna del personal de las instituciones educativas",
    2: "Recuperación del aprendizaje de los estudiantes",
    3: "Distribución oportuna y uso del material educativo",
    4: "Condiciones operativas adecuadas de las instituciones educativas",
    5: "Cierre de la brecha de infraestructura educativa",
    6: "Fortalecimiento del bienestar de los estudiantes",
    7: "Soporte pedagógico al docente",
    8: "Incorporación oportuna del personal para la Educación Superior No Universitaria",
    9: "Fortalecimiento de la Educación Superior No Universitaria",
    10: "Registro oportuno de la matrícula de Educación Superior No Universitaria",
}

INDICADORES = {
    "1.1": "Porcentaje de plazas docentes y auxiliares de Educación Básica y docentes de Educación Técnico – Productiva, contratadas adecuada y oportunamente",
    "1.2": "Porcentaje de profesionales psicólogos contratados oportunamente en las IIEE JEC",
    "1.3": "Porcentaje de plazas del cargo de profesor de EBR que han sido reubicadas oportunamente, en el marco del proceso de racionalización 2025",
    "2.1": "Porcentaje de IIEE del nivel primaria y secundaria que implementan acciones en el marco de la estrategia de Refuerzo Escolar",
    "3.1": "Porcentaje de códigos modulares que recibieron el material educativo oportuna y pertinentemente",
    "3.2": "Porcentaje de códigos modulares que recibieron los materiales educativos que les corresponde recibir, de manera suficiente",
    "3.3": "Porcentaje de IIEE públicas de gestión directa que utilizan los textos de matemática y comunicación en las sesiones de aprendizaje para el nivel de secundaria",
    "4.1": "Porcentaje de locales educativos con declaración de gastos de mantenimiento verificada oportunamente",
    "5.1": "Porcentaje de predios destinados a IIEE que cuentan con inscripción registral de algún derecho a nombre del MINEDU",
    "6.1": "Porcentaje de casos de presunta violencia sexual reportados en el SíseVe que cuentan con medidas preventivas conforme a la Ley N.º 29988 y que son registrados adecuadamente en el SIMEX.",
    "6.2": "Porcentaje de IIEE públicas que realizan una actividad de sensibilización y participan en asistencia técnica sobre educación inclusiva",
    "6.3": "Porcentaje de estudiantes matriculados en los servicios EBE que cuentan con Informe Psicopedagógico y Plan Educativo Personalizado de manera oportuna",
    "7.1": "Porcentaje de IIEE de Primaria Multigrado de ámbito rural cuyos docentes reciben visitas de asistencia técnica presencial",
    "7.2": "Porcentaje de IIEE públicas polidocentes completas del nivel de educación primaria que reciben asistencia técnica sobre el desarrollo de las competencias de Matemática y Comunicación en el III y/o IV ciclo",
    "7.3": "Porcentaje de Servicios Educativos EIB cuyos docentes reciben visita al aula y asistencia técnica presencial sobre la implementación del MSEIB",
    "8.1": "Porcentaje de plazas directivas de IEST encargadas adecuada y oportunamente",
    "9.1": "Porcentaje de títulos emitidos por IESP/EESP que son consignados de manera completa en el sistema TITULA",
    "9.2": "Porcentaje de legajos de los docentes nombrados de los Institutos de Educación Superior Tecnológica públicos registrados adecuadamente en el módulo de escalafón del sistema AYNI",
    "10.1": "Porcentaje de estudiantes de Educación Superior Tecnológica que son matriculados en el REGISTRA de manera oportuna y completa",
}


def compromiso_de(indicador: str) -> int:
    """El compromiso es el primer número del indicador (p. ej., '6.3' -> 6)."""
    return int(indicador.split(".")[0])


# Derivación (D17 y D19). Los especialistas son ficticios; la agrupación refleja la organización
# descrita por la founder, en términos de la norma.
ESPECIALISTAS = {
    "A": ["1.1", "1.2", "1.3"],
    "B": ["2.1", "3.3"],
    "C": ["3.1", "3.2"],
    "D": ["4.1", "5.1"],
    "E": ["6.1", "6.2", "6.3"],
    "F": ["7.1", "7.2", "7.3"],
    "G": ["8.1", "9.2"],
    "H": ["9.1", "10.1"],
}

EQUIPOS = {
    "IMPLEMENTACION": "Implementación y evaluación: numerales 6.1, 6.2, 6.3 y 6.5 (proceso de evaluación), "
                      "VII Responsabilidades, glosario y siglas, Anexo 3 (tramos y modalidad), normativa general.",
    "DATOS": "Datos: 6.4 metas, 6.6 incentivo monetario, 6.7 cálculo de la transferencia, 6.9 implicancias del "
             "incumplimiento del Tramo 2 (para el MMA), Anexo 1 (IGED), Anexos 5-8 (ponderadores, metas, MMA), "
             "consolidación y publicación de resultados preliminares o finales de cada tramo, reportes intermedios.",
    "PRESUPUESTO": "Presupuesto: 6.8 uso de los recursos y PUR (qué se puede financiar), cuándo se realiza la "
                   "transferencia y dónde ver la normativa presupuestal que la aprueba.",
    "COMUNICACIONES": "Comunicaciones: 6.10 asistencia técnica y atención de consultas, asistencias técnicas, "
                      "publicaciones web, canales de consulta.",
}


def especialista_de(indicador: str):
    return next((e for e, inds in ESPECIALISTAS.items() if indicador in inds), None)


# Tramo en que se evalúa cada indicador (Anexo N° 3). 5.1, 6.1 y 6.3 se evalúan en ambos tramos.
TRAMOS = {
    "1.1": [1], "1.2": [1], "1.3": [1], "3.1": [1], "8.1": [1],
    "5.1": [1, 2], "6.1": [1, 2], "6.3": [1, 2],
    "2.1": [2], "3.2": [2], "3.3": [2], "4.1": [2], "6.2": [2], "7.1": [2], "7.2": [2], "7.3": [2],
    "9.1": [2], "9.2": [2], "10.1": [2],
}
