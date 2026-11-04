#!/usr/bin/env python3
"""Send UART2 test samples and plot returned VOFA+ JustFloat ADC data."""

from __future__ import annotations

import argparse
import math
import struct
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Iterator


FRAME_START = 0xAA
FRAME_END = 0x55
INT16_MIN = -32768
INT16_MAX = 32767
WAVEFORMS = ("sine", "square", "triangle", "sawtooth")
TUI_FIELD_COUNT = 6
FFT_POINT_COUNT = 64
FIRMWARE_FFT_SAMPLE_RATE_HZ = 100.0
JUSTFLOAT_TAIL = b"\x00\x00\x80\x7f"
JUSTFLOAT_FRAME_SIZE = 8
RETURN_WAVEFORM_CAPACITY = 512
RETURN_WAVEFORM_PLOT_HEIGHT = 5
GENERATED_WAVEFORM_PLOT_HEIGHT = 3


@dataclass(frozen=True)
class FFTExpectation:
    bin_index: int
    board_peak_hz: float
    frame_duration_seconds: float
    sample_rate_matches: bool


@dataclass
class JustFloatParser:
    """Incrementally decode float32 little-endian + VOFA+ JustFloat tail."""

    buffer: bytearray = field(default_factory=bytearray)
    discarded_bytes: int = 0

    def reset(self) -> None:
        self.buffer.clear()
        self.discarded_bytes = 0

    def feed(self, data: bytes) -> list[float]:
        if data:
            self.buffer.extend(data)

        values: list[float] = []
        while True:
            tail_index = self.buffer.find(JUSTFLOAT_TAIL)
            if tail_index < 0:
                # A partial tail and the four preceding value bytes may span reads.
                maximum_pending = JUSTFLOAT_FRAME_SIZE - 1
                if len(self.buffer) > maximum_pending:
                    discard_count = len(self.buffer) - maximum_pending
                    del self.buffer[:discard_count]
                    self.discarded_bytes += discard_count
                break

            if tail_index < 4:
                discard_count = tail_index + len(JUSTFLOAT_TAIL)
                del self.buffer[:discard_count]
                self.discarded_bytes += discard_count
                continue

            value_start = tail_index - 4
            if value_start > 0:
                del self.buffer[:value_start]
                self.discarded_bytes += value_start
                tail_index = 4

            value = struct.unpack("<f", self.buffer[:4])[0]
            del self.buffer[: tail_index + len(JUSTFLOAT_TAIL)]
            if math.isfinite(value):
                values.append(value)
            else:
                self.discarded_bytes += JUSTFLOAT_FRAME_SIZE

        return values


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Send UART2 waveform samples and monitor returned JustFloat ADC data."
        )
    )
    parser.add_argument(
        "--port",
        help="Serial device, for example /dev/ttyUSB0 or COM5.",
    )
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument(
        "--wave",
        choices=WAVEFORMS,
        default="sine",
    )
    parser.add_argument(
        "--frequency",
        type=float,
        default=1.0,
        help="Waveform frequency in Hz (default: 1).",
    )
    parser.add_argument(
        "--sample-rate",
        type=float,
        default=100.0,
        help="Samples sent per second (default: 100).",
    )
    parser.add_argument(
        "--amplitude",
        type=int,
        default=1000,
        help="Peak amplitude in signed sample units (default: 1000).",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="DC offset in signed sample units (default: 0).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Run time in seconds; 0 sends until Ctrl+C (default: 0).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not open a serial port; print generated sample frames.",
    )
    parser.add_argument(
        "--preview-count",
        type=int,
        default=16,
        help="Number of frames printed by --dry-run (default: 16).",
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="List serial ports and exit.",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help=(
            "Open the interactive sender and UART2 JustFloat return "
            "waveform monitor."
        ),
    )
    return parser.parse_args()


def validate_arguments(args: argparse.Namespace) -> None:
    if args.baud <= 0:
        raise ValueError("--baud must be greater than 0")
    if args.frequency <= 0.0:
        raise ValueError("--frequency must be greater than 0")
    if args.sample_rate <= 0.0:
        raise ValueError("--sample-rate must be greater than 0")
    if args.frequency >= args.sample_rate / 2.0:
        raise ValueError(
            "--frequency must be lower than half of --sample-rate "
            "to avoid aliasing"
        )
    if args.amplitude < 0:
        raise ValueError("--amplitude must be 0 or greater")
    if args.duration < 0.0:
        raise ValueError("--duration must be 0 or greater")
    if args.preview_count <= 0:
        raise ValueError("--preview-count must be greater than 0")
    if args.offset - args.amplitude < INT16_MIN:
        raise ValueError("offset - amplitude is below signed int16 range")
    if args.offset + args.amplitude > INT16_MAX:
        raise ValueError("offset + amplitude is above signed int16 range")
    if not args.dry_run and not args.list_ports and not args.tui and not args.port:
        raise ValueError("--port is required unless --dry-run or --tui is used")


