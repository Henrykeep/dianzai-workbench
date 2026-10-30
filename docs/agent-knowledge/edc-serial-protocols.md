---
triggers: 串口协议, uart, 通信协议, 帧格式, 校验
---
> 原样收录自 Loclove/Electronics-Design-Competition-Skill@cd46b72 `references/serial-protocols.md`（用户提供的参考资料，见 docs/参考来源.md）。

# Serial Protocols

Use this file when the user needs UART, USB serial, CAN, SPI, I2C, or another control link.

## Required Serial Question

Ask whether serial output is needed. If yes, ask:

- Link type: UART, USB serial, CAN, SPI, I2C, or vendor-specific.
- Port/pins: TX/RX pins, FPIOA mapping, `/dev/tty*`, COM port, or board connector.
- Baud/settings: baud rate, parity, stop bits, byte order.
- Payload: center coordinates, corners, target lock flag, distance, yaw/pitch error, FPS, or debug state.
- Coordinate frame: detection resolution, display resolution, original sensor resolution, or normalized coordinates.
- Packet format: binary with checksum, ASCII line, JSON line, or legacy format.
- Send cadence: every frame, every N frames, only locked, include coast/miss state, or heartbeat when lost.

Do not invent a serial packet when the downstream controller already has a protocol.

## Packet Templates

Use one of these only when the user has no existing protocol.

### Binary xy_u16

Use for precise display/control coordinates:

```text
55 AA XL XH YL YH CHECKSUM
CHECKSUM = sum(first 6 bytes) & 0xFF
X/Y = little-endian unsigned 16-bit in declared coordinate frame
```

### Binary xy_lock_u16

Use when the controller needs lock state:

```text
55 AA LOCK XL XH YL YH CHECKSUM
LOCK = 1 locked, 0 lost/coasting
CHECKSUM = sum(first 7 bytes) & 0xFF
```

### ASCII

Use for debugging and PC tools:

```text
T,x,y,lock,fps\n
```

### Legacy u8

Use only when existing firmware expects 0-255 scaled coordinates. State the scaling and inversion explicitly.

## Serial Safety

- Keep serial sending non-blocking or lightweight.
- Send the newest target state; drop old states when necessary.
- Include a lost-target/heartbeat behavior so STM32 or gimbal code can fail safe.
- Print debug logs less often than serial packets, because printing can reduce FPS.
