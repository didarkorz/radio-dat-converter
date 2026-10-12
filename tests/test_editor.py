"""User input, edited-file output and failure handling for the desktop editor."""

from pathlib import Path
import tempfile
import unittest

import convert_dat as converter
from radio_gui import edited_channel, normalize_frequency, normalize_tone


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class EditorTests(unittest.TestCase):
    def test_user_input_is_normalized_without_mutating_original(self):
        original = converter.parse_legacy_channels(EXAMPLES / "legacy.dat")[0]
        updated = edited_channel(original, ["436,5", "437", "d023r", "67"])
        self.assertEqual((updated.rx_freq, updated.tx_freq), ("436.50000", "437.00000"))
        self.assertEqual((updated.rx_tone, updated.tx_tone), ("D023I", "67.0"))
        self.assertEqual((original.rx_freq, original.rx_tone), ("435.32500", "127.3"))
        self.assertEqual(updated.legacy_fields, original.legacy_fields)

    def test_invalid_input_is_rejected(self):
        for frequency in ("", "0", "-1", "435.123456", "1.2.3", "1000", "NaN", "inf"):
            with self.subTest(frequency=frequency), self.assertRaises(ValueError):
                normalize_frequency(frequency)
        for tone in ("", "NaN", "Infinity", "0", "-67", "D888N", "127.33", "9999"):
            with self.subTest(tone=tone), self.assertRaises(ValueError):
                normalize_tone(tone)

    def test_edited_values_are_written_and_other_records_preserved(self):
        channels = converter.parse_legacy_channels(EXAMPLES / "legacy.dat")
        channels[1] = edited_channel(channels[1], ["440.125", "441.5", "D023R", "88.5"])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.dat"
            converter.convert_channels(channels, EXAMPLES / "modern_template.dat", output)
            _, image = converter.parse_modern_template(output)
            _, expected = converter.parse_modern_template(EXAMPLES / "expected_converted.dat")
            result = converter.decode_modern_channels(image)[1]
            self.assertEqual((result.rx_freq, result.tx_freq, result.rx_tone, result.tx_tone),
                             ("440.12500", "441.50000", "D023I", "88.5"))
            self.assertEqual(result.flag, 0xEF)
            self.assertEqual(image[:0x20], expected[:0x20])
            self.assertEqual(image[0x30:], expected[0x30:])

    def test_invalid_channel_does_not_overwrite_existing_output(self):
        channels = converter.parse_legacy_channels(EXAMPLES / "legacy.dat")
        channels[-1].rx_freq = "invalid"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.dat"
            output.write_bytes(b"previous result")
            with self.assertRaises(ValueError):
                converter.convert_channels(channels, EXAMPLES / "modern_template.dat", output)
            self.assertEqual(output.read_bytes(), b"previous result")


if __name__ == "__main__":
    unittest.main()
