from rain_pipeline import anna_stage, vendor


def test_record_hit_keeps_only_the_workbench_fields_and_fingerprint_verifies_offline():
    vendor.ensure_importable()
    from engine import records

    api_hit = {
        "score": 0.03, "relevance": 1.0, "highlights": ["<em>sinus</em>"], "explanation": {"method": "rrf"},
        "document": {"id": "arxiv:1", "title": "RSA", "source": "arxiv", "abstract": "Breathing modulates heart rate.",
                     "url": "https://arxiv.org/abs/1", "pdf_url": None, "authors": ["A"], "published": "2020",
                     "version": None, "categories": ["q-bio"], "body": "not exported"},
    }
    hit = anna_stage._record_hit(api_hit)
    assert set(hit["document"]) == {"id", "title", "source", "url", "pdf_url", "authors", "published", "version",
                                    "abstract"}
    assert hit["document"]["pdf_url"] == "" and hit["relevance"] == 1.0

    record = {"schema": records.RECORD_SCHEMA, "hits": [hit], "summary": None}
    packet = {"captured_at": "2026-10-04T00:00:00.000Z", "content_sha256": records.fingerprint(record),
              "record": record}
    assert records.verify_record(packet, None)["fingerprint"]["matches"] is True
    packet["record"]["hits"][0]["document"]["title"] = "edited"
    assert records.verify_record(packet, None)["fingerprint"]["matches"] is False


def test_panel_corpus_files_are_quotable_markdown(tmp_path):
    from rain_pipeline import panel_stage

    class Doc:
        id, title, url, published = "arxiv:9", "Respiratory sinus arrhythmia in humans", "https://arxiv.org/abs/9", "2021"
        authors = ["A. Author"]
        abstract = ("Respiratory sinus arrhythmia is the rhythmic increase of heart rate during inspiration "
                    "and its decrease during expiration in healthy resting adults.")

    sources = panel_stage.write_corpus([Doc()], tmp_path)
    (name,) = sources
    assert sources[name]["anna_id"] == "arxiv:9"
    text = (tmp_path / name).read_text(encoding="utf-8")
    assert "Abstract" in text and Doc.abstract in text
