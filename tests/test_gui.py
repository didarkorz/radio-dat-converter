"""Exercise window callbacks with dialogs replaced and the window hidden."""

from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

import convert_dat as converter
import radio_gui


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class WindowTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        with patch.object(radio_gui, "ROOT", Path(self.directory.name)):
            self.app = radio_gui.RadioApp(self.root)
        self.app.template.set(str(EXAMPLES / "modern_template.dat"))
        self.app.load_source(EXAMPLES / "legacy.dat")
        self.root.update()

    def test_save_applies_pending_input_and_displays_readback(self):
        output = Path(self.directory.name) / "edited.dat"
        self.app.fields[0].set("440,125")
        self.app.fields[2].set("D023R")
        with patch.object(radio_gui.filedialog, "asksaveasfilename", return_value=str(output)), \
             patch.object(radio_gui.messagebox, "showinfo"), \
             patch.object(radio_gui.messagebox, "showerror") as error:
            self.app.save()
        self.root.update()
        error.assert_not_called()
        _, image = converter.parse_modern_template(output)
        first = converter.decode_modern_channels(image)[0]
        self.assertEqual((first.rx_freq, first.rx_tone), ("440.12500", "D023I"))
        row = self.app.tree.item("0", "values")
        self.assertEqual(row[1], "435.32500")
        self.assertEqual(row[5], "440.12500")
        self.assertEqual(row[7], "D023I")
        self.assertEqual(self.app.result_path, output.resolve())

    def test_switching_channel_applies_input(self):
        self.app.fields[1].set("445.5")
        self.app.tree.selection_set("1")
        self.root.update()
        self.assertEqual(self.app.channels[0].tx_freq, "445.50000")
        self.assertEqual(self.app.selected, 1)
        self.assertEqual(self.app.fields[0].get(), "436.43500")

    def test_save_reuses_path_and_save_as_creates_separate_file(self):
        output = Path(self.directory.name) / "saved.dat"
        copy = Path(self.directory.name) / "copy.dat"
        with patch.object(radio_gui.filedialog, "asksaveasfilename", return_value=str(output)) as dialog, \
             patch.object(radio_gui.messagebox, "showinfo"), \
             patch.object(radio_gui.messagebox, "showerror") as error:
            self.app.save()
            dialog.assert_called_once()
            dialog.reset_mock()
            self.app.fields[0].set("440.5")
            self.assertEqual(self.app.save_shortcut(), "break")
            dialog.assert_not_called()
            _, image = converter.parse_modern_template(output)
            self.assertEqual(converter.decode_modern_channels(image)[0].rx_freq, "440.50000")
            saved_bytes = output.read_bytes()
            self.app.fields[0].set("441.5")
            dialog.return_value = str(copy)
            self.app.save(save_as=True)
            dialog.assert_called_once()
            self.assertEqual(output.read_bytes(), saved_bytes)
            _, image = converter.parse_modern_template(copy)
            self.assertEqual(converter.decode_modern_channels(image)[0].rx_freq, "441.50000")
            self.assertEqual(self.app.result_path, copy.resolve())
            error.assert_not_called()

    def test_cancel_save_as_keeps_previous_output(self):
        output = Path(self.directory.name) / "saved.dat"
        with patch.object(radio_gui.filedialog, "asksaveasfilename", return_value=str(output)) as dialog, \
             patch.object(radio_gui.messagebox, "showinfo"):
            self.app.save()
            before = output.read_bytes()
            self.app.fields[0].set("442.5")
            dialog.return_value = ""
            self.app.save(save_as=True)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(self.app.result_path, output.resolve())
            self.assertEqual(self.app.channels[0].rx_freq, "442.50000")

    def test_manual_channel_can_be_saved_without_source(self):
        for _ in range(16):
            self.app.remove_last()
        self.app.add_channel()
        for field, value in zip(self.app.fields, ("435.5", "436.5", "OFF", "67")):
            field.set(value)
        output = Path(self.directory.name) / "manual.dat"
        with patch.object(radio_gui.filedialog, "asksaveasfilename", return_value=str(output)), \
             patch.object(radio_gui.messagebox, "showinfo"), \
             patch.object(radio_gui.messagebox, "showerror") as error:
            self.app.save()
        self.root.update()
        error.assert_not_called()
        _, image = converter.parse_modern_template(output)
        first = converter.decode_modern_channels(image)[0]
        self.assertEqual((first.rx_freq, first.tx_freq, first.tx_tone), ("435.50000", "436.50000", "67.0"))
        self.assertEqual(self.app.tree.item("0", "values")[1], "—")

    def test_source_cannot_be_overwritten(self):
        before = (EXAMPLES / "legacy.dat").read_bytes()
        with patch.object(radio_gui.filedialog, "asksaveasfilename", return_value=str(EXAMPLES / "legacy.dat")), \
             patch.object(radio_gui.messagebox, "showerror") as error:
            self.app.save()
        error.assert_called_once()
        self.assertEqual((EXAMPLES / "legacy.dat").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