def calculate_fft_expectation(
    frequency: float, sample_rate: float
) -> FFTExpectation:
    normalized_bin = frequency * FFT_POINT_COUNT / sample_rate
    bin_index = int(math.floor(normalized_bin + 0.5))
    bin_index = min(FFT_POINT_COUNT // 2, max(1, bin_index))
    board_bin_width_hz = FIRMWARE_FFT_SAMPLE_RATE_HZ / FFT_POINT_COUNT
    return FFTExpectation(
        bin_index=bin_index,
        board_peak_hz=bin_index * board_bin_width_hz,
        frame_duration_seconds=FFT_POINT_COUNT / sample_rate,
        sample_rate_matches=math.isclose(
            sample_rate,
            FIRMWARE_FFT_SAMPLE_RATE_HZ,
            rel_tol=0.0,
            abs_tol=0.001,
        ),
    )


def print_fft_summary(frequency: float, sample_rate: float) -> None:
    expectation = calculate_fft_expectation(frequency, sample_rate)
    board_bin_width_hz = FIRMWARE_FFT_SAMPLE_RATE_HZ / FFT_POINT_COUNT
    print(
        f"Board UART2 FFT: {FFT_POINT_COUNT} points, "
        f"configured sample rate {FIRMWARE_FFT_SAMPLE_RATE_HZ:g} samples/s, "
        f"bin {board_bin_width_hz:g} Hz, "
        f"range 0..{FIRMWARE_FFT_SAMPLE_RATE_HZ / 2.0:g} Hz."
    )
    print(
        f"Expected OLED peak: bin {expectation.bin_index}, "
        f"about {expectation.board_peak_hz:g} Hz; "
        f"one {FFT_POINT_COUNT}-sample frame takes "
        f"{expectation.frame_duration_seconds:.3f} s."
    )
    if not expectation.sample_rate_matches:
        print(
            "warning: sender sample rate does not match firmware "
            f"FFT_ANALYSIS_UART2_SAMPLE_RATE_HZ="
            f"{FIRMWARE_FFT_SAMPLE_RATE_HZ:g}; OLED frequency will be scaled",
            file=sys.stderr,
        )


def normalized_waveform(wave: str, phase: float) -> float:
    if wave == "sine":
        return math.sin(2.0 * math.pi * phase)
    if wave == "square":
        return 1.0 if phase < 0.5 else -1.0
    if wave == "triangle":
        return 1.0 - (4.0 * abs(phase - 0.5))
    if wave == "sawtooth":
        return (2.0 * phase) - 1.0
    raise ValueError(f"unsupported waveform: {wave}")


def generate_samples(
    wave: str,
    frequency: float,
    sample_rate: float,
    amplitude: int,
    offset: int,
) -> Iterator[int]:
    sample_index = 0
    while True:
        phase = ((sample_index * frequency) / sample_rate) % 1.0
        normalized = normalized_waveform(wave, phase)
        sample = int(round(offset + (amplitude * normalized)))
        yield max(INT16_MIN, min(INT16_MAX, sample))
        sample_index += 1


def encode_frame(sample: int) -> bytes:
    unsigned_sample = sample & 0xFFFF
    return bytes(
        (
            FRAME_START,
            (unsigned_sample >> 8) & 0xFF,
            unsigned_sample & 0xFF,
            FRAME_END,
        )
    )


def import_pyserial():
    try:
        import serial  # type: ignore
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "pyserial is not installed; install tools/requirements.txt "
            "inside a Python virtual environment"
        ) from error
    return serial


def get_serial_ports() -> list[tuple[str, str]]:
    import_pyserial()
    from serial.tools import list_ports  # type: ignore

    return [(port.device, port.description) for port in list_ports.comports()]


def list_serial_ports() -> None:
    ports = get_serial_ports()
    if not ports:
        print("No serial ports found.")
        return

    for device, description in ports:
        print(f"{device}: {description}")


