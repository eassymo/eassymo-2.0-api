"""Validation loop for the WhatsApp bot's understanding of sloppy messages.

Runs each message of tests/whatsapp_messy_corpus.py through the SAME code the bot uses after
the webhook: model extraction -> catalog mapping of parts and vehicle -> the questions the
seller would be asked. Nothing is sent or stored. Prints a scorecard: the number that matters is
FAIL (confidently wrong); ASK is a miss that at least asks instead of guessing.

    python scripts/whatsapp_validation_loop.py [--set tuning|holdout|fresh|all] [--refresh-llm] [--only ID ...] [-v] [--workers 4]

Model replies are cached by (prompt, message) so tuning the mapper does not re-call the model;
pass --refresh-llm after changing the prompt or to re-measure the model itself.
"""
import argparse
import hashlib
import json
import os
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.database import get_mysql_db  # noqa: E402
from app.schemas.WhatsappExtraction import WhatsappExtractionProposal  # noqa: E402
from app.services import WhatsappClarificationService as clarify  # noqa: E402
from app.services import LlmExtractionService as llm_module  # noqa: E402
from app.services.WhatsappIntakeProcessorService import WhatsappIntakeProcessorService  # noqa: E402
from tests.whatsapp_messy_corpus import CASES, FRESH, HOLDOUT  # noqa: E402

CACHE_DIR = os.environ.get("VALIDATION_CACHE_DIR", "/tmp/wa_val_cache")


def fold(text):
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").strip()


def _cache_key(text):
    prompt = llm_module.SYSTEM_PROMPT + llm_module.USER_PROMPT_TEMPLATE
    return hashlib.sha256((prompt + "\n" + text).encode()).hexdigest()[:24]


def extract(llm, text, refresh):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, _cache_key(text) + ".json")
    if not refresh and os.path.exists(path):
        return WhatsappExtractionProposal.model_validate(json.load(open(path)))
    proposal = llm.extract([text], store_name="Refaccionaria Demo")
    json.dump(proposal.model_dump(mode="json"), open(path, "w"), ensure_ascii=False)
    return proposal


def resolve(proc, db, proposal, text):
    """Mirror of WhatsappIntakeProcessorService._create_draft_from_proposal, minus I/O."""
    pieces = proc._lines_to_pieces(db, proposal)
    resolved, status = proc._map_catalog_vehicle(db, proposal, [text])
    proc._apply_resolved_vehicle(proposal, resolved, status)
    vehicle = proc._vehicle_from_proposal(proposal) or {}
    folio = {"vehicle": vehicle, "pieces": pieces}
    questions = clarify.derive_pending_questions(folio, proposal)
    return status, vehicle, pieces, questions


def judge_vehicle(expected, status, vehicle, questions):
    maker, model, year = fold(vehicle.get("maker")), fold(vehicle.get("model")), str(vehicle.get("year") or "")
    confident = status in ("matched", "corrected")
    suggestion = next(
        (q.get("suggestion") for q in questions
         if (q.get("path") or "").startswith("vehicle") and (q.get("suggestion") or {}).get("make")),
        None,
    )

    if expected is None:
        if confident:
            return "WRONG", f"matched {vehicle.get('maker')} {vehicle.get('model')} but no car was named"
        if suggestion:
            return "ASK", f"suggested {suggestion} for a message with no car"
        return "OK", ""
    e_make, e_model, e_year = expected
    if e_year is None and year:
        return "WRONG", f"invented year {year}"
    if confident or status == "unchecked":
        make_ok = fold(e_make) in maker if maker else False
        model_ok = (e_model is None and (not model or status == "unchecked")) or (e_model is not None and model and fold(e_model) in model)
        if confident and e_model is None and model:
            return "WRONG", f"invented model {vehicle.get('model')}"
        if confident and (not make_ok or not model_ok):
            return "WRONG", f"matched {vehicle.get('maker')} {vehicle.get('model')}, wanted {e_make} {e_model}"
        if confident:
            return "OK", ""
    if suggestion:
        s = fold(f"{suggestion.get('make', '')} {suggestion.get('model', '')}")
        if fold(e_make) in s and (e_model is None or fold(e_model) in s):
            return "CONFIRM", f"suggests {suggestion}"
        return "WRONG", f"suggested {suggestion}, wanted {e_make} {e_model}"
    if e_year is None and status == "unchecked" and fold(e_make) in maker and (e_model is None or fold(e_model) in model) \
            and any((q.get("path") or "") == "vehicle.year" for q in questions):
        return "OK", ""  # kept the car and asked for the year instead of guessing it
    if e_model is None:
        return ("OK", "") if not model or status != "matched" else ("WRONG", "")
    # Not resolved by the catalog: acceptable only when the seller is asked (a question exists)
    if any((q.get("path") or "").startswith("vehicle") for q in questions) or status in ("unrecognized", "ambiguous", "unchecked"):
        return "ASK", f"status={status}"
    return "ASK", f"status={status}"


