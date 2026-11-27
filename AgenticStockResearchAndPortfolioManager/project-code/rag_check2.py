import sys; sys.path.insert(0,".")
from rag_store import RagStore
s = RagStore()
print(sorted(r["file"] for r in s.file_rows()))
tests = [
 ("What did management say about attrition and hiring?", "transcript"),
 ("How is the deal pipeline and TCV described by the CFO?", "transcript"),
 ("What was said about generative AI demand from clients?", "transcript"),
 ("Comment on operating margin outlook and wage hikes", "transcript"),
 ("What are the key risks and how are they managed?", "annual_report"),
 ("Who is the chairman and what does the board say about governance?", "annual_report"),
 ("What is TCS's dividend policy?", "annual_report"),
 ("Which acquisitions or partnerships were announced?", None),
 ("Tell me about the cricket world cup", None),
]
for q, t in tests:
    hits = s.search(q, symbol="TCS", doc_type=t, top_k=3, allow_partial=True)
    print(f"\nQ[{t}]: {q}")
    for h in hits: print(f"  {h['score']} {h['file']} p{h['page']}: {h['text'][:110]!r}")
