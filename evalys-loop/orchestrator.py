#!/usr/bin/env python3
"""
Evalys - Orquestador del loop de avance autonomo
=================================================

Idea central (lo que hace que corra SIN que estes mirando cada 30 min):
el loop no solo *hace*, sino que se *verifica solo*. Cada hito tiene una
Definition of Done comprobable (tests) y toda la corrida respeta las guardas
de gobernanza (seudonimizacion, lenguaje propositivo). Si algo no pasa, no hay
commit y no se marca como hecho.

Ciclo por iteracion:
  1. Elegir el siguiente hito accionable (dependencias cumplidas, status pending).
  2. Si es un hito con gate humano y no esta aprobado -> needs_review + escalar + saltar.
  3. Ejecutar el paso de agente (agent_step): API Claude o Claude Code. <- SEAM
  4. Correr los tests de aceptacion del hito.
  5. Correr las guardas de gobernanza (siempre).
  6. Si todo verde -> git commit + marcar 'done' + log. Si no -> reintentar (reparar)
     hasta max_repairs; si sigue rojo -> 'blocked' + escalar.
  7. Topes: max_iterations, max_wall_seconds, presupuesto. Detector de atasco -> escalar.

SEGURIDAD: por defecto corre en DRY-RUN (no ejecuta el agente ni hace commits).
Para correr de verdad: `python orchestrator.py --run`.

Requisitos: solo stdlib para el arnes. El "cerebro" (agent_step) necesita tu
entorno: ANTHROPIC_API_KEY (engine=api) o Claude Code instalado (engine=claude_code).
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEDGER = ROOT / "estados.json"
CONFIG = ROOT / "loop_config.json"
LOG = ROOT / "loop_log.jsonl"
PROGRESS = ROOT / "PROGRESS.md"
ESCALATION = ROOT / "ESCALATION.md"


# ----------------------------------------------------------------------------- utilidades
def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def save_ledger(data: dict) -> None:
    LEDGER.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def log_event(event: dict) -> None:
    event = {"ts": now(), **event}
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    print(f"[{event['ts']}] {event.get('kind','')}: {event.get('msg','')}")


def run_cmd(cmd: str, cwd: Path, timeout: int = 1800) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=str(cwd), shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)[-4000:]
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT tras {timeout}s: {cmd}"
    except Exception as e:  # noqa: BLE001
        return 1, f"ERROR ejecutando '{cmd}': {e}"


# ----------------------------------------------------------------------------- ledger / estado
def milestone_by_id(ledger: dict, mid: str) -> dict | None:
    for m in ledger["milestones"]:
        if m["id"] == mid:
            return m
    return None


def deps_done(ledger: dict, m: dict) -> bool:
    for d in m.get("depends_on", []):
        dep = milestone_by_id(ledger, d)
        if not dep or dep.get("status") != "done":
            return False
    return True


def gate_blocked(m: dict, cfg: dict) -> bool:
    """True si el hito tiene gate humano y aun no fue aprobado en la config."""
    return m.get("gate") == "human" and m["id"] not in set(cfg.get("human_approvals", []))


def next_actionable(ledger: dict, cfg: dict) -> dict | None:
    for m in ledger["milestones"]:
        if m.get("status") in ("pending", "needs_review") and deps_done(ledger, m) \
                and not gate_blocked(m, cfg):
            return m
    return None


def set_status(ledger: dict, m: dict, status: str) -> None:
    m["status"] = status
    m["updated_at"] = now()
    save_ledger(ledger)


# ----------------------------------------------------------------------------- gates / escalacion
def human_approved(m: dict, cfg: dict) -> bool:
    """Un hito con gate humano solo avanza si su id esta en approvals de la config."""
    return m["id"] in set(cfg.get("human_approvals", []))


def escalate(m: dict, reason: str, cfg: dict) -> None:
    line = f"- [{now()}] **{m['id']}** ({m['title']}): {reason}\n"
    with ESCALATION.open("a", encoding="utf-8") as fh:
        fh.write(line)
    log_event({"kind": "ESCALATION", "milestone": m["id"], "msg": reason})
    hook = cfg.get("escalation_webhook")
    if hook:
        # Gancho opcional: notificacion (Slack/email/etc.). Se deja documentado.
        log_event({"kind": "ESCALATION_HOOK", "msg": f"(configurar POST a {hook})"})


# ----------------------------------------------------------------------------- verificacion
def run_acceptance(m: dict, cfg: dict) -> tuple[bool, str]:
    acc = m.get("acceptance", {})
    code_root = Path(cfg.get("code_root", "."))
    atype = acc.get("type")
    if atype == "human_review":
        # La parte automatizable (si hay cmd) se corre igual; la validacion humana es el gate.
        if acc.get("cmd"):
            rc, out = run_cmd(acc["cmd"], code_root)
            return rc == 0, out
        return True, "(hito de revision humana; sin comando automatico)"
    if atype == "cmd":
        rc, out = run_cmd(acc["cmd"], code_root)
        return rc == 0, out
    return True, "(sin criterio automatico definido)"


def run_governance(cfg: dict) -> tuple[bool, str]:
    rc, out = run_cmd(f"python {ROOT/'checks'/'run_all_checks.py'}", ROOT)
    return rc == 0, out


# ----------------------------------------------------------------------------- git
def git_commit(m: dict, cfg: dict) -> None:
    code_root = Path(cfg.get("code_root", "."))
    msg = f"[loop] {m['id']}: {m['title']}"
    run_cmd("git add -A", code_root)
    run_cmd(f'git commit -m "{msg}"', code_root)
    log_event({"kind": "COMMIT", "milestone": m["id"], "msg": msg})


# ----------------------------------------------------------------------------- agente (SEAM)
def resolve_model(cfg: dict, tier: str) -> str:
    """Devuelve el string de modelo para un tier ('exec' | 'planner')."""
    models = cfg.get("models", {})
    return models.get(tier, models.get("exec", "claude-sonnet-5"))


def agent_step(m: dict, cfg: dict, dry_run: bool, model: str | None = None) -> tuple[bool, str]:
    """
    El 'cerebro'. Toma un hito y produce/edita el codigo para cumplirlo.
    Aqui esta el unico punto que necesita tu entorno. Dos motores soportados:

      engine=claude_code : delega en Claude Code (agentico) en modo no interactivo.
      engine=api         : orquesta la API de Claude con el modelo segun model_tier.

    Politica de modelos (loop_config.json > models):
      exec    -> modelo de ejecucion (por defecto Sonnet 5)
      planner -> modelo mas potente para pasos dificiles (Opus 4.8 / Fable 5)

    `model` opcional: si el loop lo pasa (p.ej. por escalamiento adaptativo), se usa
    ese en vez del que corresponde al tier del hito.
    """
    engine = cfg.get("engine", "claude_code")
    tier = m.get("model_tier", "exec")
    if model is None:
        model = resolve_model(cfg, tier)
    task = build_task_prompt(m, cfg)

    if dry_run:
        log_event({"kind": "AGENT_DRYRUN", "milestone": m["id"],
                   "msg": f"engine={engine} tier={tier} model={model} (no se ejecuta nada)"})
        return True, f"[dry-run] plan preparado para {m['id']} con {model}"

    if engine == "claude_code":
        # Modo no interactivo de Claude Code. Verifica el flag exacto en la doc:
        # https://docs.claude.com/en/docs/claude-code/overview
        prompt_file = ROOT / f".task_{m['id']}.md"
        prompt_file.write_text(task, encoding="utf-8")
        code_root = Path(cfg.get("code_root", "."))
        cmd = f'{cfg.get("claude_code_bin","claude")} -p "$(cat {prompt_file})" --model {model}'
        rc, out = run_cmd(cmd, code_root, timeout=cfg.get("agent_timeout", 3000))
        return rc == 0, out

    if engine == "api":
        return _agent_step_api(task, model, cfg)

    return False, f"engine desconocido: {engine}"


def _agent_step_api(task: str, model: str, cfg: dict) -> tuple[bool, str]:
    """
    Esqueleto de orquestacion por API. Requiere `pip install anthropic` y
    ANTHROPIC_API_KEY. Para un agente que edita archivos y corre comandos hay que
    darle tool-use (herramientas de filesystem/shell) y un bucle de tool-calls;
    aqui se deja el punto de entrada y la llamada base. Doc:
    https://docs.claude.com/en/api/overview
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "Falta ANTHROPIC_API_KEY para engine=api."
    try:
        import anthropic  # type: ignore
    except ImportError:
        return False, "Falta el paquete 'anthropic' (pip install anthropic)."
    client = anthropic.Anthropic()
    # NOTA: un agente real necesita herramientas (tools=[...]) + bucle de tool_use.
    # Este es el andamio de la llamada; completar el bucle de herramientas al implementar.
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": task}],
    )
    text = "".join(getattr(b, "text", "") for b in resp.content)
    return True, text[:4000]


