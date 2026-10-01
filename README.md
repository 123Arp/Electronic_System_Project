# Real-Time Spectrum Analyzer on STM32G474RE

An embedded real-time audio and RF spectrum analyzer firmware developed for the **STMicroelectronics NUCLEO-G474RE** development board (Arm® Cortex®-M4 with FPU & DSP instructions running at 170 MHz).

The system continuously samples an analog signal using **ADC1** triggered by hardware timer **TIM6**, buffers samples in circular DMA double buffers, performs a **1024-point Fast Fourier Transform (FFT)** with Hann windowing using **CMSIS-DSP**, and streams frequency magnitude spectra to a host PC over **USART2 via DMA** at **921,600 baud**.

---

## Features

- **Hardware-Timed Sampling**: TIM6 TRGO triggers ADC1 conversions at a precise **100 kSps** (Nyquist bandwidth: **0 – 50 kHz**).
- **Zero CPU Sampling Overhead**: ADC conversions stream directly into SRAM using DMA1 Channel 1 in circular double-buffered mode (ping-pong buffer).
- **DSP Optimization**:
  - DC bias cancellation (dynamic mean subtraction).
  - Pre-computed 1024-point **Hann window** application for minimal spectral leakage.
  - CMSIS-DSP **Real Fast Fourier Transform (`arm_rfft_fast_f32`)** leveraging hardware FPU instructions.
  - Real-time Euclidean magnitude computation (`arm_cmplx_mag_f32`).
- **High-Speed Binary Streaming**: 512 magnitude bins packed with header and frame ID transmitted via **USART2 DMA** at **921,600 baud**.
- **Frequency Resolution**: 
  $$\Delta f = \frac{f_s}{N} = \frac{100\,\text{kHz}}{1024} \approx 97.66\,\text{Hz / bin}$$
- **Built-in Diagnostic Test Generator**: Generates synthetic sinusoidal test waveforms in software (`test_mode = 1`) for verification without an external function generator.

---

## System Architecture & Data Pipeline

```
  [ Analog Input: PA0 ]
           │
           ▼
     ┌───────────┐         ┌─────────────────────────┐
     │ ADC1 12b  │ ◄────── │ TIM6 TRGO (100 kHz)     │
     └─────┬─────┘         └─────────────────────────┘
           │
     DMA1 Channel 1 (Circular Ping-Pong Buffer: 2048 Samples)
           │
     ┌─────┴────────────────────────┐
     ▼                              ▼
[ Half Buffer (1024 samples) ]   [ Second Half (1024 samples) ]
     │                              │
     └──────────────┬───────────────┘
                    ▼
          ┌────────────────────┐
          │ DC Offset Removal  │
          └─────────┬──────────┘
                    ▼
          ┌────────────────────┐
          │  Hann Windowing    │
          └─────────┬──────────┘
                    ▼
          ┌────────────────────┐
          │ CMSIS-DSP RFFT-F32 │
          └─────────┬──────────┘
                    ▼
          ┌────────────────────┐
          │ Magnitude Spectrum │
          └─────────┬──────────┘
                    ▼
     ┌───────────────────────────────┐
     │ Packed Binary Packet Format   │
     └──────────────┬────────────────┘
                    ▼
       USART2 TX via DMA (921,600 Baud)
                    │
                    ▼
             [ Host PC / GUI ]
```

---

## Hardware Pinout & Wiring

| Pin | Peripheral | Function | Description |
|:---|:---|:---|:---|
| **PA0** | `ADC1_IN1` | Analog Input | Signal input pin (0V to 3.3V max, AC-couple if needed) |
| **PA2** | `USART2_TX` | Serial TX | Transmit line connected to onboard ST-LINK VCP |
| **PA3** | `USART2_RX` | Serial RX | Receive line connected to onboard ST-LINK VCP |
| **PA5** | `GPIO_Output` | Status LED | User LED (LD2) on Nucleo board |
| **PC13** | `GPXTI13` | Pushbutton | User Button (B1) |

> [!WARNING]
> Do not apply voltages exceeding **3.3V** or below **0V** directly to pin **PA0**. If measuring AC signals or audio, use a DC biasing network (e.g. voltage divider setting baseline to 1.65V with input coupling capacitor).

---

## Packet Protocol Specification

The firmware transmits binary data packets over UART. Each frame is structured as follows:

```c
typedef struct __attribute__((packed)) {
    uint32_t header;            // Magic: 0xA55AA55A
    uint32_t frame_id;          // Monotonically increasing frame counter
    uint16_t fft_bins;          // Number of magnitude bins (512)
    uint16_t reserved;          // Reserved / alignment padding (0x0000)
    float    magnitude[512];    // 512 single-precision IEEE 754 float values
} FFTPacket_t;
```

