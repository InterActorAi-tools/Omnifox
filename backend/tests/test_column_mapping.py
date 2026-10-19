"""Link exports: when two source columns map to one name, the first wins and the
other keeps its own column (found by the data review)."""
import pandas as pd


def test_first_mapping_wins_and_nothing_is_lost():
    from services.export_service import column_mapper
    df = pd.DataFrame([{"message": "hi", "comment_id": "c1", "id": "fb_1", "like_count": 12, "likes": None}])

    mapped = column_mapper.map_columns(df, "facebook")

    assert mapped.at[0, "Comment ID"] == "c1"
    assert mapped.at[0, "Likes"] == 12
    assert "fb_1" in mapped.iloc[0].tolist()  # kept under its own name
