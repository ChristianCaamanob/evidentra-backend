from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.assessment import Assessment
from app.models.answer_key import AnswerKey, AnswerKeyItem
from app.models.base import Base
from app.models.course import Course
from app.models.scan import Scan
from app.models.student import Student
from app.models.teacher import Teacher
from app.models.password_reset import PasswordResetToken
from app.models.en_vivo import SesionEnVivo, ParticipanteVivo, RespuestaVivo, EventoIntegridad  # noqa: F401
from app.models.asistencia import (  # noqa: F401
    AsistenciaMatricula, DispositivoWebAuthn, SesionAsistencia, MarcaAsistencia)
from app.models.suscripcion import Suscripcion, EventoPago  # noqa: F401
from app.models.snapshot import AnalisisSnapshot  # noqa: F401
from app.models.teacher_passkey import TeacherPasskey  # noqa: F401
from app.models.estructura import EstructuraInstitucional  # noqa: F401
from app.models.desarrollo_reporte import DesarrolloRespuesta  # noqa: F401
from app.models.examen_oral import (  # noqa: F401
    OralExamSesion, OralExamSegmento, OralExamEvaluacion)

# Normaliza el esquema de Render/Heroku: SQLAlchemy 2.0 exige 'postgresql://'.
_db_url = settings.database_url
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if _db_url.startswith("sqlite") else {}
engine = create_engine(_db_url, future=True, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


def _seed_cohorte_showcase(db) -> None:
    """Cohorte SHOWCASE Q1 (DEMO-Q1): grande y bien diseñada para exhibir el módulo Investigador
    a máxima potencia. n=600, 24 ítems, 4 RA, respuestas 2PL (discriminación variable → TRI real),
    DIF UNIFORME plantado en 2 ítems (detectable; el resto limpio), grupos consentidos y
    balanceados (ambos ≥200). Enciende Rasch / TRI-2PL / CFA / DINA / DIF / dimensionalidad /
    efectos / cualitativo en verde y con potencia de publicación. Semilla fija (reproducible)."""
    import math
    import random
    from app.models.answer_key import AnswerKey, AnswerKeyItem
    from app.models.student import Student

    if db.query(Course).filter(Course.code == "DEMO-Q1").first():
        return

    course = Course(name="Demo · Showcase Q1", code="DEMO-Q1", status="active",
                    program_document_url=None, has_learning_structure=True,
                    grading_scale="chile_1_7", passing_threshold=60.0, base_score_type="raw_points")
    db.add(course); db.flush()

    k, n, n_ra = 16, 540, 4    # n≥500 potencia DINA/TRI; k=16 mantiene CFA rápida (120 pares)
    assessment = Assessment(course_id=course.id, name="Evaluación integradora (showcase)",
                            status="active", has_versions=False, version_count=1, has_answer_key=True,
                            briefing_level="initial", grading_scale="chile_1_7", passing_threshold=60.0)
    db.add(assessment); db.flush()
    ak = AnswerKey(assessment_id=assessment.id, status="valid", is_valid=True, version_coverage_ok=True,
                   annulled_items_count=0, invalid_weight_count=0, invalid_partial_rule_count=0)
    db.add(ak); db.flush()

    letras = ["A", "B", "C", "D"]
    blooms = ["recordar", "comprender", "aplicar", "analizar"]
    correctas = {}
    for q in range(1, k + 1):
        c = letras[(q * 3) % 4]; correctas[q] = c
        db.add(AnswerKeyItem(answer_key_id=ak.id, question_number=q, version="A",
                             correct_answer=c, weight=1.0, is_annulled=False,
                             learning_outcome_id=f"RA{((q - 1) % n_ra) + 1}",
                             bloom_level=blooms[(q - 1) % len(blooms)]))
    db.flush()

    rng = random.Random(2026)
    a = [round(rng.uniform(0.9, 2.0), 2) for _ in range(k)]           # discriminacion 2PL variable
    b = [round(-2.0 + 4.0 * (j / (k - 1)), 2) for j in range(k)]      # dificultad bien esparcida
    dif_items = {4, 11}                                               # items 5 y 12: DIF uniforme
    mis = [rng.choice([l for l in letras if l != correctas[j + 1]]) for j in range(k)]
    for i in range(n):
        theta = rng.gauss(0, 1)
        sexo = "F" if i % 2 == 0 else "M"
        dep = "municipal" if (i % 5) < 2 else "particular"           # ~40% municipal (~240), resto ~360
        rut = f"Q1-{i+1:04d}"
        db.add(Student(course_id=course.id, rut=rut, nombres=f"Estudiante {i+1}",
                       apellido_paterno="Demo", sexo=sexo, dependencia=dep, consiente_equidad=True))
        answers = []
        for j in range(k):
            b_eff = b[j] + (0.8 if (j in dif_items and dep == "municipal") else 0.0)  # DIF uniforme
            p = 1.0 / (1.0 + math.exp(-a[j] * (theta - b_eff)))
            if rng.random() < p:
                answers.append(correctas[j + 1])
            elif rng.random() < 0.6:
                answers.append(mis[j])                               # concepcion erronea sistematica
            else:
                otras = [l for l in letras if l != correctas[j + 1] and l != mis[j]]
                answers.append(rng.choice(otras) if otras else mis[j])
        db.add(Scan(assessment_id=assessment.id, student_identifier=rut, status="scored",
                    detected_version="A", requires_review=False,
                    raw_ocr_payload_json={"answers": answers}))
    db.commit()


def _seed_cohorte_psicometria(db) -> None:
    """Cohorte demo para exhibir la psicometria (Rasch/DINA/DIF/dimensionalidad/invarianza)
    con datos reales. Idempotente (marcada por Course.code == 'DEMO-PSICO'). ~40 estudiantes,
    12 items etiquetados C3 (3 RA), respuestas generadas por un modelo IRT logistico con
    semilla fija. Todos los estudiantes consienten el analisis de equidad (demo)."""
    import math
    import random
    from app.models.answer_key import AnswerKey, AnswerKeyItem
    from app.models.student import Student

    if db.query(Course).filter(Course.code == "DEMO-PSICO").first():
        return

    course = Course(name="Demo · Psicometría", code="DEMO-PSICO", status="active",
                    program_document_url=None, has_learning_structure=True,
                    grading_scale="chile_1_7", passing_threshold=60.0,
                    base_score_type="raw_points")
    db.add(course); db.flush()

    k, n = 12, 250      # n adecuado para psicometria estable (CFA/DINA/DIF requieren muestra)
    assessment = Assessment(course_id=course.id, name="Ensayo diagnóstico", status="active",
                            assessment_document_url=None, has_versions=False, version_count=1,
                            has_answer_key=True, briefing_level="initial",
                            grading_scale="chile_1_7", passing_threshold=60.0)
    db.add(assessment); db.flush()

    ak = AnswerKey(assessment_id=assessment.id, status="valid", is_valid=True,
                   version_coverage_ok=True, annulled_items_count=0,
                   invalid_weight_count=0, invalid_partial_rule_count=0)
    db.add(ak); db.flush()

    letras = ["A", "B", "C", "D"]
    correctas = {}
    for q in range(1, k + 1):
        c = letras[(q * 3) % 4]
        correctas[q] = c
        db.add(AnswerKeyItem(answer_key_id=ak.id, question_number=q, version="A",
                             correct_answer=c, weight=1.0, is_annulled=False,
                             partial_credit_rule_json=None,
                             learning_outcome_id=f"RA{(q % 3) + 1}", bloom_level="aplicar"))
    db.flush()

    rng = random.Random(42)
    b = [-1.5 + 3.0 * (j / (k - 1)) for j in range(k)]     # dificultad por item
    # Distractor de "concepcion erronea" por item: quien falla lo elige con prob 0.6 (el resto,
    # otro distractor al azar). Concentra un error sistematico -> el mapa cualitativo es real.
    mis = [rng.choice([l for l in letras if l != correctas[j + 1]]) for j in range(k)]
    for i in range(n):
        theta = rng.gauss(0, 1)                            # habilidad del estudiante
        rut = f"DEMO-{i+1:03d}"
        db.add(Student(course_id=course.id, rut=rut, nombres=f"Estudiante {i+1}",
                       apellido_paterno="Demo", sexo=("F" if i % 2 == 0 else "M"),
                       dependencia=("municipal" if i % 3 == 0 else "particular"),
                       consiente_equidad=True))
        answers = []
        for j in range(k):
            p = 1.0 / (1.0 + math.exp(-(theta - b[j])))
            if rng.random() < p:
                answers.append(correctas[j + 1])
            elif rng.random() < 0.6:
                answers.append(mis[j])                     # concepcion erronea sistematica
            else:
                otras = [l for l in letras if l != correctas[j + 1] and l != mis[j]]
                answers.append(rng.choice(otras) if otras else mis[j])
        db.add(Scan(assessment_id=assessment.id, student_identifier=rut, status="scored",
                    detected_version="A", requires_review=False,
                    raw_ocr_payload_json={"answers": answers}))
    db.commit()


def _seed_desarrollo(db) -> None:
    """Pregunta de desarrollo (open_response) con rúbrica de 2 criterios y anclas, para
    exhibir la pre-calificación con IA (F2) y la validación docente (F3). Idempotente
    (marcada por Course.code == 'DEMO-DESA'). En un curso aparte para no tocar la
    psicometría de alternativas."""
    from app.models.answer_key import (AnswerKey, AnswerKeyItem, RubricCriterion,
                                       RubricAncla, QUESTION_TYPE_OPEN_RESPONSE)

    if db.query(Course).filter(Course.code == "DEMO-DESA").first():
        return

    course = Course(name="Demo · Desarrollo", code="DEMO-DESA", status="active",
                    program_document_url=None, has_learning_structure=True,
                    grading_scale="chile_1_7", passing_threshold=60.0,
                    base_score_type="raw_points")
    db.add(course); db.flush()
    a = Assessment(course_id=course.id, name="Ensayo · Sistema linfático", status="active",
                   assessment_document_url=None, has_versions=False, version_count=1,
                   has_answer_key=True, briefing_level="initial",
                   grading_scale="chile_1_7", passing_threshold=60.0)
    db.add(a); db.flush()
    ak = AnswerKey(assessment_id=a.id, status="valid", is_valid=True, version_coverage_ok=True,
                   annulled_items_count=0, invalid_weight_count=0, invalid_partial_rule_count=0)
    db.add(ak); db.flush()
    item = AnswerKeyItem(answer_key_id=ak.id, question_number=1, version="A", correct_answer="",
                         weight=20.0, is_annulled=False, question_type=QUESTION_TYPE_OPEN_RESPONSE,
                         learning_outcome_id="RA1", bloom_level="comprender",
                         enunciado="Explica la función del sistema linfático en la respuesta inmune.")
    db.add(item); db.flush()

    c1 = RubricCriterion(answer_key_item_id=item.id, name="Función de drenaje y transporte de linfa",
                         weight=1.0, order=0, nivel_exigencia="tolerante", umbral_confianza=0.7,
                         sinonimos_json=["líquido intersticial", "drenaje", "transporte"])
    db.add(c1); db.flush()
    for t, n, o in [("El sistema linfático drena el líquido intersticial y lo devuelve a la sangre, transportando linfa.", "logrado", 0),
                    ("Transporta líquido por el cuerpo.", "parcial", 1),
                    ("Bombea sangre al corazón.", "no_logrado", 2)]:
        db.add(RubricAncla(rubric_criterion_id=c1.id, texto=t, nivel=n, order=o))
    c2 = RubricCriterion(answer_key_item_id=item.id, name="Relación con la respuesta inmune",
                         weight=1.0, order=1, nivel_exigencia="estricto", umbral_confianza=0.7,
                         sinonimos_json=["linfocitos", "ganglios linfáticos", "inmunidad"])
    db.add(c2); db.flush()
    for t, n, o in [("Los ganglios linfáticos filtran patógenos y activan linfocitos, participando en la respuesta inmune.", "logrado", 0),
                    ("Ayuda a defender el cuerpo de enfermedades.", "parcial", 1),
                    ("Solo transporta líquidos.", "no_logrado", 2)]:
        db.add(RubricAncla(rubric_criterion_id=c2.id, texto=t, nivel=n, order=o))
    db.flush()

    # 2ª pregunta de desarrollo (peso 15 pts) — demuestra el instrumento multi-pregunta.
    item2 = AnswerKeyItem(answer_key_id=ak.id, question_number=2, version="A", correct_answer="",
                          weight=15.0, is_annulled=False, question_type=QUESTION_TYPE_OPEN_RESPONSE,
                          learning_outcome_id="RA2", bloom_level="analizar",
                          enunciado="Compara el sistema linfático con el circulatorio: una semejanza y una diferencia.")
    db.add(item2); db.flush()
    c3 = RubricCriterion(answer_key_item_id=item2.id, name="Semejanza y diferencia correctas",
                         weight=1.0, order=0, nivel_exigencia="tolerante", umbral_confianza=0.7,
                         sinonimos_json=["red de vasos", "transporte", "unidireccional"])
    db.add(c3); db.flush()
    for t, n, o in [("Ambos son redes de vasos; el linfático es unidireccional y drena hacia la sangre.", "logrado", 0),
                    ("Los dos transportan líquidos por el cuerpo.", "parcial", 1),
                    ("Son lo mismo.", "no_logrado", 2)]:
        db.add(RubricAncla(rubric_criterion_id=c3.id, texto=t, nivel=n, order=o))
    db.flush()

    # ── Validaciones docentes (F3) simuladas: activan R (psicometría de rúbrica), MFRM
    # (severidad IA vs docente) y F4 (aprendizaje). Sin esto, esos análisis quedan inertes. ──
    import hashlib, random, math
    from app.models.validacion import RegistroValidacion
    rngv = random.Random(7)
    niveles = ["no_logrado", "parcial", "logrado"]
    crits = [(c1.name, 0.0), (c2.name, 0.7)]           # (nombre, dificultad; c2 es más estricto)

    def _nivel(theta, dif):
        p = 1.0 / (1.0 + math.exp(-(theta - dif)))
        return "logrado" if p > 0.66 else ("parcial" if p > 0.4 else "no_logrado")

    regs = []
    for s in range(18):
        theta = rngv.gauss(0.3, 1.0)
        href = "e:" + hashlib.sha256(("dev-stu-%d" % s).encode()).hexdigest()[:8]
        for cname, cdif in crits:
            niv_ia = _nivel(theta, cdif)
            conf = round(rngv.uniform(0.55, 0.95), 2)
            if rngv.random() < 0.6:                     # el docente aprueba la propuesta IA
                niv_doc, accion, com = niv_ia, "aprobado", None
            else:                                        # el docente ajusta (sesgo estricto en c2)
                idx = niveles.index(niv_ia)
                delta = -1 if (cdif > 0.3 and rngv.random() < 0.65) else rngv.choice([-1, 1])
                idx2 = max(0, min(2, idx + delta))
                niv_doc = niveles[idx2]
                accion = "ajustado" if idx2 != idx else "aprobado"
                com = ("Falta el término canónico exigido por la norma." if niv_doc != niv_ia else None)
            regs.append(RegistroValidacion(
                respuesta_ref=href + "#" + cname, criterio=cname, assessment_id=str(a.id),
                rubrica_version_hash=None, nivel_ia=niv_ia, confianza_ia=conf,
                nivel_docente=niv_doc, accion=accion, comentario=com, docente="docente@evalys.demo"))
    db.add_all(regs)
    db.commit()


def _seed_ficha_p3(db):
    """DEMO-FICHA (P3): cursos VISIBLES AL DOCENTE con nómina + Tabla de Especificaciones
    (LearningOutcome) + 2 pruebas etiquetadas por RA + escaneos ligados por RUT, con brechas
    variadas. Exhibe la ficha del alumno, el informe personalizado y —con facultad/departamento—
    el panorama del Director. Idempotente por Course.code == 'DEMO-FICHA'."""
    from app.models.curriculo import LearningOutcome
    from app.models.student import Student
    ra_de_q = {1: "RA1", 2: "RA1", 3: "RA2", 4: "RA2", 5: "RA3", 6: "RA3"}  # 2 ítems por RA
    # Patrones de respuesta (correcta = "A"): logros/brechas distintos por RA y por prueba.
    solemne = [["A", "A", "A", "B", "B", "B"], ["A", "B", "A", "A", "A", "A"],
               ["B", "B", "B", "A", "A", "A"], ["A", "A", "A", "A", "A", "B"],
               ["B", "A", "B", "B", "B", "B"], ["A", "A", "B", "A", "B", "A"]]
    control = [["A", "A", "B", "B", "A", "A"], ["A", "A", "A", "B", "A", "A"],
               ["B", "A", "B", "B", "A", "B"], ["A", "A", "A", "A", "B", "A"],
               ["A", "B", "B", "A", "B", "B"], ["A", "A", "A", "A", "A", "A"]]
    nombres = [("Soto", "Vera", "Ana"), ("Lira", "Paz", "Beto"), ("Rojas", "Díaz", "Carolina"),
               ("Díaz", "Mora", "Darío"), ("Muñoz", "Rey", "Elsa"), ("Vega", "Luna", "Franco")]

    def _backfill(existing, name, tipo, fac, dep):
        cambio = False
        if existing.name and existing.name.startswith("Demo"):
            existing.name = name; cambio = True
        if not existing.tipo:
            existing.tipo = tipo; cambio = True
        if existing.status != "active":
            existing.status = "active"; cambio = True
        if not existing.facultad:
            existing.facultad = fac; cambio = True
        if not existing.departamento:
            existing.departamento = dep; cambio = True
        if cambio:
            db.commit()

    def _curso(code, name, tipo, ras, fac, dep, rut_pref, patrones_solemne):
        existing = db.query(Course).filter(Course.code == code).first()
        if existing is not None:
            _backfill(existing, name, tipo, fac, dep)
            return
        course = Course(name=name, code=code, status="active", tipo=tipo, facultad=fac,
                        departamento=dep, grading_scale="chile_1_7", passing_threshold=60.0)
        db.add(course); db.flush()
        for i, (rcode, text) in enumerate(ras, start=1):
            db.add(LearningOutcome(course_id=course.id, code=rcode, text=text, orden=i))
        ruts = [f"{rut_pref}{k}.{k}{k}{k}.{k}{k}{k}-{k}" for k in range(1, 7)]
        for rut, (ap, am, nom) in zip(ruts, nombres):
            db.add(Student(course_id=course.id, rut=rut, apellido_paterno=ap,
                           apellido_materno=am, nombres=nom))
        db.flush()

        def _prueba(pn, tp, vectores, origen):
            a = Assessment(course_id=course.id, name=pn, tipo=tp, modalidad="alternativas",
                           grading_scale="chile_1_7", passing_threshold=60.0)
            db.add(a); db.flush()
            ak = AnswerKey(assessment_id=a.id, status="valid", is_valid=True)
            db.add(ak); db.flush()
            for q in range(1, 7):
                db.add(AnswerKeyItem(answer_key_id=ak.id, question_number=q, version="A",
                                     correct_answer="A", weight=1.0,
                                     learning_outcome_id=ra_de_q[q], bloom_level="aplicar"))
            for rut, vec in zip(ruts, vectores):
                db.add(Scan(assessment_id=a.id, student_identifier=rut,
                            status=("en_vivo" if origen == "en_vivo" else "scored"),
                            detected_version="A", requires_review=False, origen=origen,
                            raw_ocr_payload_json={"answers": vec, "origen": origen}))

        _prueba("Solemne 1 · alternativas", "solemne", patrones_solemne, "omr")
        _prueba("Control 2 · en vivo", "control", control, "en_vivo")

    # ── Curso insignia GRANDE y realista — SHOWCASE del demo ──────────────────────────────────
    # Aditivo e idempotente: crea el curso/nómina/RA si faltan y AGREGA cada evaluación por nombre
    # si aún no existe (así un DEMO-MORFO ya sembrado recibe los nuevos tipos de prueba en el
    # próximo arranque, sin borrar nada). Determinista por hash → estable entre reinicios.
    def _curso_grande(code, name, tipo, ras, fac, dep, n_est, seed):
        import hashlib
        letras = ["A", "B", "C", "D"]

        def _h(*parts):
            return int(hashlib.md5(("|".join(map(str, parts)) + "|" + str(seed)).encode()).hexdigest(), 16)

        def _u(*parts):                       # uniforme 0..1 determinista
            return (_h(*parts) % 1_000_000) / 1_000_000

        def _codigo_sesion(h):                # código de sala tipo "26PZVT"
            alf = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            s = ""
            for _ in range(6):
                s += alf[h % 36]; h //= 36
            return s

        APE = ["Soto", "Rojas", "Muñoz", "Díaz", "Vega", "Fuentes", "Contreras", "Morales", "Silva",
               "Araya", "Castro", "Reyes", "Espinoza", "Tapia", "Núñez", "Fernández", "Gutiérrez",
               "Pizarro", "Sepúlveda", "Cortés", "Riquelme", "Valdés", "Bravo", "Cárdenas"]
        NOM = ["Ana", "Benjamín", "Catalina", "Diego", "Elisa", "Felipe", "Gabriela", "Hugo",
               "Isidora", "Joaquín", "Karina", "Lucas", "Martina", "Nicolás", "Olivia", "Pablo",
               "Renata", "Sebastián", "Trinidad", "Vicente", "Amanda", "Emilio", "Josefa", "Matías"]

        course = db.query(Course).filter(Course.code == code).first()
        if course is None:
            course = Course(name=name, code=code, status="active", tipo=tipo, facultad=fac,
                            departamento=dep, grading_scale="chile_1_7", passing_threshold=60.0)
            db.add(course); db.flush()
        else:
            _backfill(course, name, tipo, fac, dep)

        n_ra = len(ras)
        # Tabla de Especificaciones (RA): agrega los que falten.
        ya_ra = {r.code for r in db.query(LearningOutcome).filter(LearningOutcome.course_id == course.id).all()}
        for i, (rcode, text) in enumerate(ras, start=1):
            if rcode not in ya_ra:
                db.add(LearningOutcome(course_id=course.id, code=rcode, text=text, orden=i))
        db.flush()

        # Nómina: reusa la existente; si no hay, la crea.
        existentes = db.query(Student).filter(Student.course_id == course.id).all()
        if existentes:
            ruts = [s.rut for s in existentes]
        else:
            ruts = []
            for k in range(n_est):
                nn = 18000000 + seed * 100000 + k * 373
                rut = f"{nn // 1000000}.{(nn // 1000) % 1000:03d}.{nn % 1000:03d}-{k % 10}"
                ruts.append(rut)
                db.add(Student(course_id=course.id, rut=rut, apellido_paterno=APE[(seed + k) % len(APE)],
                               apellido_materno=APE[(seed + k * 3 + 5) % len(APE)],
                               nombres=NOM[(seed + k * 2) % len(NOM)]))
            db.flush()

        n_items = n_ra * 3                                   # 3 ítems por RA
        ra_q = {q: "RA%d" % (((q - 1) // 3) + 1) for q in range(1, n_items + 1)}

        def correcta(q, v):
            return letras[_h("key", q, v) % 4]

        def abil(rut, ra, boost):                            # habilidad 0.05–0.98 (brechas + tendencia)
            return max(0.05, min(0.98, 0.2 + _u("abil", rut, ra) * 0.72 + boost))

        def _prueba(pn, tp, origen="omr", boost=0.0, con_scans=True):
            # Idempotente por nombre: si ya existe esa evaluación en el curso, no la re-crea.
            if db.query(Assessment).filter(Assessment.course_id == course.id, Assessment.name == pn).first():
                return
            a = Assessment(course_id=course.id, name=pn, tipo=tp,
                           modalidad=("en_vivo" if origen == "en_vivo" else "alternativas"),
                           grading_scale="chile_1_7", passing_threshold=60.0)
            db.add(a); db.flush()
            ak = AnswerKey(assessment_id=a.id, status="valid", is_valid=True)
            db.add(ak); db.flush()
            for q in range(1, n_items + 1):
                for v in ("A", "B"):
                    db.add(AnswerKeyItem(answer_key_id=ak.id, question_number=q, version=v,
                                         correct_answer=correcta(q, v), weight=1.0,
                                         learning_outcome_id=ra_q[q], bloom_level="aplicar"))
            if not con_scans:
                return   # evaluación PENDIENTE (programada, aún sin rendir) → pronóstico mid-course
            sesiones = [_codigo_sesion(_h("ses", pn, i)) for i in range(2)] if origen == "en_vivo" else None
            for idx, rut in enumerate(ruts):
                v = "A" if _h("ver", pn, rut) % 2 == 0 else "B"
                ans = []
                for q in range(1, n_items + 1):
                    if _u("ans", pn, rut, q) < abil(rut, ra_q[q], boost):
                        ans.append(correcta(q, v))
                    else:
                        wrong = [l for l in letras if l != correcta(q, v)]
                        ans.append(wrong[_h("w", pn, rut, q) % len(wrong)])
                payload = {"answers": ans, "origen": origen}
                if sesiones:
                    payload["sesion"] = sesiones[idx % len(sesiones)]
                db.add(Scan(assessment_id=a.id, student_identifier=rut,
                            status=("en_vivo" if origen == "en_vivo" else "scored"),
                            detected_version=v, requires_review=False, origen=origen,
                            raw_ocr_payload_json=payload))

        # Varios TIPOS de prueba → el demo explota: filtros por tipo/origen, comparativa multi-eval
        # con tendencia (los boosts crean mejora visible) y trazabilidad de sesión en vivo.
        _prueba("Solemne 1", "solemne", "omr", 0.00)
        _prueba("Solemne 2", "solemne", "omr", 0.11)
        _prueba("Certamen", "certamen", "omr", 0.06)
        _prueba("Control 1", "control", "omr", -0.05)
        _prueba("Quiz en vivo Nº1", "control", "en_vivo", 0.09)
        _prueba("Examen final", "certamen", "omr", 0.0, con_scans=False)   # PENDIENTE → mid-course
        db.flush()

        # Parametrización demo (pesos que suman 100% + asistencia + semáforo). Incluye el Examen
        # final PENDIENTE (peso restante) para exhibir el pronóstico mid-course ("necesita X…").
        # Re-siembra si falta o si aún no incluye el Examen final (curso ya sembrado antes).
        _pactual = course.parametrizacion or {}
        _tiene_examen = any((cc.get("nombre") == "Examen final") for cc in (_pactual.get("componentes") or []))
        if not _pactual or not _tiene_examen:
            asm_by_name = {a.name: str(a.id) for a in
                           db.query(Assessment).filter(Assessment.course_id == course.id).all()}
            pesos = [("Solemne 1", "solemne", 20), ("Solemne 2", "solemne", 20),
                     ("Certamen", "certamen", 20), ("Control 1", "control", 10),
                     ("Quiz en vivo Nº1", "lab_envivo", 10), ("Examen final", "certamen", 20)]
            comps = [{"id": "d%d" % i, "nombre": nm, "categoria": cat, "peso_pct": pw,
                      "assessment_id": asm_by_name.get(nm)}
                     for i, (nm, cat, pw) in enumerate(pesos, start=1) if asm_by_name.get(nm)]
            if comps:
                course.parametrizacion = {"activa": True, "componentes": comps,
                                          "asistencia": {"teorico_pct": 75, "teorico_libre": False,
                                                         "lab_pct": 100, "modo": "gate"},
                                          "semaforo": {"nota_verde": 5.0, "nota_amarillo": 4.0,
                                                       "asist_amarillo_min": 50}}
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(course, "parametrizacion")
                db.flush()

    _curso("DEMO-FICHA", "Histología", "teorico",
           [("RA1", "Identifica y describe las estructuras anatómicas fundamentales."),
            ("RA2", "Relaciona estructura y función en los sistemas del cuerpo."),
            ("RA3", "Integra los conceptos en el análisis de casos clínicos.")],
           "Facultad de Medicina", "Departamento de Anatomía", "1", solemne)
    _curso("DEMO-FICHA2", "Fisiología Humana", "teorico",
           [("RA1", "Explica los mecanismos fisiológicos básicos."),
            ("RA2", "Interpreta parámetros funcionales en distintos sistemas."),
            ("RA3", "Aplica el razonamiento fisiológico a casos clínicos.")],
           "Facultad de Medicina", "Departamento de Fisiología", "9",
           [["A", "B", "A", "B", "A", "A"], ["A", "A", "A", "A", "B", "B"],
            ["B", "B", "A", "A", "A", "A"], ["A", "A", "B", "B", "B", "A"],
            ["A", "A", "A", "A", "A", "A"], ["B", "A", "B", "A", "B", "B"]])
    _curso_grande("DEMO-MORFO", "Morfología Humana", "teorico",
                  [("RA1", "Identifica las estructuras y niveles de organización del cuerpo humano."),
                   ("RA2", "Relaciona la estructura de los tejidos con su función."),
                   ("RA3", "Analiza la organización de los sistemas y aparatos."),
                   ("RA4", "Integra los conceptos morfológicos en el razonamiento clínico.")],
                  "Facultad de Medicina", "Departamento de Anatomía", 24, 7)
    db.commit()


# Columnas ADITIVAS que deben existir aunque Alembic no corra (prod histórico usa
# create_all, que crea tablas nuevas pero NO altera las existentes). Idempotente: solo
# añade las que faltan. DDL válido en Postgres (prod) y SQLite (local/tests).
_COLUMNAS_ADITIVAS = {
    "oral_exam_sesiones": {
        "vivo_token": "VARCHAR(40)",
    },
    "sesiones_en_vivo": {
        "retro_alumno": "BOOLEAN NOT NULL DEFAULT false",
        "revelar_correccion": "BOOLEAN NOT NULL DEFAULT true",
        "mascota_motivacional": "BOOLEAN NOT NULL DEFAULT true",
        "duracion_min": "INTEGER NOT NULL DEFAULT 0",
        "timer_inicio_ts": "INTEGER",
        "modo_ritmo": "VARCHAR(20) NOT NULL DEFAULT 'docente'",
        "shuffle_preguntas": "BOOLEAN NOT NULL DEFAULT false",
        "shuffle_opciones": "BOOLEAN NOT NULL DEFAULT false",
        "requiere_seb": "BOOLEAN NOT NULL DEFAULT false",
        "seb_config_key": "VARCHAR(80)",
        "atencion_camara": "BOOLEAN NOT NULL DEFAULT false",
        "auditorio_items_json": "JSON",
    },
    "participantes_vivo": {
        "layout_json": "JSON",
        "progreso": "INTEGER NOT NULL DEFAULT 0",
        "bloqueado": "BOOLEAN NOT NULL DEFAULT false",
        "bloqueado_motivo": "VARCHAR(255)",
        "ultimo_latido_ts": "INTEGER",
        "device_id": "VARCHAR(64)",
        "tiempo_extra_seg": "INTEGER NOT NULL DEFAULT 0",
    },
    "answer_key_items": {
        "opciones_json": "JSON",
        "justificacion": "TEXT",
        "enunciado_imagen": "TEXT",
        "respuesta_optima": "TEXT",
        "nivel_rigor": "VARCHAR(20) NOT NULL DEFAULT 'estricto'",
        "area_conocimiento": "VARCHAR(40)",
        "fuente_estandar": "TEXT",
        "tiempo_reflexion_seg": "INTEGER",
        "tiempo_max_seg": "INTEGER",
        "conceptos_indispensables": "TEXT",
        "errores_criticos": "TEXT",
    },
    "asistencia_matriculas": {
        "webauthn_challenge": "VARCHAR(255)",
        "webauthn_challenge_exp": "INTEGER",
    },
    "assessments": {
        "tipo": "VARCHAR(20)",
        "ponderacion_semestral": "FLOAT",
    },
    "teachers": {
        "email_verificado": "BOOLEAN NOT NULL DEFAULT true",
    },
    "courses": {
        "tipo": "VARCHAR(20)",
        "departamento": "VARCHAR(160)",
        "facultad": "VARCHAR(160)",
        "norma_terminologica": "VARCHAR(120)",
        "parametrizacion": "JSON",
    },
    "scans": {
        "origen": "VARCHAR(20)",
    },
    "silabo_agentes": {
        "ayudante_activo": "BOOLEAN NOT NULL DEFAULT false",
        "ayudante_codigo": "VARCHAR(12)",
    },
    "silabo_mensajes": {
        "device_id": "VARCHAR(64)",
        "tipo": "VARCHAR(40)",
        "vence_ts": "INTEGER",
        "cita": "TEXT",
        "nivel": "INTEGER NOT NULL DEFAULT 3",
        "respondido_por": "VARCHAR(16)",
        "motivo_escalamiento": "VARCHAR(255)",
        "tema": "VARCHAR(120)",
        "fuente": "VARCHAR(16)",
        "confianza": "VARCHAR(8)",
    },
}


def _ensure_columns(log) -> None:
    """Añade columnas aditivas que falten en tablas ya existentes (idempotente)."""
    from sqlalchemy import inspect as sa_inspect, text
    try:
        insp = sa_inspect(engine)
        tablas = set(insp.get_table_names())
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudo inspeccionar el esquema: %s", e); return
    for tabla, cols in _COLUMNAS_ADITIVAS.items():
        if tabla not in tablas:
            continue
        try:
            existentes = {c["name"] for c in insp.get_columns(tabla)}
        except Exception:
            continue
        for nombre, ddl in cols.items():
            if nombre in existentes:
                continue
            try:
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE {tabla} ADD COLUMN {nombre} {ddl}'))
                log.info("Columna aditiva añadida: %s.%s", tabla, nombre)
            except Exception as e:  # noqa: BLE001
                log.warning("No se pudo añadir %s.%s: %s", tabla, nombre, e)


def _init_schema() -> None:
    """Crea/actualiza el esquema. Fuente de verdad = Alembic (upgrade head). Si Alembic no
    está disponible o falla, cae a create_all (idempotente) para no bloquear el arranque.
    Tras crear, garantiza columnas aditivas en tablas existentes (independiente de Alembic)."""
    import logging
    log = logging.getLogger("evalys")
    if settings.run_migrations:
        try:
            import os
            from alembic.config import Config
            from alembic import command
            root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # repo root
            cfg = Config(os.path.join(root, "alembic.ini"))
            cfg.set_main_option("script_location", os.path.join(root, "alembic"))  # robusto ante cwd
            command.upgrade(cfg, "head")
            log.info("Esquema al día vía Alembic (upgrade head).")
        except Exception as e:  # noqa: BLE001
            log.warning("Alembic upgrade falló, se usa create_all: %s", e)
    Base.metadata.create_all(bind=engine)
    _ensure_columns(log)


def _promote_owners() -> None:
    """Owner bootstrap: promueve a rol 'creador' (acceso total) los correos declarados en
    EVALYS_OWNER_EMAILS (coma-separado; por defecto el correo del CEO). Idempotente; corre
    SIEMPRE (también en producción). Así el dueño tiene acceso real sin depender del modo demo."""
    import os
    emails = [e.strip().lower() for e in
              os.getenv("EVALYS_OWNER_EMAILS", "mispelis2020@gmail.com").split(",") if e.strip()]
    if not emails:
        return
    db = SessionLocal()
    try:
        for em in emails:
            t = db.query(Teacher).filter(Teacher.email == em).first()
            if t and t.rol != "creador":
                t.rol = "creador"
                t.email_verificado = True
                print(f"[OWNER] {em} promovido a creador", flush=True)
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        print(f"[OWNER ERROR] {e}", flush=True)
    finally:
        db.close()


def create_db_and_seed() -> None:
    _init_schema()
    _promote_owners()   # el dueño (CEO) siempre queda con acceso total, con o sin datos demo
    # En producción real (SEED_DEMO=false) el sistema arranca vacío: los usuarios se
    # auto-registran y crean sus cursos. Los datos demo solo para exhibición.
    if not settings.seed_demo:
        return
    db = SessionLocal()
    try:
        # Usuarios demo para el login (idempotentes): permiten mostrar el producto
        # funcionando. 'profesor' es el auto-registro estandar; 'investigador' accede al
        # modulo de psicometria (RBAC).
        from app.services.auth_service import hash_password
        if not db.query(Teacher).filter(Teacher.email == "docente@evalys.demo").first():
            db.add(Teacher(email="docente@evalys.demo",
                           hashed_password=hash_password("evalys2026"),
                           name="Docente Demo", rol="profesor"))
            db.commit()
        if not db.query(Teacher).filter(Teacher.email == "investigador@evalys.demo").first():
            db.add(Teacher(email="investigador@evalys.demo",
                           hashed_password=hash_password("evalys2026"),
                           name="Investigadora Demo", rol="investigador"))
            db.commit()
        # Cuenta OWNER (creador): acceso TOTAL a todos los perfiles con datos reales. Es la que
        # usa el CEO para trabajar; las demás cuentas demo siguen mostrando el modo demostración.
        if not db.query(Teacher).filter(Teacher.email == "director@evalys.demo").first():
            db.add(Teacher(email="director@evalys.demo",
                           hashed_password=hash_password("evalys2026"),
                           name="Director(a) Demo", rol="director", email_verificado=True))
            db.commit()
        _adm = db.query(Teacher).filter(Teacher.email == "admin@evalys.demo").first()
        if not _adm:
            db.add(Teacher(email="admin@evalys.demo",
                           hashed_password=hash_password("evalys2026"),
                           name="Administrador", rol="creador", email_verificado=True))
            db.commit()
        elif not getattr(_adm, "email_verificado", False) or _adm.rol != "creador":
            _adm.email_verificado = True; _adm.rol = "creador"; db.commit()

        # Cohortes demo (idempotentes por su propia marca).
        _seed_cohorte_psicometria(db)
        _seed_cohorte_showcase(db)        # DEMO-Q1: showcase grande (n=600) del módulo Investigador
        _seed_desarrollo(db)
        _seed_ficha_p3(db)                # DEMO-FICHA: ficha del estudiante (brechas por RA) + informe

        course = db.query(Course).filter(
            Course.code.notin_(["DEMO-PSICO", "DEMO-DESA", "DEMO-FICHA"])).first()
        if course:
            return

        course = Course(
            name="Morfología",
            code="DMOR-0030",
            status="draft",
            program_document_url="https://files.example/programa.pdf",
            has_learning_structure=False,
            grading_scale="chile_1_7",
            passing_threshold=60,
            base_score_type="raw_points",
        )
        db.add(course)
        db.flush()

        assessment = Assessment(
            course_id=course.id,
            name="Solemne 1",
            status="draft",
            assessment_document_url=None,
            has_versions=True,
            version_count=2,
            has_answer_key=True,
            briefing_level="initial",
        )
        db.add(assessment)
        db.flush()

        answer_key = AnswerKey(
            assessment_id=assessment.id,
            status="draft",
            is_valid=False,
            version_coverage_ok=True,
            annulled_items_count=1,
            invalid_weight_count=0,
            invalid_partial_rule_count=1,
        )
        db.add(answer_key)
        db.flush()

        db.add_all(
            [
                AnswerKeyItem(
                    answer_key_id=answer_key.id,
                    question_number=1,
                    version="A",
                    correct_answer="B",
                    weight=1.0,
                    is_annulled=False,
                    partial_credit_rule_json=None,
                ),
                AnswerKeyItem(
                    answer_key_id=answer_key.id,
                    question_number=1,
                    version="B",
                    correct_answer="C",
                    weight=1.0,
                    is_annulled=False,
                    partial_credit_rule_json=None,
                ),
                AnswerKeyItem(
                    answer_key_id=answer_key.id,
                    question_number=2,
                    version="A",
                    correct_answer="D",
                    weight=1.0,
                    is_annulled=True,
                    partial_credit_rule_json={"invalid": True},
                ),
            ]
        )

        scan = Scan(
            assessment_id=assessment.id,
            student_identifier="student_001",
            status="requires_review",
            detected_version="B",
            requires_review=True,
            ambiguity_count=1,
            unresolved_ambiguity_count=1,
            review_reasons_json=["corrector con ambigüedad real"],
            sheet_image_url=None,
            raw_ocr_payload_json={"provider": "mock", "confidence": 0.94},
        )
        db.add(scan)
        db.commit()
    finally:
        db.close()