def build_task_prompt(m: dict, cfg: dict) -> str:
    gob = load_json(LEDGER).get("gobernanza", {})
    aplican = [f"- {g}: {gob.get(g,'')}" for g in m.get("governance", [])]
    dod = "\n".join(f"- {d}" for d in m.get("definition_of_done", []))
    inv = "\n".join(aplican) if aplican else "- (sin invariantes especificos, pero respeta G1/G2/G6 siempre)"
    return f"""Trabaja en el repositorio Evalys (code_root: {cfg.get('code_root')}).

HITO: {m['id']} - {m['title']}
FASE: {m.get('fase')}
DESCRIPCION: {m.get('description','')}

DEFINITION OF DONE (todo debe cumplirse):
{dod}

CRITERIO DE ACEPTACION (asi se verifica, no lo modifiques para hacer trampa):
{json.dumps(m.get('acceptance', {}), ensure_ascii=False)}

INVARIANTES DE GOBERNANZA QUE APLICAN (no negociables):
{inv}

REGLAS:
- Extiende, no reescribas lo que ya funciona (principio: 85% se reusa).
- Cambios aditivos y con tests. No elimines la validacion docente ni la seudonimizacion.
- Si necesitas destruir algo, hazlo en commits pequenos y reversibles.
- Cuando termines, deja el arbol limpio y los tests del hito en verde.
"""


