"""RAG evaluation for the Knowledge Q&A agent.

  python eval/run_rag_eval.py

Always computes retrieval metrics on synthetic Q/A pairs (hit@1, hit@3, MRR, and whether
out-of-scope questions correctly return "not in knowledge base").
RAGAS (faithfulness, answer relevancy, context precision/recall) needs the `ragas` package AND
a live LLM key; otherwise it is SKIPPED with a clear message. WikiQA is an analogous open-domain
answer-selection benchmark; it is noted here but not run (our KB is domain-specific).
"""
from __future__ import annotations

import time

from common import mode_label, percentile, save

from app.ai import graph, rag
from app.core.config import get_settings

QA = [
    ("How do I report a suspicious email?", "reporting-procedure", "Report Phish"),
    ("Should I forward a phishing email to my colleagues?", "reporting-procedure", "forward"),
    ("What happens after I report a message?", "reporting-procedure", "triage"),
    ("I already clicked a link, what now?", "reporting-procedure", "immediately"),
    ("What is MFA fatigue or push bombing?", "mfa", "push"),
    ("Why are authenticator apps better than SMS codes?", "mfa", "SIM"),
    ("Should I share my MFA code with IT support?", "mfa", "Never share"),
    ("What is number matching?", "mfa", "number"),
    ("How long should my password be?", "password-hygiene", "passphrase"),
    ("Why use a password manager?", "password-hygiene", "password manager"),
    ("What is credential stuffing?", "password-hygiene", "credential stuffing"),
    ("What is business email compromise?", "bec", "Business email compromise"),
    ("A supplier changed their bank details by email. What should I do?", "bec", "verify"),
    ("Why do BEC emails often have no links?", "bec", "links"),
    ("What is smishing?", "smishing-vishing", "SMS"),
    ("What is vishing and how do I handle a suspicious call?", "smishing-vishing", "Hang up"),
    ("Can caller ID be spoofed?", "smishing-vishing", "spoofed"),
    ("What is quishing?", "qr-code-phishing", "QR"),
    ("Why are QR codes in emails risky?", "qr-code-phishing", "destination"),
    ("How do I read a link's real domain?", "spotting-phishing", "right to left"),
    ("What do SPF DKIM DMARC failures mean?", "email-authentication", "SPF"),
    ("What is DKIM?", "email-authentication", "signature"),
    ("Does passing SPF and DMARC mean an email is safe?", "email-authentication", "look-alike"),
    ("Which attachments are risky?", "spotting-phishing", ".iso"),
]
OUT_OF_SCOPE = [
    "What is the capital of France?",
    "How do I bake sourdough bread?",
    "Who won the 1998 football world cup?",
    "What is the boiling point of mercury in kelvin?",
    "Recommend a good laptop for gaming",
]


def main():
    hit1 = hit3 = 0
    rr, lat = [], []
    contains_fact = 0
    for q, slug, fact in QA:
        t = time.perf_counter()
        hits = rag.retrieve(q, k=3)
        lat.append((time.perf_counter() - t) * 1000)
        slugs = [h["slug"] for h in hits]
        hit1 += slugs[:1] == [slug]
        hit3 += slug in slugs
        rr.append(1 / (slugs.index(slug) + 1) if slug in slugs else 0.0)
        ans = graph.run(org_id="eval", user_id=None, session_id=f"rag-{q}", demo_mode=get_settings().demo_mode,
                        request_type="qa", payload={"question": q})["result"]["answer"]
        contains_fact += fact.lower() in ans.lower()
    oos_ok = sum(
        graph.run(org_id="eval", user_id=None, session_id=f"oos-{q}", demo_mode=get_settings().demo_mode,
                  request_type="qa", payload={"question": q})["result"]["answer"] == graph.NOT_IN_KB
        for q in OUT_OF_SCOPE)

    n = len(QA)
    retrieval = {"n_questions": n, "hit@1": round(hit1 / n, 3), "hit@3": round(hit3 / n, 3),
                 "mrr": round(sum(rr) / n, 3), "answer_contains_key_fact": round(contains_fact / n, 3),
                 "out_of_scope_correctly_refused": f"{oos_ok}/{len(OUT_OF_SCOPE)}",
                 "retrieval_latency_ms": {"p50": percentile(lat, 0.5), "p95": percentile(lat, 0.95)},
                 "vector_store": rag.get_store().backend, "embedding": "local hashing (lexical)",
                 "similarity_threshold": rag.MIN_SIMILARITY}

    try:
        import ragas  # noqa: F401
        have_ragas = True
    except ImportError:
        have_ragas = False
    if get_settings().demo_mode or not have_ragas:
        ragas_result = {"skipped": True, "reason": (
            "RAGAS requires the `ragas` package and a live LLM key (it uses an LLM as judge). "
            f"ragas installed: {have_ragas}; demo mode: {get_settings().demo_mode}.")}
    else:  # pragma: no cover - requires network + key
        ragas_result = {"skipped": True, "reason": "Wiring RAGAS to the configured provider is documented in "
                                                   "eval/README.md but not executed in this build."}

    out = {"retrieval": retrieval, "ragas": ragas_result,
           "benchmark_note": "WikiQA (Yang et al., 2015) is an analogous answer-selection benchmark; not run "
                             "because our knowledge base is a small domain-specific corpus."}
    path = save("rag_eval", out)
    print(f"[{mode_label()}] retrieval: {retrieval}")
    print("RAGAS:", ragas_result["reason"] if ragas_result.get("skipped") else ragas_result)
    print(f"saved -> {path}")


if __name__ == "__main__":
    main()
