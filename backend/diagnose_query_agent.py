"""
Diagnose QueryAgent/Ollama Latency Regression
----------------------------------------------
Instruments QueryAgent sub-stages for query:
"Verify invoice 200004 against PO 100004"
"""

import json
import re
import sys
import time
from typing import Any, Dict, Optional

import httpx

# Ensure stdout handles UTF-8
sys.stdout.reconfigure(encoding='utf-8')

from app.core.config import settings
from app.core.logging import logger
from app.agents.graph import app_graph
from app.agents.query_agent import (
    _clean_answer_text,
    _filter_evidence_for_prompt,
    _format_deterministic_verification_response,
    _format_check_block,
    _filter_checks_for_query,
    _is_verification_query,
    _VERIFICATION_SYSTEM_PROMPT,
    _build_intent_system_prompt,
    _get_query_http_client,
    _CHECK_TITLES
)


def build_dynamic_context_for_verification(user_query: str, evidence: dict, verification_info: dict, bundle_id: Optional[str] = None):
    inv = evidence.get("invoice") or {}
    po = evidence.get("purchase_order") or {}
    grn = evidence.get("grn") or {}
    vendor = evidence.get("vendor_name") or inv.get("vendor_name") or po.get("vendor_name") or "N/A"

    checks = verification_info.get("checks") or []
    discrepancies = verification_info.get("discrepancies") or []
    verdict = verification_info.get("verdict")
    risk_score = float(verification_info.get("risk_score") or 0.0)
    overall_status = verification_info.get("overall_status") or ("CLEAN" if (verdict or "").lower() == "clean" else "ANOMALY")

    passed_count = sum(1 for c in checks if (c.get("status") or "").lower() == "pass")
    failed_count = sum(1 for c in checks if (c.get("status") or "").lower() == "fail")
    warning_count = sum(1 for c in checks if (c.get("status") or "").lower() == "warning")

    po_num = po.get("po_number") or inv.get("po_number") or inv.get("purchase_order") or "N/A"
    inv_num = inv.get("invoice_number") or "N/A"
    grn_num = grn.get("grn_number") or "N/A"

    inv_total_str = f"₹{float(inv.get('total_amount', 0)):,.2f}" if inv.get("total_amount") else "N/A"
    po_total_str = f"₹{float(po.get('total_amount') or po.get('subtotal', 0)):,.2f}" if (po.get("total_amount") or po.get("subtotal")) else "N/A"
    grn_total_str = f"₹{float(grn.get('total_amount', 0)):,.2f}" if grn.get("total_amount") else "N/A"

    # Prioritize checks relevant to the user query or failed checks
    detailed_checks = _filter_checks_for_query(checks, user_query)
    detailed_check_names = {(c.get("check_type") or c.get("check_name")) for c in detailed_checks}
    for c in checks:
        if (c.get("status") or "").lower() in ("fail", "warning") and (c.get("check_type") or c.get("check_name")) not in detailed_check_names:
            detailed_checks.append(c)
            detailed_check_names.add(c.get("check_type") or c.get("check_name"))

    checks_blocks = [_format_check_block(c, evidence) for c in detailed_checks]
    checks_str = "\n\n".join(checks_blocks) if checks_blocks else "All deterministic checks passed."

    other_passing = [
        _CHECK_TITLES.get((c.get("check_type") or c.get("check_name")), (c.get("check_type") or c.get("check_name")))
        for c in checks
        if (c.get("status") or "").lower() == "pass" and (c.get("check_type") or c.get("check_name")) not in detailed_check_names
    ]
    other_passing_str = f"\nOther Passing Checks ({len(other_passing)}): " + ", ".join(f"✓ {name}" for name in other_passing) if other_passing else ""

    findings = []
    seen_exps = set()
    for c in checks:
        st = (c.get("status") or "").lower()
        if st in ("fail", "warning"):
            exp = c.get("explanation") or f"Check {c.get('check_name')} resulted in {st}."
            if exp not in seen_exps:
                seen_exps.add(exp)
                sev = (c.get("severity") or "").upper()
                sev_str = f" [{sev}]" if sev else ""
                findings.append(f"- {exp}{sev_str}")

    for d in discrepancies:
        desc = d.get("description")
        if desc and desc not in seen_exps and not any(desc in f for f in findings):
            seen_exps.add(desc)
            rec = d.get("recommended_action")
            rec_str = f" Action: {rec}" if rec else ""
            findings.append(f"- {desc}{rec_str}")

    findings_str = "\n".join(findings) if findings else "No discrepancies or exceptions found. All deterministic checks passed."

    report = f"""## Deterministic Verification Findings (SOURCE OF TRUTH)
Overall Status: {overall_status} | Verdict: {verdict or overall_status} | Risk Score: {int(risk_score)}/100
Invoice: {inv_num} (Total: {inv_total_str}) | PO: {po_num} (Total: {po_total_str}) | GRN: {grn_num} (Total: {grn_total_str})
Vendor: {vendor}
Checks Summary: {passed_count} Passed, {failed_count} Failed, {warning_count} Warnings

### Relevant Comparison Checks:
{checks_str}{other_passing_str}

### Discrepancies & Findings:
{findings_str}"""

    has_issues = bool(findings) and findings_str != "No discrepancies or exceptions found. All deterministic checks passed."
    max_tokens = 350 if has_issues else 150

    return report, max_tokens


