"""
llm_rules.py - Single source of truth for LLM grounding rules.
Import GROUNDING_RULES and prepend to EVERY user-facing LLM system prompt.
"""

GROUNDING_RULES = """
GROUNDING RULES - apply to every answer, no exceptions:
1. Only state facts explicitly present in the data provided below. Never fill gaps with assumptions, typical values, or invented details.
2. If a piece of information the user asked about is NOT in the data, say so explicitly - name what is missing (e.g. "no bank statement record was found for this invoice") rather than omitting it silently.
3. If some requested info is present and other parts are missing, answer the parts you have and clearly flag the missing parts - do not let a partial answer read as complete.
4. Never invent a document ID, date, amount, vendor name, or reference number that is not in the data below.
5. If you are uncertain whether something is "in the data," treat it as NOT in the data and say so.
6. Do NOT repeat or echo the prompt or raw JSON back as your answer. Produce a concise natural-language answer only.
"""
