import json
import unittest

from audio_processor import (
    InputValidationError,
    MediaInfo,
    MediaProcessingError,
    parse_probe_json,
    validate_media,
)


class ParseProbeJsonTests(unittest.TestCase):
    def test_parses_video_with_audio(self):
        payload = {
            "format": {"duration": "12.5", "size": "4096"},
            "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
        }

        result = parse_probe_json(json.dumps(payload))

        self.assertEqual(result, MediaInfo(12.5, 4096, True, True))

    def test_uses_file_size_when_ffprobe_omits_size(self):
        payload = {
            "format": {"duration": "3"},
            "streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
        }

        result = parse_probe_json(json.dumps(payload), fallback_size_bytes=1234)

        self.assertEqual(result.size_bytes, 1234)

    def test_rejects_invalid_probe_output(self):
        with self.assertRaises(MediaProcessingError):
            parse_probe_json("not json")


class ValidateMediaTests(unittest.TestCase):
    def setUp(self):
        self.valid_media = MediaInfo(
            duration_seconds=120,
            size_bytes=10 * 1024 * 1024,
            has_video=True,
            has_audio=True,
        )
        self.limits = {
            "max_size_bytes": 20 * 1024 * 1024,
            "max_duration_seconds": 300,
        }

    def test_accepts_media_within_limits(self):
        validate_media(self.valid_media, **self.limits)

    def test_rejects_video_without_audio(self):
        media = MediaInfo(10, 1000, True, False)
        with self.assertRaisesRegex(InputValidationError, "অডিও"):
            validate_media(media, **self.limits)

    def test_rejects_video_without_video_track(self):
        media = MediaInfo(10, 1000, False, True)
        with self.assertRaisesRegex(InputValidationError, "ভিডিও ট্র্যাক"):
            validate_media(media, **self.limits)

    def test_rejects_file_over_size_limit(self):
        media = MediaInfo(10, 21 * 1024 * 1024, True, True)
        with self.assertRaisesRegex(InputValidationError, "20 MB"):
            validate_media(media, **self.limits)

    def test_rejects_file_over_duration_limit(self):
        media = MediaInfo(301, 1000, True, True)
        with self.assertRaisesRegex(InputValidationError, "5 মিনিট"):
            validate_media(media, **self.limits)


if __name__ == "__main__":
    unittest.main()