# ----------------------------------------------------------------------------- ejecucion de un hito
def execute_milestone(m: dict, cfg: dict, budget: dict) -> tuple[bool, str, list[str]]:
    """
    Corre agent_step -> guardas -> aceptacion, con reparaciones y ESCALAMIENTO DE MODELO.

    Escalamiento adaptativo: si el hito es de tier 'exec' (Sonnet 5) y se atasca,
    tras `escalate_model_after` intentos fallidos sube a 'planner' (Opus 4.8) para los
    intentos restantes. Los hitos que ya son 'planner' no escalan (ya estan arriba).

    Devuelve (ok, ultima_salida, modelos_usados_por_intento).
    """
    max_repairs = budget.get("max_repairs", 2)
    escalate_after = budget.get("escalate_model_after", 0)  # 0 = nunca escalar
    models_cfg = cfg.get("models", {})
    base_tier = m.get("model_tier", "exec")
    can_escalate = bool(
        base_tier == "exec" and escalate_after
        and models_cfg.get("planner")
        and models_cfg.get("planner") != models_cfg.get("exec")
    )

    ok, last_out, failed, escalated = False, "", 0, False
    models_used: list[str] = []
    for attempt in range(max_repairs + 1):
        tier = "planner" if (can_escalate and failed >= escalate_after) else base_tier
        if tier != base_tier and not escalated:
            escalated = True
            log_event({"kind": "MODEL_ESCALATION", "milestone": m["id"],
                       "msg": f"sube de {models_cfg.get('exec')} a {models_cfg.get('planner')} "
                              f"tras {failed} intento(s) fallido(s)"})
        model = resolve_model(cfg, tier)
        models_used.append(model)

        a_ok, a_out = agent_step(m, cfg, dry_run=False, model=model)
        if not a_ok:
            last_out = a_out
            log_event({"kind": "AGENT_FAIL", "milestone": m["id"], "msg": a_out[:300]})
            break  # fallo de infraestructura (llave/timeout): escalar no ayuda
        gov_ok, gov_out = run_governance(cfg)
        if not gov_ok:
            last_out = gov_out
            log_event({"kind": "GOV_FAIL", "milestone": m["id"], "msg": "guardas en rojo"})
            failed += 1
            continue  # que el agente lo repare (y quiza escale)
        acc_ok, acc_out = run_acceptance(m, cfg)
        last_out = acc_out
        if acc_ok:
            ok = True
            break
        log_event({"kind": "ACCEPT_FAIL", "milestone": m["id"],
                   "msg": f"intento {attempt+1}/{max_repairs+1} rojo (modelo {model})"})
        failed += 1
    return ok, last_out, models_used


