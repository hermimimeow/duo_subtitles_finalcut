from pathlib import Path

from video_workflow.audio import build_ffmpeg_audio_command


def test_ffmpeg_command_declares_mp3_format_for_tmp_output() -> None:
    command = build_ffmpeg_audio_command(
        "ffmpeg",
        Path("input.mov"),
        Path("project_1.mp3.tmp"),
    )

    assert command[-3:] == ["-f", "mp3", "project_1.mp3.tmp"]
