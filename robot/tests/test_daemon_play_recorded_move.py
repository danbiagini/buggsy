import io
import urllib.error
from unittest.mock import MagicMock, patch

from robot.agent.agent import daemon_play_recorded_move


def _fake_resp(body: bytes) -> MagicMock:
    resp = MagicMock()
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: False
    resp.read.return_value = body
    return resp


def test_returns_uuid_on_success():
    with patch("urllib.request.urlopen", return_value=_fake_resp(b'{"uuid": "abc-123"}')) as urlopen:
        result = daemon_play_recorded_move("http://daemon:8000", "ds", "mv")
    assert result == "abc-123"
    req = urlopen.call_args[0][0]
    assert req.full_url == "http://daemon:8000/api/move/play/recorded-move-dataset/ds/mv"
    assert req.get_method() == "POST"


def test_returns_none_on_http_error():
    err = urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO(b""))
    with patch("urllib.request.urlopen", side_effect=err):
        assert daemon_play_recorded_move("http://daemon:8000", "ds", "missing") is None


def test_returns_none_on_url_error():
    err = urllib.error.URLError("connection refused")
    with patch("urllib.request.urlopen", side_effect=err):
        assert daemon_play_recorded_move("http://daemon:8000", "ds", "mv") is None


def test_returns_none_on_non_json_body():
    with patch("urllib.request.urlopen", return_value=_fake_resp(b"not json")):
        assert daemon_play_recorded_move("http://daemon:8000", "ds", "mv") is None


def test_returns_none_when_uuid_missing():
    with patch("urllib.request.urlopen", return_value=_fake_resp(b'{"foo": "bar"}')):
        assert daemon_play_recorded_move("http://daemon:8000", "ds", "mv") is None
