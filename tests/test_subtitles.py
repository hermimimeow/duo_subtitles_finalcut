from video_workflow.models import SubtitleCue
from video_workflow.subtitles import (
    cues_aligned,
    format_timestamp,
    merge_cues,
    parse_srt_text,
    render_srt,
)


def test_render_and_parse_srt_round_trip() -> None:
    cues = [
        SubtitleCue(1, 0.0, 1.25, "你好"),
        SubtitleCue(2, 1.5, 2.75, "世界"),
    ]

    parsed = parse_srt_text(render_srt(cues))

    assert parsed == cues
    assert format_timestamp(3723.456) == "01:02:03,456"


def test_merge_cues_combines_lines_and_preserves_timing() -> None:
    source = [SubtitleCue(1, 0.0, 1.0, "你好")]
    translated = [SubtitleCue(1, 0.0, 1.0, "Hello")]

    merged = merge_cues(source, translated)

    assert cues_aligned(source, translated)
    assert merged == [SubtitleCue(1, 0.0, 1.0, "你好\nHello")]
