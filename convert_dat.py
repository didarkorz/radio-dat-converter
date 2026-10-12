"""Convert legacy radio channel settings using a compatible newer CPS template.

See README.md for usage and docs/FORMAT.md for the observed format mapping.
Only the Python standard library is required.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import re
from pathlib import Path


CHANNEL_RECORD_SIZE = 16
CHANNEL_COUNT = 16
CHANNEL_BASE_OFFSET = 0x10
CHANNEL_REGION_SIZE = CHANNEL_BASE_OFFSET + CHANNEL_RECORD_SIZE * CHANNEL_COUNT

# The newer CPS template shows two active channel-flag variants: 0xEB and 0xEF.
# The legacy CSV exposes only one consistently varying per-channel flag column,
# so we map that legacy toggle onto the observed 0x04 delta.
FLAG_BASE = 0xEB
FLAG_ALT = 0xEF


@dataclass
class LegacyChannel:
    index: int
    rx_freq: str
    tx_freq: str
    rx_tone_index: str
    tx_tone_index: str
    legacy_fields: list[str]
    rx_tone: str
    tx_tone: str


@dataclass
class ModernChannel:
    index: int
    rx_freq: str
    tx_freq: str
    rx_tone: str
    tx_tone: str
    flag: int


def parse_legacy_channels(path: Path) -> list[LegacyChannel]:
    text = path.read_bytes().decode("latin1")
    channels: list[LegacyChannel] = []

    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            if channels:
                break
            continue
        if "," not in line:
            if channels:
                break
            continue

        fields = [part.strip() for part in line.split(",")]
        if len(fields) != 18:
            raise ValueError(
                f"{path} line {line_no}: expected 18 CSV fields, found {len(fields)}"
            )
        channels.append(
            LegacyChannel(
                index=len(channels) + 1,
                rx_freq=fields[0],
                tx_freq=fields[1],
                rx_tone_index=fields[2],
                tx_tone_index=fields[3],
                legacy_fields=fields[4:16],
                rx_tone=fields[16],
                tx_tone=fields[17],
            )
        )

    if not channels:
        raise ValueError(f"{path}: no legacy channel rows found")

    if len(channels) > CHANNEL_COUNT:
        raise ValueError(
            f"{path}: found {len(channels)} channels, template supports {CHANNEL_COUNT}"
        )

    return channels


def parse_modern_template(path: Path) -> tuple[str, bytearray]:
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    if not lines:
        raise ValueError(f"{path}: empty template")

    header = lines[0]
    chunks: dict[int, bytes] = {}

    for line_no, line in enumerate(lines[1:], start=2):
        parts = line.split()
        if len(parts) != 12:
            raise ValueError(
                f"{path} line {line_no}: expected 12 tokens, found {len(parts)}"
            )
        if parts[0] != "57":
            raise ValueError(f"{path} line {line_no}: unsupported record tag {parts[0]}")

        addr = (int(parts[1], 16) << 8) | int(parts[2], 16)
        length = int(parts[3], 16)
        if length != 8:
            raise ValueError(f"{path} line {line_no}: expected length 08, found {length:02X}")

        data = bytes(int(token, 16) for token in parts[4:12])
        chunks[addr] = data

    if not chunks:
        raise ValueError(f"{path}: no memory records found")

    image = bytearray(max(chunks) + 8)
    for addr, data in chunks.items():
        image[addr : addr + 8] = data

    if len(image) < CHANNEL_REGION_SIZE:
        raise ValueError(
            f"{path}: template image too short ({len(image)} bytes) for {CHANNEL_COUNT} channels"
        )

    return header, image


def freq_to_word(freq_text: str) -> bytes:
    digits = freq_text.strip().replace(".", "")
    if not re.fullmatch(r"\d{8}", digits):
        raise ValueError(f"unsupported frequency format: {freq_text!r}")
    return int(digits, 16).to_bytes(4, "little")


def word_to_freq(word: bytes) -> str:
    digits = f"{int.from_bytes(word, 'little'):08X}"
    return f"{digits[:3]}.{digits[3:]}"


def ctcss_to_word(tone_text: str) -> int:
    tenths = int(
        (Decimal(tone_text).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) * 10)
    )
    value = 0x89FF - tenths
    if not (0x8000 <= value <= 0x8FFF):
        raise ValueError(f"CTCSS tone out of encodable range: {tone_text}")
    return value


def word_to_ctcss(value: int) -> str:
    tenths = Decimal(0x89FF - value) / Decimal(10)
    return f"{tenths:.1f}"


def dcs_to_word(tone_text: str) -> int:
    match = re.fullmatch(r"D([0-7]{3})([NnRrIi])", tone_text.strip())
    if not match:
        raise ValueError(f"unsupported DCS format: {tone_text!r}")

    code = match.group(1).upper()
    polarity = match.group(2).upper()
    # New CPS displays the template's 0xCxxx words as inverted polarity,
    # so normal polarity must be encoded with 0xDxxx instead.
    prefix = "D" if polarity == "N" else "C"
    return int(prefix + code, 16)


def word_to_dcs(value: int) -> str:
    code = f"{value & 0x0FFF:03X}"
    prefix = (value >> 12) & 0xF
    suffix = "N" if prefix == 0xD else "I"
    return f"D{code}{suffix}"


def tone_to_word(tone_text: str) -> int:
    tone = tone_text.strip().upper()
    if tone == "OFF":
        return 0xFFFF
    if tone.startswith("D"):
        return dcs_to_word(tone)
    return ctcss_to_word(tone)


def word_to_tone(value: int) -> str:
    if value == 0xFFFF:
        return "OFF"
    prefix = value & 0xF000
    if prefix in (0xC000, 0xD000):
        return word_to_dcs(value)
    if prefix == 0x8000:
        return word_to_ctcss(value)
    return f"0x{value:04X}"


def legacy_flag_to_modern(channel: LegacyChannel) -> int:
    legacy_toggle = channel.legacy_fields[4]
    return FLAG_BASE if legacy_toggle == "1" else FLAG_ALT


def encode_channel(channel: LegacyChannel) -> bytes:
    record = bytearray(CHANNEL_RECORD_SIZE)
    record[0:4] = freq_to_word(channel.rx_freq)
    record[4:8] = freq_to_word(channel.tx_freq)
    record[8:10] = tone_to_word(channel.rx_tone).to_bytes(2, "little")
    record[10:12] = tone_to_word(channel.tx_tone).to_bytes(2, "little")
    record[12] = legacy_flag_to_modern(channel)
    record[13:16] = b"\xFF\xFF\xFF"
    return bytes(record)


def decode_modern_channels(image: bytes, count: int = CHANNEL_COUNT) -> list[ModernChannel]:
    channels: list[ModernChannel] = []
    for index in range(count):
        offset = CHANNEL_BASE_OFFSET + index * CHANNEL_RECORD_SIZE
        record = image[offset : offset + CHANNEL_RECORD_SIZE]
        channels.append(
            ModernChannel(
                index=index + 1,
                rx_freq=word_to_freq(record[0:4]),
                tx_freq=word_to_freq(record[4:8]),
                rx_tone=word_to_tone(int.from_bytes(record[8:10], "little")),
                tx_tone=word_to_tone(int.from_bytes(record[10:12], "little")),
                flag=record[12],
            )
        )
    return channels


def write_modern_file(path: Path, header: str, image: bytes) -> None:
    lines = [header]
    for addr in range(0, len(image), 8):
        chunk = image[addr : addr + 8]
        data_text = " ".join(f"{byte:02X}" for byte in chunk)
        lines.append(f"57 {addr >> 8:02X} {addr & 0xFF:02X} 08 {data_text} ")
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))


def convert(old_path: Path, template_path: Path, output_path: Path) -> None:
    legacy_channels = parse_legacy_channels(old_path)
    convert_channels(legacy_channels, template_path, output_path)


def convert_channels(
    channels: list[LegacyChannel], template_path: Path, output_path: Path
) -> None:
    """Write edited channels, validating all records before touching the output."""
    if not 1 <= len(channels) <= CHANNEL_COUNT:
        raise ValueError(f"Expected 1 to {CHANNEL_COUNT} channels")
    if [channel.index for channel in channels] != list(range(1, len(channels) + 1)):
        raise ValueError("Channel numbers must be consecutive, starting at 1")
    header, image = parse_modern_template(template_path)

    for channel in channels:
        offset = CHANNEL_BASE_OFFSET + (channel.index - 1) * CHANNEL_RECORD_SIZE
        image[offset : offset + CHANNEL_RECORD_SIZE] = encode_channel(channel)

    write_modern_file(output_path, header, image)


def print_report(old_path: Path, new_path: Path) -> None:
    legacy_channels = parse_legacy_channels(old_path)
    _, image = parse_modern_template(new_path)
    decoded = decode_modern_channels(image, len(legacy_channels))

    print("Channel  RX         TX         RX Tone  TX Tone  Flag")
    print("-------  ---------  ---------  -------  -------  ----")
    for legacy, modern in zip(legacy_channels, decoded):
        print(
            f"{modern.index:>7}  "
            f"{modern.rx_freq:<9}  "
            f"{modern.tx_freq:<9}  "
            f"{modern.rx_tone:<7}  "
            f"{modern.tx_tone:<7}  "
            f"{modern.flag:02X}"
        )

        expected_rx = legacy.rx_freq
        expected_tx = legacy.tx_freq
        expected_rx_tone = legacy.rx_tone.upper()
        expected_tx_tone = legacy.tx_tone.upper()

        if (
            modern.rx_freq != expected_rx
            or modern.tx_freq != expected_tx
            or modern.rx_tone.upper() != expected_rx_tone
            or modern.tx_tone.upper() != expected_tx_tone
        ):
            raise ValueError(
                f"round-trip validation failed on channel {modern.index}: "
                f"expected ({expected_rx}, {expected_tx}, {expected_rx_tone}, {expected_tx_tone}), "
                f"got ({modern.rx_freq}, {modern.tx_freq}, {modern.rx_tone}, {modern.tx_tone})"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert legacy radio DAT channel data into newer CPS DAT format."
    )
    parser.add_argument("--old", default="123.dat", type=Path, help="legacy DAT source")
    parser.add_argument(
        "--template", default="124.dat", type=Path, help="new CPS DAT template"
    )
    parser.add_argument(
        "--output", default="123_converted.dat", type=Path, help="converted DAT output"
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="decode the output and print a validation report after conversion",
    )
    args = parser.parse_args()

    convert(args.old, args.template, args.output)
    if args.report:
        print_report(args.old, args.output)


if __name__ == "__main__":
    main()
