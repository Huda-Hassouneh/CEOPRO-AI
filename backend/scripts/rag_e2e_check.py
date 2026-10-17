"""
KEEL - the assistant end to end through the running API, the way the frontend
uses it: sign in, upload documents (POST /extraction/upload -> object storage
-> chunking -> embeddings stored in rag_document_chunks), then ask questions
(POST /rag/query) and check what comes back.
Checks, each against the live API and its database:
- every uploaded PDF is Processed, and its chunks carry a vector from the
  configured embedding model;
- an Arabic question about each English document, sharing no word with it,
  gets that document cited first (semantic retrieval; keyword search can't);
- a company-data question cites the company's own records;
- another company, with the same supplier text in a file of its own, asking
  the same question
  gets an answer citing its own document and never the first company's -
  in its answer or its document list (tenant isolation);
- with an LLM provider configured (llm_client.active_provider()), the answers
  are written by it - an evidence-mode fallback fails the check; without one,
  the assistant's evidence mode still returns the cited sources.
- with --api-pid, the API process's peak memory (VmHWM) stays under
  --max-peak-mb.

    python -m scripts.rag_e2e_check --api http://localhost:8000 --email ... --password ... [--api-pid N]
"""
import argparse
import io
import os
import sys
import time
import uuid
from dataclasses import replace

from scripts.demo_companies.profiles import COMPANIES
from scripts.demo_companies.seed import Client, sign_in
from scripts.rag_runtime_check import ARABIC_QUESTIONS, DOCUMENTS


