"""BRSE interprets microphone audio only — never screen-share audio or unknown sources."""
from types import SimpleNamespace

import livekit.rtc as rtc
import pytest

from server.service.media.livekit_runtime import LiveKitRuntime


@pytest.fixture
def runtime(fake_settings):
    return LiveKitRuntime("rm_test", fake_settings, lambda _: None, lambda _: None, lambda *_: None)


def _publication(source, kind=rtc.TrackKind.KIND_AUDIO):
    return SimpleNamespace(kind=kind, source=source, sid="TR_x")


def _participant(identity="pt_user"):
    return SimpleNamespace(identity=identity)


def test_microphone_feeds_brse(runtime):
    assert runtime._is_human_microphone_audio(_participant(), _publication(rtc.TrackSource.SOURCE_MICROPHONE))


@pytest.mark.parametrize(
    "source",
    [rtc.TrackSource.SOURCE_SCREENSHARE_AUDIO, rtc.TrackSource.SOURCE_UNKNOWN, None],
)
def test_screen_share_and_unknown_audio_never_feed_brse(runtime, source):
    assert not runtime._is_human_microphone_audio(_participant(), _publication(source))


def test_video_and_interpreter_tracks_are_ignored(runtime):
    assert not runtime._is_human_microphone_audio(
        _participant(), _publication(rtc.TrackSource.SOURCE_SCREENSHARE, kind=rtc.TrackKind.KIND_VIDEO)
    )
    assert not runtime._is_human_microphone_audio(
        _participant("interp::rm_test"), _publication(rtc.TrackSource.SOURCE_MICROPHONE)
    )
