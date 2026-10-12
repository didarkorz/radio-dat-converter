"""Small Tk editor for comparing and converting radio DAT channel settings."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import convert_dat as converter


ROOT = Path(__file__).resolve().parent
FILE_TYPES = [("Настройки рации", "*.dat"), ("Все файлы", "*.*")]


def normalize_frequency(value: str) -> str:
    text = value.strip().replace(",", ".")
    if not re.fullmatch(r"[0-9]{1,3}(\.[0-9]{1,5})?", text):
        raise ValueError("Частота: введите число в МГц, например 435.32500 (до 5 знаков после точки).")
    frequency = Decimal(text)
    if frequency <= 0:
        raise ValueError("Частота должна быть больше нуля.")
    return f"{frequency:09.5f}"


def normalize_tone(value: str) -> str:
    text = value.strip().upper().replace(",", ".")
    if text == "OFF":
        return text
    if re.fullmatch(r"D[0-7]{3}[NIR]", text):
        return text[:-1] + ("I" if text[-1] == "R" else text[-1])
    if not re.fullmatch(r"[0-9]+(\.[0-9])?", text) or Decimal(text) <= 0:
        raise ValueError("Тон: OFF, частота CTCSS (например 127.3) или код DCS (например D371N / D371I).")
    try:
        return converter.word_to_tone(converter.tone_to_word(text))
    except (ValueError, InvalidOperation) as error:
        raise ValueError("Тон CTCSS выходит за диапазон поддерживаемого формата.") from error


def edited_channel(channel: converter.LegacyChannel, values: list[str]) -> converter.LegacyChannel:
    """Normalize user input without changing the original channel or its flag."""
    updated = replace(
        channel,
        rx_freq=normalize_frequency(values[0]),
        tx_freq=normalize_frequency(values[1]),
        rx_tone=normalize_tone(values[2]),
        tx_tone=normalize_tone(values[3]),
    )
    converter.encode_channel(updated)
    return updated


def channel_values(channel) -> tuple[str, str, str, str]:
    return channel.rx_freq, channel.tx_freq, channel.rx_tone, channel.tx_tone


class RadioApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Radio DAT Converter — каналы рации")
        root.geometry("1080x700")
        root.minsize(940, 630)
        self.channels: list[converter.LegacyChannel] = []
        self.original: list[converter.LegacyChannel | None] = []
        self.selected: int | None = None
        self.source: Path | None = None
        self.result_path: Path | None = None
        self.template = tk.StringVar()
        self.source_label = tk.StringVar(value="Исходник не выбран — можно ввести каналы вручную")
        self.status = tk.StringVar(value="Загрузите старый DAT-файл или добавьте канал вручную.")
        self.editor_title = tk.StringVar(value="Значения канала")
        self.fields = [tk.StringVar() for _ in range(4)]
        self._build()
        root.bind("<Control-s>", self.save_shortcut)
        root.bind("<Control-S>", lambda event: self.save_shortcut(event, save_as=True))
        template = ROOT / "124.dat"
        if template.exists():
            self.template.set(str(template))
        if (ROOT / "123.dat").exists():
            self.load_source(ROOT / "123.dat")

    def _build(self):
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=25)
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)
        heading = ttk.Frame(main)
        heading.pack(fill="x")
        ttk.Label(heading, text="Настройки каналов → новый DAT", font=("Segoe UI", 16, "bold")).pack(side="left")
        ttk.Button(heading, text="Сохранить как…", command=lambda: self.save(save_as=True)).pack(side="right", padx=(8, 0))
        ttk.Button(heading, text="Сохранить DAT  •  Ctrl+S", command=self.save).pack(side="right")
        ttk.Label(main, text="Загрузите значения, внесите изменения и сохраните файл для нового ПО.").pack(anchor="w", pady=(2, 12))

        files = ttk.Frame(main)
        files.pack(fill="x")
        files.columnconfigure(1, weight=1)
        ttk.Button(files, text="Открыть старый DAT…", command=self.choose_source).grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Label(files, textvariable=self.source_label, wraplength=750).grid(row=0, column=1, columnspan=2, sticky="w")
        ttk.Label(files, text="Шаблон нового ПО:").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Entry(files, textvariable=self.template, state="readonly").grid(row=1, column=1, sticky="ew", pady=8)
        ttk.Button(files, text="Выбрать…", command=self.choose_template).grid(row=1, column=2, padx=(8, 0))

        ttk.Label(main, text="Слева — как было в исходнике. Справа — что будет записано. Выберите строку для изменения.").pack(anchor="w", pady=(4, 6))
        table = ttk.Frame(main)
        table.pack(fill="both", expand=True)
        columns = ("number", "old_rx", "old_tx", "old_rt", "old_tt", "rx", "tx", "rt", "tt")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse", height=10)
        headings = ("Канал", "Было RX", "Было TX", "Было тон RX", "Было тон TX", "Новый RX", "Новый TX", "Новый тон RX", "Новый тон TX")
        for column, heading in zip(columns, headings):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=55 if column == "number" else 108, minwidth=50, anchor="center")
        self.tree.tag_configure("changed", background="#e6f2ff")
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.select_channel)

        edit = ttk.LabelFrame(main, text="Редактирование выбранного канала", padding=10)
        edit.pack(fill="x", pady=10)
        ttk.Label(edit, textvariable=self.editor_title).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 6))
        self.entries = []
        for index, label in enumerate(("RX, МГц", "TX, МГц", "Тон RX", "Тон TX")):
            edit.columnconfigure(index, weight=1)
            ttk.Label(edit, text=label).grid(row=1, column=index, sticky="w")
            entry = ttk.Entry(edit, textvariable=self.fields[index], width=18)
            entry.grid(row=2, column=index, sticky="ew", padx=(0, 10))
            entry.bind("<Return>", lambda event: self.apply_edits())
            self.entries.append(entry)
        ttk.Button(edit, text="Применить", command=self.apply_edits).grid(row=2, column=4)
        ttk.Label(edit, text="Частота: 435.32500  •  Тон: OFF, 127.3, D371N или D371I. Частоты при смене формата сами не меняются.").grid(row=3, column=0, columnspan=5, sticky="w", pady=(8, 0))

        actions = ttk.Frame(main)
        actions.pack(fill="x")
        ttk.Button(actions, text="Добавить канал", command=self.add_channel).pack(side="left")
        ttk.Button(actions, text="Убрать последний", command=self.remove_last).pack(side="left", padx=8)
        ttk.Button(actions, text="Конвертировать и сохранить…", command=self.save).pack(side="right")
        ttk.Label(main, textvariable=self.status, wraplength=1000).pack(anchor="w", pady=(10, 0))

    def invalidate_result(self):
        self.status.set("Есть изменения. Нажмите «Сохранить DAT» или Ctrl+S, чтобы записать их в файл.")

    def save_shortcut(self, _event=None, save_as=False):
        self.save(save_as=save_as)
        return "break"

    def choose_source(self):
        path = filedialog.askopenfilename(parent=self.root, title="Старый файл настроек", filetypes=FILE_TYPES)
        if path:
            if self.channels and not messagebox.askyesno("Загрузить другие каналы?", "Текущие значения в окне будут заменены каналами из выбранного файла.", parent=self.root):
                return
            self.load_source(Path(path))

    def load_source(self, path: Path):
        try:
            channels = converter.parse_legacy_channels(path)
        except (OSError, ValueError) as error:
            messagebox.showerror("Не удалось открыть исходник", str(error), parent=self.root)
            return
        self.source = path.resolve()
        self.channels = deepcopy(channels)
        self.original = deepcopy(channels)
        self.selected = None
        self.result_path = None
        self.source_label.set(str(self.source))
        self.refresh()
        self.focus_channel(0)
        self.status.set(f"Загружено каналов: {len(channels)}. Выберите канал, чтобы изменить его значения.")

    def choose_template(self):
        path = filedialog.askopenfilename(parent=self.root, title="Шаблон из нового ПО", filetypes=FILE_TYPES)
        if path:
            try:
                converter.parse_modern_template(Path(path))
            except (OSError, ValueError) as error:
                messagebox.showerror("Не удалось открыть шаблон", str(error), parent=self.root)
                return
            self.template.set(path)
            self.invalidate_result()

    def refresh(self, decoded=None):
        self.tree.delete(*self.tree.get_children())
        for index, channel in enumerate(self.channels):
            before = channel_values(self.original[index]) if self.original[index] else ("—",) * 4
            after = channel_values(decoded[index] if decoded else channel)
            self.tree.insert("", "end", iid=str(index), values=(index + 1, *before, *after), tags=("changed",) if before != after else ())

    def focus_channel(self, index: int):
        self.selected = index
        self.tree.selection_set(str(index))
        self.tree.see(str(index))
        self.editor_title.set(f"Канал {index + 1} — значения для нового файла")
        for variable, value in zip(self.fields, channel_values(self.channels[index])):
            variable.set(value)

    def select_channel(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        index = int(selection[0])
        if index == self.selected:
            return
        previous = self.selected
        if not self.apply_edits():
            if previous is not None:
                self.tree.selection_set(str(previous))
            return
        self.focus_channel(index)

    def apply_edits(self) -> bool:
        if self.selected is None:
            return True
        index = self.selected
        try:
            updated = edited_channel(self.channels[index], [field.get() for field in self.fields])
        except (ValueError, InvalidOperation) as error:
            messagebox.showerror(f"Проверьте канал {index + 1}", str(error), parent=self.root)
            return False
        if updated != self.channels[index]:
            self.channels[index] = updated
            self.invalidate_result()
            before = channel_values(self.original[index]) if self.original[index] else ("—",) * 4
            self.tree.item(str(index), values=(index + 1, *before, *channel_values(updated)), tags=("changed",) if before != channel_values(updated) else ())
        for variable, value in zip(self.fields, channel_values(updated)):
            variable.set(value)
        return True

    def add_channel(self):
        if len(self.channels) >= converter.CHANNEL_COUNT:
            messagebox.showinfo("Все каналы заполнены", "Формат поддерживает не более 16 каналов.", parent=self.root)
            return
        if not self.apply_edits():
            return
        fields = ["0"] * 12
        fields[4] = "1"
        self.channels.append(converter.LegacyChannel(len(self.channels) + 1, "", "", "0", "0", fields, "OFF", "OFF"))
        self.original.append(None)
        self.refresh()
        self.focus_channel(len(self.channels) - 1)
        self.invalidate_result()
        self.entries[0].focus_set()

    def remove_last(self):
        if not self.channels:
            return
        # Pending input on another channel must survive removal of the last row.
        if self.selected != len(self.channels) - 1 and not self.apply_edits():
            return
        self.channels.pop()
        self.original.pop()
        self.selected = None
        self.refresh()
        if self.channels:
            self.focus_channel(len(self.channels) - 1)
        else:
            for field in self.fields:
                field.set("")
            self.editor_title.set("Добавьте канал или откройте старый DAT")
        self.invalidate_result()

    def save(self, save_as=False):
        if not self.channels:
            messagebox.showinfo("Нет каналов", "Откройте старый DAT или добавьте канал вручную.", parent=self.root)
            return
        if not self.apply_edits():
            return
        if not self.template.get():
            messagebox.showinfo("Нужен шаблон", "Выберите DAT-файл, сохранённый новым ПО для вашей рации.", parent=self.root)
            return
        template = Path(self.template.get()).resolve()
        try:
            converter.parse_modern_template(template)
            channels = [edited_channel(channel, list(channel_values(channel))) for channel in self.channels]
        except (OSError, ValueError, InvalidOperation) as error:
            messagebox.showerror("Не удалось подготовить файл", str(error), parent=self.root)
            return
        output = self.result_path
        if save_as or output is None:
            path = filedialog.asksaveasfilename(
                parent=self.root, title="Сохранить готовый DAT-файл",
                initialdir=str(output.parent if output else ROOT),
                initialfile=output.name if output else "radio_converted.dat",
                defaultextension=".dat", filetypes=FILE_TYPES,
            )
            if not path:
                return
            output = Path(path).resolve()
        protected = [template] + ([self.source] if self.source else [])
        if any(output == item or (output.exists() and item.exists() and output.samefile(item)) for item in protected):
            messagebox.showerror("Выберите другое имя", "Результат нужно сохранить отдельно от исходника и шаблона.", parent=self.root)
            return
        try:
            converter.convert_channels(channels, template, output)
            _, image = converter.parse_modern_template(output)
            decoded = converter.decode_modern_channels(image, len(channels))
            for channel, result in zip(channels, decoded):
                if channel_values(channel) != channel_values(result) or converter.legacy_flag_to_modern(channel) != result.flag:
                    raise ValueError(f"Проверка записанного канала {channel.index} не прошла.")
        except (OSError, ValueError, InvalidOperation) as error:
            messagebox.showerror("Не удалось сохранить и проверить файл", str(error), parent=self.root)
            return
        self.channels = channels
        self.result_path = output
        self.refresh(decoded)
        self.focus_channel(self.selected if self.selected is not None else 0)
        self.status.set(f"Готово: {output}\nПроверено каналов: {len(decoded)}. Справа показаны значения, прочитанные из сохранённого файла.")
        messagebox.showinfo("Файл готов", f"Сохранено и проверено каналов: {len(decoded)}.\n\n{output}\n\nФайл можно открыть в новом ПО настройки рации.", parent=self.root)


def main():
    root = tk.Tk()
    RadioApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
