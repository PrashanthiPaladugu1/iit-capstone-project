import sys; sys.path.insert(0,".")
from rag_store import RagStore
s = RagStore()
print(s.status())
for q, kw in [("What are the main risks management highlighted?", {"doc_type":"annual_report"}),
              ("Did management comment on deal wins and demand outlook?", {"doc_type":"transcript"}),
              ("attrition rate employees", {})]:
    print("\nQ:", q)
    for h in s.search(q, symbol="TCS", top_k=3, allow_partial=True, **kw):
        print(f"  {h['score']} {h['file']} p{h['page']}: {h['text'][:150]!r}")