- **Packet Total Size**: 4 + 4 + 2 + 2 + (512 * 4) = **2060 bytes**
- **UART Parameters**: 921,600 Baud, 8 Data Bits, 1 Stop Bit, No Parity (8N1).

---

## Configuration: Test Mode vs Live ADC

In `Core/Src/main.c`, switch between the simulated signal generator and live analog acquisition via `test_mode`:

```c
/* Set to 0 for live ADC acquisition on PA0 */
/* Set to 1 for simulated internal test wave */
static uint8_t test_mode = 0;
```

---

## Python Host Visualizer Example

You can visualize the live spectrum using Python, `pyserial`, and `matplotlib` or `pyqtgraph`:

```python
import struct
import serial
import numpy as np
import matplotlib.pyplot as plt

PORT = "COM3"  # Adjust for your ST-Link VCP port
BAUD = 921600
HEADER = 0xA55AA55A
BINS = 512
SAMPLE_RATE = 100000

ser = serial.Serial(PORT, BAUD, timeout=1)
freqs = np.linspace(0, SAMPLE_RATE / 2, BINS)

plt.ion()
fig, ax = plt.subplots(figsize=(10, 5))
line, = ax.plot(freqs, np.zeros(BINS))
ax.set_ylim(0, 100000)
ax.set_xlabel("Frequency (Hz)")
ax.set_ylabel("Magnitude")
ax.set_title("Real-Time STM32 Spectrum Analyzer")
ax.grid(True)

def read_frame():
    while True:
        raw_header = ser.read(4)
        if len(raw_header) < 4:
            continue
        hdr = struct.unpack("<I", raw_header)[0]
        if hdr == HEADER:
            payload = ser.read(4 + 2 + 2 + BINS * 4)
            if len(payload) == (8 + BINS * 4):
                frame_id, bins, _ = struct.unpack("<IHH", payload[:8])
                mags = struct.unpack(f"<{BINS}f", payload[8:])
                return mags

while True:
    try:
        mag = read_frame()
        line.set_ydata(mag)
        ax.set_ylim(0, max(max(mag) * 1.1, 100))
        plt.pause(0.001)
    except KeyboardInterrupt:
        break

ser.close()
```

---

## Project Structure

```
.
├── Core/
│   ├── Inc/
│   │   ├── main.h                 # Peripheral declarations & defines
│   │   ├── stm32g4xx_hal_conf.h   # HAL configuration
│   │   └── stm32g4xx_it.h         # Interrupt handlers prototypes
│   ├── Src/
│   │   ├── main.c                 # Spectrum analyzer logic & DSP loop
│   │   ├── stm32g4xx_hal_msp.c    # Low-level hardware initialization
│   │   ├── stm32g4xx_it.c         # ISR callbacks
│   │   ├── system_stm32g4xx.c     # CMSIS system initialization
│   │   ├── syscalls.c
│   │   └── sysmem.c
│   └── Startup/
│       └── startup_stm32g474retx.s# Vector table and startup code
├── Drivers/
│   ├── CMSIS/                     # CMSIS Core and DSP Library
│   │   └── DSP/                   # Complex & transform DSP functions
│   ├── BSP/                       # Board Support Package for Nucleo
│   └── STM32G4xx_HAL_Driver/      # Hardware Abstraction Layer
├── ppjjjjjjjj.ioc                 # STM32CubeMX hardware configuration
├── STM32G474RETX_FLASH.ld         # Linker script for Flash execution
├── STM32G474RETX_RAM.ld           # Linker script for RAM execution
└── README.md
```

---

## Getting Started

### Prerequisites

- **IDE**: [STM32CubeIDE](https://www.st.com/en/development-tools/stm32cubeide.html) (v1.14.0 or newer).
- **Toolchain**: `arm-none-eabi-gcc` (bundled with STM32CubeIDE).
- **Hardware**: NUCLEO-G474RE board and a Micro-USB cable.

### Building & Running

1. **Clone the repository**:
   ```bash
   git clone https://github.com/123Arp/Electronic_System_Project.git
   ```
2. **Open in STM32CubeIDE**:
   - File > Open Projects from File System...
   - Select the cloned repository directory.
3. **Build**:
   - Click the hammer icon or press `Ctrl + B` to compile.
4. **Flash**:
   - Connect your NUCLEO-G474RE board via USB.
   - Run / Debug (`F11` or green play button).
5. **Monitor Output**:
   - Connect to the ST-Link COM port at **921,600 baud, 8N1**.

---

## License

This project is licensed under the Apache 2.0 / BSD 3-Clause License compatible with CMSIS and STM32Cube HAL libraries. See [LICENSE.txt](Drivers/CMSIS/LICENSE.txt) for details.