def judge_parts(expected, pieces):
    results = []
    used = set()
    resolved = [
        (i, fold(p.get("tipoParteDescripcion")) if p.get("tipoParteId") else None,
         [fold(c.get("tipoParteDescripcion")) for c in (p.get("catalog_suggestions") or [])])
        for i, p in enumerate(pieces)
    ]
    for exp in expected:
        if exp is None:
            bad = [i for i, r, _ in resolved if r]
            if bad:
                results.append(("WRONG", f"resolved a vague/nonsense part to {pieces[bad[0]].get('tipoParteDescripcion')}"))
                used.update(bad)
            else:
                results.append(("OK", ""))
            continue
        accept = {fold(x) for x in (exp if isinstance(exp, tuple) else (exp,))}
        hit = next(((i, "OK") for i, r, _ in resolved if r in accept and i not in used), None) \
            or next(((i, "CONFIRM") for i, _, s in resolved if set(s) & accept and i not in used), None)
        if hit:
            used.add(hit[0])
            results.append((hit[1], ""))
        else:
            results.append(("ASK", f"expected {sorted(accept)}; got {[p.get('tipoParteDescripcion') or p.get('name') for p in pieces]}"))
    extras = [i for i, r, _ in resolved if r and i not in used]
    if not expected and extras:
        results.append(("WRONG", f"invented part {pieces[extras[0]].get('tipoParteDescripcion')} from a message with no parts"))
    elif extras:
        results.append(("WRONG", f"extra part {pieces[extras[0]].get('tipoParteDescripcion')}"))
    if not expected and pieces and not extras:
        results.append(("ASK", f"invented free-text line {[p.get('name') for p in pieces]}"))
    return results


def run_case(case, proc, llm, refresh):
    db = next(get_mysql_db())
    try:
        proposal = extract(llm, case["text"], refresh)
        raw_vehicle = proposal.vehicle.model_dump() if proposal.vehicle else None
        raw_lines = [l.part_name for l in proposal.lines]
        status, vehicle, pieces, questions = resolve(proc, db, proposal, case["text"])
    finally:
        db.close()
    v_verdict, v_note = judge_vehicle(case["vehicle"], status, vehicle, questions)
    p_results = judge_parts(case["parts"], pieces)
    verdicts = [v_verdict] + [r for r, _ in p_results]
    final = "FAIL" if "WRONG" in verdicts else ("ASK" if "ASK" in verdicts else "PASS")
    notes = [n for n in [v_note] + [n for _, n in p_results] if n]
    return dict(id=case["id"], text=case["text"], final=final, verdicts=verdicts, notes=notes,
                status=status, vehicle=vehicle, raw_vehicle=raw_vehicle, raw_lines=raw_lines,
                pieces=[(p.get("name"), p.get("tipoParteDescripcion"), p.get("position")) for p in pieces],
                questions=[(q.get("severity"), q.get("copy_text")) for q in questions])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-llm", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--set", choices=["tuning", "holdout", "fresh", "all"], default="all")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    proc = WhatsappIntakeProcessorService()
    llm = proc.llm_service
    if not llm.enabled:
        sys.exit("Z_AI_API_KEY is not configured: cannot run the live model")
    pool_cases = {"tuning": CASES, "holdout": HOLDOUT, "fresh": FRESH, "all": CASES + HOLDOUT + FRESH}[args.set]
    cases = [c for c in pool_cases if not args.only or c["id"] in args.only]

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda c: run_case(c, proc, llm, args.refresh_llm), cases))

    counts = {"PASS": 0, "ASK": 0, "FAIL": 0}
    for r in results:
        counts[r["final"]] += 1
        if args.verbose or r["final"] != "PASS":
            print(f"\n[{r['final']}] {r['id']}: {r['text']!r}")
            for n in r["notes"]:
                print(f"    - {n}")
            print(f"    model: vehicle={r['raw_vehicle']} lines={r['raw_lines']}")
            print(f"    bot:   status={r['status']} vehicle={r['vehicle'].get('maker')}/{r['vehicle'].get('model')}/{r['vehicle'].get('year')} pieces={r['pieces']}")
            print(f"    asks:  {r['questions']}")
    total = len(results)
    print("\n" + "=" * 64)
    print(f"cases={total}  PASS={counts['PASS']} ({counts['PASS']*100//total}%)  ASK={counts['ASK']}  FAIL(confidently wrong)={counts['FAIL']}")
    json.dump(results, open(os.path.join(CACHE_DIR, "last_run.json"), "w"), ensure_ascii=False, default=str, indent=1)
    sys.exit(1 if counts["FAIL"] else 0)


if __name__ == "__main__":
    main()