def _pdf(text: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    page = canvas.Canvas(buffer, pagesize=A4)
    y = 800
    line = ""
    for word in text.split():
        if len(line) + len(word) > 85:
            page.drawString(50, y, line)
            y, line = y - 16, ""
        line = f"{line} {word}".strip()
    page.drawString(50, y, line)
    page.save()
    return buffer.getvalue()


def _peak_mb(pid: int) -> float:
    with open(f"/proc/{pid}/status") as status:
        for line in status:
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
    return 0.0


def _ask(client: Client, question: str) -> dict:
    started = time.monotonic()
    response = client.http.post("/rag/query", params={"query_text": question}, headers=client.headers)
    elapsed = time.monotonic() - started
    if response.status_code != 200:
        return {"status": response.status_code, "reason": response.headers.get("X-Assistant-Reason"),
                "detail": response.text[:300], "seconds": elapsed}
    body = response.json()
    return {"status": 200, "mode": body.get("answer_mode"), "answer": body.get("answer", ""),
            "titles": [r.get("title") for r in body.get("references") or []], "seconds": elapsed}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--company", default="zaytouna")
    parser.add_argument("--api-pid", type=int)
    parser.add_argument("--max-peak-mb", type=float, default=512)
    args = parser.parse_args()
    failures = []
    company = next(c for c in COMPANIES if c.key == args.company)
    client = Client(args.api)
    sign_in(client, company, args.email, args.password)

    run = uuid.uuid4().hex[:6]
    names = {}
    for name, text in DOCUMENTS.items():
        file_name = f"{name[:-4]}_{run}.pdf"
        names[name] = file_name
        started = time.monotonic()
        data = client.request("POST", "/extraction/upload", files={"file": (file_name, _pdf(text), "application/pdf")})
        status = data.get("rag_document_status")
        print(f"upload {file_name}: {status} in {time.monotonic() - started:.1f}s")
        if status != "Processed":
            failures.append(f"{file_name} was not processed ({status})")

    listed = {d.get("file_name") for d in client.request("GET", "/rag/documents").get("documents") or []}
    if not set(names.values()) <= listed:
        failures.append(f"the document list is missing {sorted(set(names.values()) - listed)}")

    model = None
    if os.getenv("DATABASE_URL"):
        import psycopg2

        with psycopg2.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cursor:
            cursor.execute(
                """SELECT m.file_name, count(c.chunk_id), count(c.embedding), max(c.embedding_model_version)
                   FROM rag_documents_metadata m LEFT JOIN rag_document_chunks c
                     ON c.tenant_id = m.tenant_id AND c.document_id = m.document_id
                   WHERE m.file_name = ANY(%s) GROUP BY m.file_name ORDER BY m.file_name;""",
                (list(names.values()),),
            )
            for file_name, chunks, vectors, version in cursor.fetchall():
                model = version
                print(f"  {file_name}: {chunks} chunk(s), {vectors} with a vector ({version})")
                if not chunks or vectors != chunks:
                    failures.append(f"{file_name}: {vectors}/{chunks} chunks have a vector")

    print()
    from src.ai.rag import llm_client

    # The API runs with this script's environment in CI: with a provider
    # configured, answers must be written by it, not fall back to evidence mode.
    llm = llm_client.active_provider() if llm_client.provider_configured() else None
    print(f"LLM provider: {llm or 'none configured (answers in evidence mode)'}")
    modes = []
    right = 0
    for doc, question in ARABIC_QUESTIONS.items():
        result = _ask(client, question)
        if result["status"] != 200:
            failures.append(f"/rag/query answered {result['status']} ({result.get('reason')}): {result.get('detail')}")
            print(f"{question}: HTTP {result['status']} {result.get('reason')}")
            continue
        documents = [t for t in result["titles"] if str(t).endswith(f"_{run}.pdf")]
        first = documents[0] if documents else None
        right += first == names[doc]
        modes.append(result["mode"])
        print(f"{question}\n  mode={result['mode']} {result['seconds']:.1f}s, first document cited: {first} "
              f"({'right' if first == names[doc] else 'WRONG'}), all references: {result['titles']}")
        print("  answer:", result["answer"][:300].replace("\n", " "))
    print(f"{right}/{len(ARABIC_QUESTIONS)} Arabic questions cited their English document first")
    if right < len(ARABIC_QUESTIONS) - 1:
        failures.append(f"only {right}/{len(ARABIC_QUESTIONS)} Arabic questions cited the right document first")

    if llm and "evidence" in modes:
        failures.append(f"{llm} is configured but {modes.count('evidence')} answer(s) fell back to evidence mode "
                        "(the provider call failed - see the API log)")

    company_question = _ask(client, "Which products are most profitable?")
    print(f"\nWhich products are most profitable?\n  mode={company_question.get('mode')}, "
          f"references: {company_question.get('titles')}\n  answer: {company_question.get('answer', '')[:300]}")
    if company_question["status"] != 200 or not company_question["titles"]:
        failures.append("the company-data question came back without cited records")

    other = Client(args.api)
    other_company = replace(company, business_name=f"Isolation Check {run}", owner_name="Isolation Check")
    sign_in(other, other_company, f"isolation-{run}@keel-ci.example", args.password)
    # The same supplier text under its own file name: the question then has
    # evidence in this company too (answered, not refused), and the first
    # company's identical document is the one that must not show up.
    own = f"isolation_supplier_{run}.pdf"
    data = other.request("POST", "/extraction/upload", files={"file": (
        own, _pdf(DOCUMENTS["supplier_agreement.txt"]), "application/pdf")})
    if data.get("rag_document_status") != "Processed":
        failures.append(f"tenant isolation: the other company's {own} was not processed")
    ours = set(names.values())
    listed = [d.get("file_name") for d in other.request("GET", "/rag/documents").get("documents") or []]
    print(f"\nAnother company's document list: {listed}")
    if ours & set(listed):
        failures.append(f"tenant isolation: another company's document list shows {sorted(ours & set(listed))}")
    leaked = _ask(other, ARABIC_QUESTIONS["supplier_agreement.txt"])
    print(f"Another company asking the supplier question: HTTP {leaked['status']}, references {leaked.get('titles')}")
    if leaked["status"] != 200:
        failures.append(f"tenant isolation: the other company's question answered {leaked['status']} "
                        f"({leaked.get('reason')}), so the check proved nothing")
    elif ours & set(leaked["titles"]):
        failures.append(f"tenant isolation: another company was shown {sorted(ours & set(leaked['titles']))}")
    elif own not in leaked["titles"]:
        failures.append(f"tenant isolation: the other company's own {own} wasn't cited ({leaked['titles']})")

    if args.api_pid:
        peak = _peak_mb(args.api_pid)
        print(f"\nAPI process peak memory: {peak:.0f} MB (limit {args.max_peak_mb:.0f})")
        if peak > args.max_peak_mb:
            failures.append(f"API process peak memory {peak:.0f} MB is over {args.max_peak_mb:.0f} MB")
    print(f"Embedding model on stored vectors: {model}")
    if failures:
        print("\nFAIL:\n- " + "\n- ".join(failures))
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
