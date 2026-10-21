import asyncio
import math

import pytest

from hiveops import rag
from hiveops.config import EMBED_DIM
from hiveops.db import Database
from hiveops.seed import DATA


def test_embeddings_are_deterministic_and_normalised():
    a = rag.embed("Expenses above $5,000 need the Finance Director")
    assert a == rag.embed("Expenses above $5,000 need the Finance Director")
    assert len(a) == EMBED_DIM
    assert math.isclose(math.sqrt(sum(x * x for x in a)), 1.0, rel_tol=1e-9)


def test_similar_text_scores_higher_than_unrelated_text():
    q = rag.embed("hotel limit per night in London")
    related = rag.embed("The hotel limit is $250 per night, and $350 per night in London.")
    unrelated = rag.embed("Native connectors are available for Salesforce and HubSpot.")
    assert rag.cosine(q, related) > rag.cosine(q, unrelated)


def test_keyword_overlap_ignores_stopwords():
    assert rag.keyword_overlap("What is the SLA?", "Enterprise SLA is 99.9%") == 1.0
    assert rag.keyword_overlap("", "anything") == 0.0


def test_chunks_follow_sections_and_keep_their_heading():
    text = "# Title\n\n## Pricing\nStarter costs $49.\n\n## Support\nEmail support only."
    chunks = rag.chunk_text(text)
    assert chunks == ["Pricing\nStarter costs $49.", "Support\nEmail support only."]


def test_long_paragraphs_are_split_by_sentence():
    para = " ".join(f"Sentence number {i} talks about policy details." for i in range(60))
    chunks = rag.chunk_text(f"## Policy\n{para}", size=300)
    assert len(chunks) > 3
    assert all(len(c) <= 360 for c in chunks)
    assert all(c.startswith("Policy") for c in chunks)


def test_extract_text_rejects_unsupported_types():
    with pytest.raises(ValueError):
        rag.extract_text("photo.png", b"...")


def test_search_finds_the_right_document(tmp_path):
    async def run():
        db = Database(f"sqlite+aiosqlite:///{tmp_path / 'rag.db'}")
        await db.init()
        for path in sorted(DATA.glob("*.md")):
            await rag.ingest(db, path.name, path.read_bytes())
        cases = {
            "hotel limit in London": "employee_handbook.md",
            "Growth plan price per month": "product_faq.md",
            "non-renewal notice deadline Acme Cloud": "acme_cloud_contract_summary.md",
            "Q3 revenue growth by region": "q3_2026_business_review.md",
        }
        for query, expected in cases.items():
            hits = await rag.search(db, query, k=3)
            assert hits[0].document == expected, (query, [h.document for h in hits])
        await db.close()

    asyncio.run(run())
