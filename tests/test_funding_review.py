import json

import pytest

from evaluation import funding_review as review


def test_funding_review_preserves_unknown_dates_and_no_unproven_growth():
    result = review.build()
    assert result == json.loads((review.ROOT / review.OUTPUT).read_text())
    rows = {r['company_id']: r for r in result['reviews']}
    assert rows['llamaindex']['announcement_date'] is None
    assert rows['browserbase']['announcement_within_study_window'] is False
    assert rows['langchain']['lead_investor'] == 'CapitalG'
    assert rows['langchain']['retained_complete_github_windows_strictly_after_announcement'] == []
    assert len(rows['langchain']['post_announcement_board_snapshot_dates']) == 1
    for row in rows.values():
        assert row['financing_closed_at'] is None
        assert row['original_event_at'] is None
        assert row['independent_personal_annotation'] is False
        assert row['funding_caused_growth_established'] is False
        for span in row['passages'].values():
            if span:
                assert span['end'] - span['start'] == len(span['text'])


def test_unmatched_source_passages_are_rejected():
    with pytest.raises(ValueError, match='no longer matches'):
        review.passage('The published source text.', 'A fabricated funding assertion.')
