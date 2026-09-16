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
    _is_verification_query,
    _VERIFICATION_SYSTEM_PROMPT,
    _build_intent_system_prompt,
    _get_query_http_client
)


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

    print(f"Upstream Stages:")
    print(f"  • intent_router : {t_ir:.2f} ms")
    print(f"  • search        : {t_search:.2f} ms")
    print(f"  • verify        : {t_verify:.2f} ms")

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

    # ── Stage 1: Evidence & Context Preparation ──
    t_prep0 = time.time()
    is_verif = _is_verification_query(user_query, plan, verification_info)
    deterministic_verif_report = ""
    if is_verif and verification_info:
        deterministic_verif_report = _format_deterministic_verification_response(
            evidence, verification_info, bundle_id, user_query
        )
    filtered_evidence = _filter_evidence_for_prompt(user_query, evidence, plan)
    evidence_json = json.dumps(filtered_evidence, indent=2)
    t_prep = (time.time() - t_prep0) * 1000

    # ── Stage 2: Prompt Construction ──
    t_prompt0 = time.time()
    if is_verif and deterministic_verif_report:
        system_prompt = _VERIFICATION_SYSTEM_PROMPT
        user_prompt = (
            f"User question: {json.dumps(user_query)}\n\n"
            f"Authoritative Deterministic Verification Results (SOURCE OF TRUTH):\n{deterministic_verif_report}\n\n"
            f"Evidence Documents Table:\n{evidence_json}\n\n"
            f"Provide a complete, factually grounded answer directly answering the question using only the verified evidence above. "
            f"Include relevant amounts (₹), dates, document references, and check/discrepancy findings where applicable. "
            f"If no failure reason or discrepancy exists in the retrieved evidence, state that clearly and do not invent any reasons."
        )
        max_tokens = 350
    else:
        intent = plan.get("intent", "lookup") if plan else "lookup"
        system_prompt = _build_intent_system_prompt(intent)
        user_prompt = (
            f"User question: {json.dumps(user_query)}\n\n"
            f"Evidence Table:\n{evidence_json}\n\n"
            f"Provide a complete, factually grounded answer directly answering the question using only the verified evidence above. "
            f"State exact document numbers, values in ₹ (with subtotal and tax breakdown if available), dates, and vendor names."
        )
        max_tokens = 250

    full_prompt = f"{system_prompt}\n\n{user_prompt}"
    prompt_char_count = len(full_prompt)
    t_prompt = (time.time() - t_prompt0) * 1000

    # ── Stage 3, 4, 5: Ollama Connection, TTFT / Generation ──
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

    # Ollama internal timing breakdown (in nanoseconds from Ollama server)
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

    # ── Stage 6: Response Parsing & Post-Processing ──
    t_parse0 = time.time()
    cleaned_answer = _clean_answer_text(raw_response)
    t_parse = (time.time() - t_parse0) * 1000

    query_agent_total_ms = t_prep + t_prompt + t_http_total + t_parse
    tokens_per_sec = (eval_count / (eval_duration_ns / 1e9)) if eval_duration_ns > 0 else 0

    print(f"\nQueryAgent Sub-Stage Breakdown:")
    print(f"  1. Evidence/context prep      : {t_prep:>8.2f} ms")
    print(f"  2. Prompt construction         : {t_prompt:>8.2f} ms")
    print(f"  3. HTTP connection & overhead  : {http_overhead_ms:>8.2f} ms")
    print(f"  4. Ollama model load (warmth)  : {load_duration_ms:>8.2f} ms ({'WARM' if load_duration_ms < 500 else 'COLD LOAD'})")
    print(f"  5a. Prompt evaluation (TTFT)   : {prompt_eval_duration_ms:>8.2f} ms ({prompt_eval_count} prompt tokens)")
    print(f"  5b. Token generation time      : {eval_duration_ms:>8.2f} ms ({eval_count} response tokens @ {tokens_per_sec:.2f} tok/s)")
    print(f"  6. Response post-processing    : {t_parse:>8.2f} ms")
    print(f"  ------------------------------------------------")
    print(f"  ⏱️  QueryAgent Total Latency   : {query_agent_total_ms:>8.2f} ms ({query_agent_total_ms/1000:.2f}s)")
    print(f"\nConfiguration & Diagnostics:")
    print(f"  • Model Name        : {ollama_model}")
    print(f"  • num_predict       : {max_tokens}")
    print(f"  • num_ctx           : 4096")
    print(f"  • temperature       : 0.1")
    print(f"  • Prompt Char Count : {prompt_char_count} chars")
    print(f"  • Prompt Token Count: {prompt_eval_count} tokens")
    print(f"  • Resp Token Count  : {eval_count} tokens")
    print(f"  • Client Timeout    : {client.timeout.read}s")
    print(f"  • Model Status      : {'WARM' if load_duration_ms < 500 else 'COLD LOAD'}")
    print(f"\nGenerated Answer Sample (first 150 chars):")
    print(f"  {cleaned_answer[:150]}...")

    return {
        "run_index": run_index,
        "prep_ms": t_prep,
        "prompt_ms": t_prompt,
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
        "model": ollama_model,
        "num_predict": max_tokens,
        "num_ctx": 4096,
        "temperature": 0.1,
    }


def main():
    query = "Verify invoice 200004 against PO 100004"
    results = []
    for r in range(1, 4):
        res = diagnose_query_agent_run(query, r)
        results.append(res)
        time.sleep(1)

    print(f"\n{'='*70}")
    print("📊 3-RUN SUMMARY TABLE")
    print(f"{'='*70}")
    print(f"{'Run':<5} | {'Prep (ms)':<10} | {'Prompt(ms)':<10} | {'Load(ms)':<10} | {'PromptEval':<12} | {'Eval Gen(ms)':<12} | {'Resp Tok':<9} | {'Tok/s':<8} | {'Total QueryAgent'}")
    print("-" * 105)
    for r in results:
        print(f"#{r['run_index']:<4} | {r['prep_ms']:<10.2f} | {r['prompt_ms']:<10.2f} | {r['load_ms']:<10.2f} | {r['prompt_eval_ms']:<12.2f} | {r['eval_ms']:<12.2f} | {r['resp_tokens']:<9} | {r['tokens_per_sec']:<8.2f} | {r['query_agent_total_ms']:<8.2f} ms ({r['query_agent_total_ms']/1000:.2f}s)")
    print("=" * 105)


if __name__ == "__main__":
    main()
