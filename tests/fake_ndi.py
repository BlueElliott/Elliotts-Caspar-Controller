"""A stand-in for ndi-python's NDIlib module, using 6.3.2.6's names, for tally tests.

Serves queued metadata frames to one receiver and records what it asked for, freed and
destroyed. Sets ``stop`` once the queue is empty, so a tally session ends without threads.
"""

import threading
from types import SimpleNamespace


class FakeNDI:
    # Strings, not the real enum values: an int like -10 must not pass for the enum.
    RECV_BANDWIDTH_HIGHEST = "highest"
    RECV_BANDWIDTH_METADATA_ONLY = "metadata-only"
    FRAME_TYPE_NONE = "none"
    FRAME_TYPE_METADATA = "metadata"

    def __init__(self):
        self.stop = threading.Event()
        self.frames: list = []  # XML still to deliver
        self.connect_error: Exception | None = None
        self.receivers: list = []  # the settings each receiver was created with
        self.captures: list = []  # (want_video, want_audio) for each capture
        self.freed: list = []  # XML of each freed frame
        self.destroyed = 0

    def RecvCreateV3(self) -> SimpleNamespace:
        return SimpleNamespace(
            bandwidth=self.RECV_BANDWIDTH_HIGHEST, allow_video_fields=True, ndi_recv_name=""
        )

    def recv_create_v3(self, settings: SimpleNamespace) -> str:
        self.receivers.append(settings)
        return "recv"

    def recv_connect(self, recv: str, source: object) -> None:
        if self.connect_error:
            raise self.connect_error

    def recv_capture_v3(
        self, recv: str, timeout_in_ms: int, want_video=True, want_audio=True, want_metadata=True
    ) -> tuple:
        self.captures.append((want_video, want_audio))
        if not self.frames:
            self.stop.set()
            return self.FRAME_TYPE_NONE, None, None, None
        return self.FRAME_TYPE_METADATA, None, None, SimpleNamespace(data=self.frames.pop(0))

    def recv_free_metadata(self, recv: str, metadata: SimpleNamespace) -> None:
        self.freed.append(metadata.data)

    def recv_destroy(self, recv: str) -> None:
        self.destroyed += 1