def preview_frames(args: argparse.Namespace) -> None:
    print_fft_summary(args.frequency, args.sample_rate)
    samples = generate_samples(
        args.wave,
        args.frequency,
        args.sample_rate,
        args.amplitude,
        args.offset,
    )
    for index in range(args.preview_count):
        sample = next(samples)
        encoded = " ".join(f"{byte:02X}" for byte in encode_frame(sample))
        print(f"{index:04d}: sample={sample:6d} frame={encoded}")


def send_frames(args: argparse.Namespace) -> None:
    serial = import_pyserial()
    samples = generate_samples(
        args.wave,
        args.frequency,
        args.sample_rate,
        args.amplitude,
        args.offset,
    )
    interval = 1.0 / args.sample_rate
    start_time = time.monotonic()
    next_send_time = start_time
    sent_count = 0

    print(
        f"Opening {args.port} at {args.baud} baud: "
        f"{args.wave} {args.frequency:g} Hz, "
        f"sample rate {args.sample_rate:g} Hz, "
        f"amplitude {args.amplitude}, offset {args.offset}"
    )
    print_fft_summary(args.frequency, args.sample_rate)

    with serial.Serial(args.port, args.baud, timeout=1) as serial_port:
        try:
            while True:
                now = time.monotonic()
                if args.duration > 0.0 and now - start_time >= args.duration:
                    break

                serial_port.write(encode_frame(next(samples)))
                sent_count += 1
                next_send_time += interval

                delay = next_send_time - time.monotonic()
                if delay > 0.0:
                    time.sleep(delay)
                elif delay < -interval:
                    next_send_time = time.monotonic()
        except KeyboardInterrupt:
            print("\nStopped by user.")

    elapsed = max(time.monotonic() - start_time, 0.000001)
    print(
        f"Sent {sent_count} samples in {elapsed:.2f} s "
        f"({sent_count / elapsed:.1f} samples/s)."
    )


@dataclass
class TUIState:
    baud: int
    duration: float
    preferred_port: str | None
    ports: list[tuple[str, str]]
    selected_field: int
    port_index: int
    wave_index: int
    frequency: float
    sample_rate: float
    amplitude: int
    offset: int
    sending: bool = False
    serial_port: object | None = None
    samples: Iterator[int] | None = None
    next_send_time: float = 0.0
    start_time: float = 0.0
    sent_count: int = 0
    received_count: int = 0
    received_samples: deque[float] = field(
        default_factory=lambda: deque(maxlen=RETURN_WAVEFORM_CAPACITY)
    )
    justfloat_parser: JustFloatParser = field(default_factory=JustFloatParser)
    last_receive_time: float = 0.0
    status: str = "DISCONNECTED"
    message: str = "Press R to refresh serial ports."


def create_tui_state(args: argparse.Namespace) -> TUIState:
    return TUIState(
        baud=args.baud,
        duration=args.duration,
        preferred_port=args.port,
        ports=[],
        selected_field=0,
        port_index=0,
        wave_index=WAVEFORMS.index(args.wave),
        frequency=args.frequency,
        sample_rate=args.sample_rate,
        amplitude=args.amplitude,
        offset=args.offset,
    )


def tui_current_port(state: TUIState) -> str | None:
    if not state.ports:
        return None
    return state.ports[state.port_index][0]


def tui_refresh_ports(state: TUIState) -> None:
    previous_port = tui_current_port(state) or state.preferred_port
    try:
        state.ports = get_serial_ports()
    except RuntimeError as error:
        state.ports = []
        state.port_index = 0
        state.message = str(error)
        return

    if state.preferred_port and all(
        device != state.preferred_port for device, _ in state.ports
    ):
        state.ports.append((state.preferred_port, "command-line port"))

    state.port_index = 0
    if previous_port:
        for index, (device, _) in enumerate(state.ports):
            if device == previous_port:
                state.port_index = index
                break

    state.message = (
        f"Found {len(state.ports)} serial port(s)."
        if state.ports
        else "No serial ports found. Connect a 3.3 V USB-TTL adapter."
    )


def tui_rebuild_generator(state: TUIState) -> None:
    state.samples = generate_samples(
        WAVEFORMS[state.wave_index],
        state.frequency,
        state.sample_rate,
        state.amplitude,
        state.offset,
    )
    state.next_send_time = time.monotonic()


def tui_close_port(state: TUIState, message: str = "Serial port closed.") -> None:
    if state.serial_port is not None:
        try:
            state.serial_port.close()  # type: ignore[attr-defined]
        except Exception:
            pass
    state.serial_port = None
    state.samples = None
    state.sending = False
    state.status = "DISCONNECTED"
    state.message = message