def diagnose_query_agent_run(user_query: str, run_index: int) -> Dict[str, Any]:
    print(f"\n{'='*70}")
    print(f"🔬 DIAGNOSTIC RUN #{run_index}: '{user_query}'")
    print(f"{'='*70}")

    initial_state = {
        "user_query": user_query,
        "bundle_id": None,
        "action": None,
    }
    
    from app.agents.intent_router_agent import intent_router_node
    from app.agents.search_agent import search_node
    from app.agents.verification_agent import verification_node

    state = {**initial_state}
    
    t_ir0 = time.time()
    s_ir = intent_router_node(state)
    state.update(s_ir)
    t_ir = (time.time() - t_ir0) * 1000

    t_s0 = time.time()
    s_search = search_node(state)
    state.update(s_search)
    t_search = (time.time() - t_s0) * 1000

    t_v0 = time.time()
    s_verify = verification_node(state)
    state.update(s_verify)
    t_verify = (time.time() - t_v0) * 1000

    evidence = state.get("evidence_table") or {}
    plan = state.get("retrieval_plan") or {}
    bundle_id = state.get("bundle_id")
    verification_info = {
        "verdict": state.get("verdict"),
        "severity": state.get("severity"),
        "risk_score": state.get("risk_score", 0.0),
        "checks": state.get("verification_checks", []),
        "discrepancies": state.get("discrepancies", []),
        "verification_run_id": state.get("verification_run_id"),
    }

    t_prep0 = time.time()
    is_verif = _is_verification_query(user_query, plan, verification_info)
    
    if is_verif:
        deterministic_verif_report, max_tokens = build_dynamic_context_for_verification(
            user_query, evidence, verification_info, bundle_id
        )
        system_prompt = _VERIFICATION_SYSTEM_PROMPT
        user_prompt = (
            f"User question: {json.dumps(user_query)}\n\n"
            f"Authoritative Deterministic Verification Results (SOURCE OF TRUTH):\n{deterministic_verif_report}\n\n"
            f"Provide a complete, factually grounded answer directly answering the question using only the verified evidence above. "
            f"Include relevant amounts (₹), dates, document references, and check/discrepancy findings where applicable. "
            f"If no failure reason or discrepancy exists in the retrieved evidence, state that clearly and do not invent any reasons."
        )
    else:
        filtered_evidence = _filter_evidence_for_prompt(user_query, evidence, plan)
        evidence_json = json.dumps(filtered_evidence, indent=2)
        intent = plan.get("intent", "lookup") if plan else "lookup"
        system_prompt = _build_intent_system_prompt(intent)
        user_prompt = (
            f"User question: {json.dumps(user_query)}\n\n"
            f"Evidence Table:\n{evidence_json}\n\n"
            f"Provide a complete, factually grounded answer directly answering the question using only the verified evidence above. "
            f"State exact document numbers, values in ₹ (with subtotal and tax breakdown if available), dates, and vendor names."
        )
        max_tokens = 150

    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    prompt_char_count = len(full_prompt)
    t_prep = (time.time() - t_prep0) * 1000

    ollama_model = settings.OLLAMA_MODEL or "qwen2.5:3b"
    payload = {
        "model": ollama_model,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.1,
            "num_ctx": 4096,
        },
    }

    t_http0 = time.time()
    client = _get_query_http_client()
    res = client.post(f"{settings.OLLAMA_HOST}/api/generate", json=payload)
    t_http_total = (time.time() - t_http0) * 1000
    
    res_data = res.json() if res.status_code == 200 else {}
    raw_response = res_data.get("response", "").strip()

    total_duration_ns = res_data.get("total_duration", 0)
    load_duration_ns = res_data.get("load_duration", 0)
    prompt_eval_count = res_data.get("prompt_eval_count", 0)
    prompt_eval_duration_ns = res_data.get("prompt_eval_duration", 0)
    eval_count = res_data.get("eval_count", 0)
    eval_duration_ns = res_data.get("eval_duration", 0)

    load_duration_ms = load_duration_ns / 1e6
    prompt_eval_duration_ms = prompt_eval_duration_ns / 1e6
    eval_duration_ms = eval_duration_ns / 1e6
    ollama_total_ms = total_duration_ns / 1e6
    http_overhead_ms = max(0, t_http_total - ollama_total_ms)

    t_parse0 = time.time()
    cleaned_answer = _clean_answer_text(raw_response)
    t_parse = (time.time() - t_parse0) * 1000

    query_agent_total_ms = t_prep + t_http_total + t_parse
    tokens_per_sec = (eval_count / (eval_duration_ns / 1e9)) if eval_duration_ns > 0 else 0

    print(f"\nQueryAgent Sub-Stage Breakdown:")
    print(f"  1. Dynamic context prep       : {t_prep:>8.2f} ms")
    print(f"  2. HTTP connection & overhead  : {http_overhead_ms:>8.2f} ms")
    print(f"  3. Ollama model load (warmth)  : {load_duration_ms:>8.2f} ms ({'WARM' if load_duration_ms < 500 else 'COLD LOAD'})")
    print(f"  4a. Prompt evaluation (TTFT)   : {prompt_eval_duration_ms:>8.2f} ms ({prompt_eval_count} prompt tokens)")
    print(f"  4b. Token generation time      : {eval_duration_ms:>8.2f} ms ({eval_count} response tokens @ {tokens_per_sec:.2f} tok/s)")
    print(f"  5. Response post-processing    : {t_parse:>8.2f} ms")
    print(f"  ------------------------------------------------")
    print(f"  ⏱️  QueryAgent Total Latency   : {query_agent_total_ms:>8.2f} ms ({query_agent_total_ms/1000:.2f}s)")
    print(f"\nConfiguration & Diagnostics:")
    print(f"  • Prompt Char Count : {prompt_char_count} chars")
    print(f"  • Prompt Token Count: {prompt_eval_count} tokens")
    print(f"  • Resp Token Count  : {eval_count} tokens")
    print(f"  • Model Status      : {'WARM' if load_duration_ms < 500 else 'COLD LOAD'}")
    print(f"\nGenerated Answer:")
    print(f"  {cleaned_answer}\n")

    return {
        "run_index": run_index,
        "prep_ms": t_prep,
        "http_overhead_ms": http_overhead_ms,
        "load_ms": load_duration_ms,
        "prompt_eval_ms": prompt_eval_duration_ms,
        "eval_ms": eval_duration_ms,
        "parse_ms": t_parse,
        "query_agent_total_ms": query_agent_total_ms,
        "prompt_chars": prompt_char_count,
        "prompt_tokens": prompt_eval_count,
        "resp_tokens": eval_count,
        "tokens_per_sec": tokens_per_sec,
        "answer": cleaned_answer,
    }


def main():
    query = "Verify invoice 200004 against PO 100004"
    results = []
    for r in range(1, 4):
        res = diagnose_query_agent_run(query, r)
        results.append(res)
        time.sleep(1)

    print(f"\n{'='*70}")
    print("📊 3-RUN SUMMARY TABLE (DYNAMIC CONTEXT - ZERO REDUNDANCY)")
    print(f"{'='*70}")
    print(f"{'Run':<5} | {'Prep (ms)':<10} | {'Load(ms)':<10} | {'PromptEval':<12} | {'Eval Gen(ms)':<12} | {'Resp Tok':<9} | {'Tok/s':<8} | {'Total QueryAgent'}")
    print("-" * 95)
    for r in results:
        print(f"#{r['run_index']:<4} | {r['prep_ms']:<10.2f} | {r['load_ms']:<10.2f} | {r['prompt_eval_ms']:<12.2f} | {r['eval_ms']:<12.2f} | {r['resp_tokens']:<9} | {r['tokens_per_sec']:<8.2f} | {r['query_agent_total_ms']:<8.2f} ms ({r['query_agent_total_ms']/1000:.2f}s)")
    print("=" * 95)


if __name__ == "__main__":
    main()