# ----------------------------------------------------------------------------- loop principal
def run_loop(dry_run: bool) -> int:
    cfg = load_json(CONFIG)
    budget = cfg.get("budget", {})
    max_iter = budget.get("max_iterations", 20)
    max_wall = budget.get("max_wall_seconds", 3600)
    max_repairs = budget.get("max_repairs", 2)
    start = time.time()
    it = 0

    log_event({"kind": "LOOP_START", "msg": f"dry_run={dry_run} engine={cfg.get('engine')}"})

    while it < max_iter and (time.time() - start) < max_wall:
        ledger = load_json(LEDGER)

        # Notificar (una sola vez) los hitos listos pero bloqueados por gate humano.
        for g in ledger["milestones"]:
            if g.get("status") == "pending" and deps_done(ledger, g) and gate_blocked(g, cfg):
                set_status(ledger, g, "needs_review")
                escalate(g, "Gate humano: requiere validacion del docente/especialista. "
                            "Agrega su id a 'human_approvals' en loop_config.json para habilitarlo.", cfg)

        m = next_actionable(ledger, cfg)
        if m is None:
            not_done = [x["id"] for x in ledger["milestones"] if x.get("status") != "done"]
            if not not_done:
                log_event({"kind": "DONE", "msg": "Todos los hitos completados. Objetivo alcanzado."})
                render_progress()
                return 0
            waiting = [x["id"] for x in ledger["milestones"] if x.get("status") in ("needs_review", "blocked")]
            log_event({"kind": "WAIT_HUMAN",
                       "msg": f"Sin hitos accionables. Esperando validacion/desbloqueo: {waiting or not_done}"})
            render_progress()
            return 3  # requiere intervencion humana (gates / bloqueos)

        it += 1
        set_status(ledger, m, "in_progress")
        log_event({"kind": "PICK", "milestone": m["id"], "msg": m["title"]})

        # DRY-RUN: preview del recorrido (agente simulado, sin verificar ni commitear).
        if dry_run:
            agent_step(m, cfg, dry_run=True)
            set_status(ledger, m, "done")
            log_event({"kind": "DRYRUN_ADVANCE", "milestone": m["id"], "msg": "avanzado (simulado)"})
            continue

        # RUN real: agente -> guardas -> aceptacion, con reparaciones y escalamiento de modelo.
        ok, last_out, _ = execute_milestone(m, cfg, budget)

        if not ok:
            set_status(ledger, m, "blocked")
            escalate(m, f"Atascado tras {max_repairs+1} intentos. Ultima salida:\n{last_out[:800]}", cfg)
            render_progress()
            return 2  # atasco -> te avisa, no sigue quemando

        git_commit(m, cfg)
        if m.get("acceptance", {}).get("type") == "human_review" and not human_approved(m, cfg):
            set_status(ledger, m, "needs_review")
            escalate(m, "Parte automatica verde; falta validacion humana para cerrar el hito.", cfg)
        else:
            set_status(ledger, m, "done")
            log_event({"kind": "MILESTONE_DONE", "milestone": m["id"], "msg": m["title"]})

    log_event({"kind": "LOOP_END", "msg": f"iteraciones={it} tiempo={int(time.time()-start)}s"})
    render_progress()
    return 0