def tui_open_port(state: TUIState) -> bool:
    port = tui_current_port(state)
    if port is None:
        state.message = "No serial port selected. Connect an adapter and press R."
        return False

    try:
        serial = import_pyserial()
        state.serial_port = serial.Serial(port, state.baud, timeout=0)
    except Exception as error:
        state.serial_port = None
        state.message = f"Open failed: {error}"
        return False

    state.received_count = 0
    state.received_samples.clear()
    state.justfloat_parser.reset()
    state.last_receive_time = 0.0
    state.status = "CONNECTED"
    state.message = f"Monitoring JustFloat return data from {port}."
    return True


def tui_toggle_port(state: TUIState) -> None:
    if state.serial_port is None:
        tui_open_port(state)
    else:
        tui_close_port(state)


def tui_stop_sending(state: TUIState, message: str = "Sending stopped.") -> None:
    state.samples = None
    state.sending = False
    state.status = (
        "CONNECTED" if state.serial_port is not None else "DISCONNECTED"
    )
    state.message = message


def tui_start_sending(state: TUIState) -> None:
    port = tui_current_port(state)
    if state.serial_port is None and not tui_open_port(state):
        return

    state.sent_count = 0
    state.start_time = time.monotonic()
    state.sending = True
    state.status = "SENDING"
    state.message = f"Sending frames to {port}."
    tui_rebuild_generator(state)


def tui_toggle_sending(state: TUIState) -> None:
    if state.sending:
        tui_stop_sending(state)
    else:
        tui_start_sending(state)


def tui_adjust_selected(state: TUIState, direction: int) -> None:
    if state.selected_field == 0:
        if state.ports:
            if state.serial_port is not None:
                tui_close_port(state, "Closed before changing serial port.")
            state.port_index = (state.port_index + direction) % len(state.ports)
    elif state.selected_field == 1:
        state.wave_index = (state.wave_index + direction) % len(WAVEFORMS)
    elif state.selected_field == 2:
        maximum_frequency = max(0.5, (state.sample_rate / 2.0) - 0.5)
        state.frequency = min(
            maximum_frequency,
            max(0.5, state.frequency + 0.5 * direction),
        )
    elif state.selected_field == 3:
        state.sample_rate = min(
            1000.0, max(10.0, state.sample_rate + 10.0 * direction)
        )
        maximum_frequency = max(0.5, (state.sample_rate / 2.0) - 0.5)
        state.frequency = min(state.frequency, maximum_frequency)
    elif state.selected_field == 4:
        maximum_amplitude = min(
            INT16_MAX - state.offset, state.offset - INT16_MIN
        )
        state.amplitude = min(
            maximum_amplitude, max(0, state.amplitude + 100 * direction)
        )
    elif state.selected_field == 5:
        minimum_offset = INT16_MIN + state.amplitude
        maximum_offset = INT16_MAX - state.amplitude
        state.offset = min(
            maximum_offset,
            max(minimum_offset, state.offset + 100 * direction),
        )

    if state.sending and state.selected_field != 0:
        tui_rebuild_generator(state)
        state.message = "Parameters updated while sending."


def tui_send_due_frames(state: TUIState) -> None:
    if not state.sending or state.serial_port is None or state.samples is None:
        return

    now = time.monotonic()
    if state.duration > 0.0 and now - state.start_time >= state.duration:
        tui_stop_sending(state, "Configured duration completed.")
        return

    interval = 1.0 / state.sample_rate
    burst_count = 0
    try:
        while now >= state.next_send_time and burst_count < 32:
            state.serial_port.write(  # type: ignore[attr-defined]
                encode_frame(next(state.samples))
            )
            state.sent_count += 1
            burst_count += 1
            state.next_send_time += interval
        if now - state.next_send_time > interval * 32.0:
            state.next_send_time = now
    except Exception as error:
        tui_close_port(state, f"Serial write failed: {error}")


def tui_receive_available(state: TUIState) -> None:
    if state.serial_port is None:
        return

    try:
        available = state.serial_port.in_waiting  # type: ignore[attr-defined]
        if available <= 0:
            return
        data = state.serial_port.read(  # type: ignore[attr-defined]
            min(available, 4096)
        )
        values = state.justfloat_parser.feed(data)
        if values:
            state.received_samples.extend(values)
            state.received_count += len(values)
            state.last_receive_time = time.monotonic()
    except Exception as error:
        tui_close_port(state, f"Serial read failed: {error}")


