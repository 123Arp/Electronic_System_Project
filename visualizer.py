#!/usr/bin/env python3
"""
Real-Time STM32 Spectrum Analyzer Host Visualizer
Receives binary FFT packets (2060 bytes) from STM32 over UART DMA at 921,600 baud
and plots the real-time frequency spectrum.
"""

import sys
import time
import struct
import argparse
import serial
import serial.tools.list_ports
import numpy as np
import matplotlib.pyplot as plt

PACKET_HEADER = 0xA55AA55A
DEFAULT_BINS = 512
DEFAULT_SAMPLE_RATE = 48000
DEFAULT_BAUD = 921600


def find_stm32_port():
    """Auto-detect ST-Link Virtual COM Port if available."""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        desc = (port.description or "").lower()
        hwid = (port.hwid or "").lower()
        if "stlink" in desc or "st-link" in desc or "stm" in desc or "0483:" in hwid:
            return port.device
    if ports:
        return ports[0].device
    return "COM3"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Real-Time STM32 Spectrum Analyzer Host Visualizer"
    )
    parser.add_argument(
        "-p", "--port",
        type=str,
        default=None,
        help="Serial port (e.g. COM3 or /dev/ttyACM0). Auto-detects if omitted.",
    )
    parser.add_argument(
        "-b", "--baud",
        type=int,
        default=DEFAULT_BAUD,
        help=f"Baud rate (default: {DEFAULT_BAUD})",
    )
    parser.add_argument(
        "-s", "--samplerate",
        type=int,
        default=DEFAULT_SAMPLE_RATE,
        help=f"Sampling frequency in Hz (default: {DEFAULT_SAMPLE_RATE})",
    )
    parser.add_argument(
        "-n", "--bins",
        type=int,
        default=DEFAULT_BINS,
        help=f"Number of FFT bins (default: {DEFAULT_BINS})",
    )
    return parser.parse_args()


def read_fft_frame(ser, bins=DEFAULT_BINS):
    """Synchronize with magic header 0xA55AA55A and unpack FFT packet."""
    while True:
        raw_byte = ser.read(1)
        if len(raw_byte) == 0:
            return None
        if raw_byte[0] == 0x5A:
            # Check remaining 3 bytes of header
            rest_hdr = ser.read(3)
            if len(rest_hdr) == 3:
                full_hdr_bytes = raw_byte + rest_hdr
                hdr = struct.unpack("<I", full_hdr_bytes)[0]
                if hdr == PACKET_HEADER:
                    # Header matched, read payload: frame_id (4), bins (2), reserved (2), data (bins * 4)
                    payload_len = 4 + 2 + 2 + (bins * 4)
                    payload = ser.read(payload_len)
                    if len(payload) == payload_len:
                        frame_id, num_bins, _ = struct.unpack("<IHH", payload[:8])
                        magnitudes = struct.unpack(f"<{num_bins}f", payload[8:])
                        return frame_id, np.array(magnitudes, dtype=np.float32)


def main():
    args = parse_args()
    port = args.port or find_stm32_port()

    print("=" * 60)
    print("  Real-Time STM32 Spectrum Analyzer Host Visualizer")
    print("=" * 60)
    print(f"Connecting to port: {port} at {args.baud} baud...")

    try:
        ser = serial.Serial(port, args.baud, timeout=1.0)
    except Exception as e:
        print(f"Error opening serial port {port}: {e}")
        print("Available ports:")
        for p in serial.tools.list_ports.comports():
            print(f"  - {p.device}: {p.description}")
        sys.exit(1)

    freqs = np.linspace(0, args.samplerate / 2, args.bins)
    df = args.samplerate / (2 * args.bins)
    print(f"Sampling Rate: {args.samplerate} Hz | Bins: {args.bins} | Resolution: {df:.2f} Hz/bin")
    print("Live plot started. Close plot window or press Ctrl+C to stop.")

    plt.ion()
    fig, ax = plt.subplots(figsize=(11, 5.5))
    fig.canvas.manager.set_window_title("Real-Time STM32 Spectrum Analyzer")
    fig.patch.set_facecolor("#181818")
    ax.set_facecolor("#0e0e0e")

    (line,) = ax.plot(freqs, np.zeros(args.bins), color="#00ffcc", lw=1.6)
    peak_text = ax.text(
        0.02, 0.92, "",
        transform=ax.transAxes,
        color="#ffff00",
        fontsize=11,
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.4", fc="#222222", ec="#444444", alpha=0.9),
    )

    ax.set_xlim(0, args.samplerate / 2)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Frequency (Hz)", color="white", fontsize=11)
    ax.set_ylabel("Magnitude (Normalized Physical Scale)", color="white", fontsize=11)
    ax.set_title(
        f"Real-Time FFT Spectrum ({args.samplerate} Sps, {args.bins} bins)",
        color="white",
        fontsize=13,
        pad=10,
    )
    ax.tick_params(colors="white")
    ax.grid(True, color="#333333", linestyle="--", linewidth=0.7)

    frame_counter = 0
    fps_start_time = time.time()

    try:
        while plt.fignum_exists(fig.number):
            result = read_fft_frame(ser, args.bins)
            if result is None:
                continue

            frame_id, mag = result
            frame_counter += 1

            # Update spectral line
            line.set_ydata(mag)

            # Detect dominant peak (excluding DC bin 0)
            if len(mag) > 1:
                peak_idx = 1 + np.argmax(mag[1:])
                peak_freq = freqs[peak_idx]
                peak_val = mag[peak_idx]
            else:
                peak_freq, peak_val = 0.0, 0.0

            # Dynamic Y limit
            max_val = np.max(mag)
            current_ymax = ax.get_ylim()[1]
            if max_val > current_ymax * 0.9 or max_val < current_ymax * 0.3:
                new_ymax = max(max_val * 1.25, 10.0)
                ax.set_ylim(0, new_ymax)

            # Update FPS and peak readout
            if frame_counter % 5 == 0:
                elapsed = time.time() - fps_start_time
                fps = frame_counter / elapsed if elapsed > 0 else 0
                peak_text.set_text(
                    f"Peak: {peak_freq:.1f} Hz (Mag: {peak_val:.1f}) | Frame: {frame_id} | {fps:.1f} FPS"
                )

            plt.pause(0.001)

    except KeyboardInterrupt:
        print("\nExiting visualizer...")
    finally:
        ser.close()
        print("Serial port closed.")


if __name__ == "__main__":
    main()
