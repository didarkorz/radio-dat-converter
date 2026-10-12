"""Regression checks against the original conversion and template boundaries."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import convert_dat


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


class ConversionTests(unittest.TestCase):
    def test_original_conversion_matches_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "converted.dat"
            convert_dat.convert(
                EXAMPLES / "legacy.dat", EXAMPLES / "modern_template.dat", output
            )
            self.assertEqual(
                output.read_bytes(), (EXAMPLES / "expected_converted.dat").read_bytes()
            )

    def test_existing_reference_passes_frequency_and_tone_report(self):
        with redirect_stdout(io.StringIO()) as report:
            convert_dat.print_report(
                EXAMPLES / "legacy.dat", EXAMPLES / "expected_converted.dat"
            )
        self.assertEqual(len(report.getvalue().splitlines()), 18)

    def test_partial_conversion_preserves_unused_channels_and_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "one_channel.dat"
            output = Path(directory) / "converted.dat"
            source.write_bytes((EXAMPLES / "legacy.dat").read_bytes().splitlines()[0] + b"\n")
            convert_dat.convert(source, EXAMPLES / "modern_template.dat", output)
            header_before, before = convert_dat.parse_modern_template(
                EXAMPLES / "modern_template.dat"
            )
            header_after, after = convert_dat.parse_modern_template(output)
            self.assertEqual(header_after, header_before)
            self.assertEqual(after[:0x10], before[:0x10])
            self.assertEqual(after[0x20:], before[0x20:])
            _, reference = convert_dat.parse_modern_template(
                EXAMPLES / "expected_converted.dat"
            )
            self.assertEqual(after[0x10:0x20], reference[0x10:0x20])

    def test_cli_creates_output_and_reports_all_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "converted.dat"
            result = subprocess.run(
                [
                    sys.executable, str(ROOT / "convert_dat.py"),
                    "--old", str(EXAMPLES / "legacy.dat"),
                    "--template", str(EXAMPLES / "modern_template.dat"),
                    "--output", str(output), "--report",
                ],
                cwd=directory, capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(result.stdout.splitlines()), 18)
            self.assertEqual(
                output.read_bytes(), (EXAMPLES / "expected_converted.dat").read_bytes()
            )


if __name__ == "__main__":
    unittest.main()