def build_waveform_preview(wave: str, width: int, height: int) -> list[str]:
    grid = [[" " for _ in range(width)] for _ in range(height)]
    center_row = height // 2
    for column in range(width):
        grid[center_row][column] = "-"

    for column in range(width):
        phase = ((column * 2.0) / max(width - 1, 1)) % 1.0
        normalized = normalized_waveform(wave, phase)
        row = int(round((1.0 - normalized) * (height - 1) / 2.0))
        row = max(0, min(height - 1, row))
        grid[row][column] = "*"
    return ["".join(row) for row in grid]


def build_sample_plot(
    samples: list[float], width: int, height: int
) -> list[str]:
    if width <= 0 or height <= 0:
        return []
    if not samples:
        empty = "Waiting for UART2 JustFloat return data..."
        return [empty[:width].ljust(width)] + [" " * width] * (height - 1)

    visible = samples[-width:]
    minimum = min(visible)
    maximum = max(visible)
    if math.isclose(minimum, maximum, rel_tol=0.0, abs_tol=1e-12):
        padding = max(abs(minimum) * 0.05, 1.0)
        minimum -= padding
        maximum += padding

    grid = [[" " for _ in range(width)] for _ in range(height)]
    if minimum <= 0.0 <= maximum:
        zero_row = int(round(
            (maximum / (maximum - minimum)) * (height - 1)
        ))
        zero_row = max(0, min(height - 1, zero_row))
        for column in range(width):
            grid[zero_row][column] = "-"

    column_offset = width - len(visible)
    for index, sample in enumerate(visible):
        normalized = (maximum - sample) / (maximum - minimum)
        row = int(round(normalized * (height - 1)))
        row = max(0, min(height - 1, row))
        grid[row][column_offset + index] = "*"

    return ["".join(row) for row in grid]


def tui_clear_received(state: TUIState) -> None:
    state.received_count = 0
    state.received_samples.clear()
    state.justfloat_parser.reset()
    state.last_receive_time = 0.0
    state.message = "Returned waveform buffer cleared."


def tui_safe_addstr(screen, row: int, column: int, value: str, attribute=0) -> None:
    height, width = screen.getmaxyx()
    if row < 0 or row >= height or column < 0 or column >= width:
        return
    try:
        screen.addstr(row, column, value[: max(width - column - 1, 0)], attribute)
    except Exception:
        pass