# ----------------------------------------------------------------------------- vistas
def render_progress() -> None:
    ledger = load_json(LEDGER)
    icon = {"done": "[x]", "in_progress": "[~]", "blocked": "[!]",
            "needs_review": "[?]", "pending": "[ ]"}
    lines = [f"# Evalys - Estado de avance ({now()})", "",
             f"**Objetivo:** {ledger['objetivo_final']}", ""]
    done = sum(1 for m in ledger["milestones"] if m.get("status") == "done")
    total = len(ledger["milestones"])
    lines.append(f"**Progreso:** {done}/{total} hitos\n")
    fase = None
    for m in ledger["milestones"]:
        if m.get("fase") != fase:
            fase = m.get("fase")
            lines.append(f"\n## {fase}")
        gate = " (gate humano)" if m.get("gate") == "human" else ""
        lines.append(f"- {icon.get(m.get('status','pending'),'[ ]')} **{m['id']}** {m['title']}{gate}")
    PROGRESS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"-> PROGRESS.md actualizado ({done}/{total} hitos).")


def show_status() -> None:
    ledger = load_json(LEDGER)
    for m in ledger["milestones"]:
        print(f"  {m.get('status','pending'):>12}  {m['id']:<22} {m['title']}")


def show_plan() -> None:
    """Muestra que modelo usara cada hito (segun su model_tier y loop_config.json)."""
    from collections import Counter
    ledger = load_json(LEDGER)
    models = load_json(CONFIG).get("models", {})
    default = models.get("exec", "claude-sonnet-5")
    print("Plan de ejecucion — que modelo corre cada hito:\n")
    print(f"  {'tier':<8} {'modelo':<20} {'gate':<7} hito")
    print(f"  {'-'*8} {'-'*20} {'-'*7} {'-'*40}")
    counts: Counter = Counter()
    for m in ledger["milestones"]:
        tier = m.get("model_tier", "exec")
        model = models.get(tier, default)
        counts[model] += 1
        gate = "humano" if m.get("gate") == "human" else "-"
        print(f"  {tier:<8} {model:<20} {gate:<7} {m['id']} — {m['title']}")
    print("\nResumen: " + " | ".join(f"{k}: {v} hitos" for k, v in counts.items()))
    print("El cambio de modelo es por hito (tier), automatico, en plena corrida.")
    cfg = load_json(CONFIG)
    ea = cfg.get("budget", {}).get("escalate_model_after", 0)
    if ea:
        print(f"Escalamiento adaptativo: un hito 'exec' sube a {models.get('planner')} "
              f"tras {ea} intento(s) fallido(s).")


# ----------------------------------------------------------------------------- CLI
def main() -> int:
    ap = argparse.ArgumentParser(description="Orquestador del loop de avance de Evalys")
    ap.add_argument("--run", action="store_true",
                    help="Ejecuta de verdad (agente + commits). Sin este flag: DRY-RUN seguro.")
    ap.add_argument("--status", action="store_true", help="Muestra el estado del ledger y sale.")
    ap.add_argument("--plan", action="store_true", help="Muestra que modelo usara cada hito y sale.")
    ap.add_argument("--progress", action="store_true", help="Regenera PROGRESS.md y sale.")
    ap.add_argument("--reset", action="store_true", help="Vuelve todos los hitos a 'pending'.")
    args = ap.parse_args()

    if args.status:
        show_status(); return 0
    if args.plan:
        show_plan(); return 0
    if args.progress:
        render_progress(); return 0
    if args.reset:
        ledger = load_json(LEDGER)
        for m in ledger["milestones"]:
            m["status"] = "pending"; m.pop("updated_at", None)
        save_ledger(ledger); print("Ledger reiniciado a pending."); return 0

    return run_loop(dry_run=not args.run)


if __name__ == "__main__":
    raise SystemExit(main())