def tui_draw(screen, curses, state: TUIState) -> None:
    screen.erase()
    height, width = screen.getmaxyx()
    if height < 27 or width < 68:
        tui_safe_addstr(screen, 0, 0, "Terminal is too small.", curses.A_BOLD)
        tui_safe_addstr(screen, 1, 0, "Resize to at least 68 columns x 27 rows.")
        screen.refresh()
        return

    port = tui_current_port(state) or "<no serial port>"
    description = ""
    if state.ports:
        description = state.ports[state.port_index][1]
    field_values = (
        f"{port}  {description}",
        WAVEFORMS[state.wave_index],
        f"{state.frequency:.1f} Hz",
        f"{state.sample_rate:.0f} samples/s",
        str(state.amplitude),
        str(state.offset),
    )
    field_labels = (
        "Serial port",
        "Waveform",
        "Frequency",
        "Sample rate",
        "Amplitude",
        "Offset",
    )

    tui_safe_addstr(
        screen, 0, 2, "UART2 Waveform Sender / JustFloat Monitor", curses.A_BOLD
    )
    tui_safe_addstr(
        screen,
        1,
        2,
        "TX: AA+int16 BE+55   RX: float32 LE+00 00 80 7F",
    )
    for index, (label, value) in enumerate(zip(field_labels, field_values)):
        row = 3 + index
        attribute = curses.A_REVERSE if index == state.selected_field else 0
        tui_safe_addstr(screen, row, 2, f" {label:<12}: {value:<45} ", attribute)

    status_attribute = curses.A_BOLD
    tui_safe_addstr(screen, 10, 2, f"Status : {state.status}", status_attribute)
    tui_safe_addstr(
        screen,
        11,
        2,
        f"Samples: TX {state.sent_count}   RX {state.received_count}   "
        f"discarded bytes {state.justfloat_parser.discarded_bytes}",
    )
    if state.received_samples:
        returned = list(state.received_samples)
        latest = returned[-1]
        minimum = min(returned)
        maximum = max(returned)
        age = max(time.monotonic() - state.last_receive_time, 0.0)
        receive_summary = (
            f"Return : latest {latest:.3f}   min {minimum:.3f}   "
            f"max {maximum:.3f}   age {age:.2f}s"
        )
    else:
        receive_summary = "Return : no valid JustFloat sample received"
    tui_safe_addstr(screen, 12, 2, receive_summary)

    tui_safe_addstr(screen, 13, 2, "Returned waveform (latest samples):")
    preview_width = min(60, width - 6)
    for index, line in enumerate(
        build_sample_plot(
            list(state.received_samples),
            preview_width,
            RETURN_WAVEFORM_PLOT_HEIGHT,
        )
    ):
        tui_safe_addstr(screen, 14 + index, 3, line)

    tui_safe_addstr(screen, 19, 2, "Generated TX waveform preview:")
    for index, line in enumerate(
        build_waveform_preview(
            WAVEFORMS[state.wave_index],
            preview_width,
            GENERATED_WAVEFORM_PLOT_HEIGHT,
        )
    ):
        tui_safe_addstr(screen, 20 + index, 3, line)

    expectation = calculate_fft_expectation(state.frequency, state.sample_rate)
    board_bin_width_hz = FIRMWARE_FFT_SAMPLE_RATE_HZ / FFT_POINT_COUNT
    tui_safe_addstr(
        screen,
        23,
        2,
        f"FFT: {FFT_POINT_COUNT} pt, Fs {FIRMWARE_FFT_SAMPLE_RATE_HZ:g}, "
        f"bin {board_bin_width_hz:g} Hz; expected bin "
        f"{expectation.bin_index} -> {expectation.board_peak_hz:g} Hz",
    )

    if not expectation.sample_rate_matches:
        tui_safe_addstr(
            screen,
            24,
            2,
            f"Warning: board FFT Fs={FIRMWARE_FFT_SAMPLE_RATE_HZ:g}; "
            "OLED frequency will be scaled.",
            curses.A_BOLD,
        )

    tui_safe_addstr(
        screen,
        24 if expectation.sample_rate_matches else 25,
        2,
        "Arrows edit  SPACE TX  O port  C clear  R scan  Q quit",
    )
    tui_safe_addstr(
        screen,
        25 if expectation.sample_rate_matches else 26,
        2,
        state.message,
    )
    screen.refresh()


def tui_loop(screen, curses, args: argparse.Namespace) -> None:
    state = create_tui_state(args)
    try:
        curses.curs_set(0)
    except Exception:
        pass
    screen.keypad(True)
    screen.timeout(20)
    tui_refresh_ports(state)
    if args.port and tui_current_port(state) is not None:
        tui_open_port(state)

    try:
        while True:
            tui_send_due_frames(state)
            tui_receive_available(state)
            tui_draw(screen, curses, state)
            key = screen.getch()
            if key in (ord("q"), ord("Q")):
                break
            if key == curses.KEY_UP:
                state.selected_field = (
                    state.selected_field - 1
                ) % TUI_FIELD_COUNT
            elif key == curses.KEY_DOWN:
                state.selected_field = (
                    state.selected_field + 1
                ) % TUI_FIELD_COUNT
            elif key == curses.KEY_LEFT:
                tui_adjust_selected(state, -1)
            elif key == curses.KEY_RIGHT:
                tui_adjust_selected(state, 1)
            elif key == ord(" "):
                tui_toggle_sending(state)
            elif key in (ord("o"), ord("O")):
                tui_toggle_port(state)
            elif key in (ord("c"), ord("C")):
                tui_clear_received(state)
            elif key in (ord("r"), ord("R")):
                if state.serial_port is not None:
                    tui_close_port(state, "Closed before refreshing ports.")
                tui_refresh_ports(state)
    finally:
        tui_close_port(state, "TUI closed.")


def run_tui(args: argparse.Namespace) -> None:
    try:
        import curses
    except ModuleNotFoundError as error:
        raise RuntimeError("Python curses support is not installed") from error

    curses.wrapper(tui_loop, curses, args)


def main() -> int:
    args = parse_arguments()
    try:
        validate_arguments(args)
        if args.tui:
            run_tui(args)
        elif args.list_ports:
            list_serial_ports()
        elif args.dry_run:
            preview_frames(args)
        else:
            send_frames(args)
    except (ValueError, RuntimeError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped by user.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
