---
triggers: 拆题, 读题, 赛题, 方案, 视觉题, 识别
---
> 原样收录自 Loclove/Electronics-Design-Competition-Skill@cd46b72 `references/task-decision-tree.md`（用户提供的参考资料，见 docs/参考来源.md）。

# Task Decision Tree

Use this file immediately after reading a contest problem statement or user request. Lingmou may write from scratch, but it should never write blindly: first split the task into layers and decide the pipeline.

## Task Layers

Break every vision task into these layers:

1. Problem constraints: target type, scoring priority, timing, precision, allowed hardware, light conditions, movement state.
2. Capture layer: board, firmware, camera channel, pixel format, frame rate, exposure, lens, display path.
3. Preprocessing layer: grayscale/color conversion, thresholding, blur, morphology, histogram/local correction, downsampling.
4. Detection layer: blob, contour, rectangle, corner, circle, line, template, PnP, YOLO/KPU, or hybrid cascade.
5. Validation layer: geometry, area, aspect ratio, edge distance, black/white sampling, temporal consistency, prediction consistency.
6. Tracking layer: ROI, EMA, alpha-beta, Kalman, deadband, coast prediction, corner smoothing.
7. Output layer: coordinate frame, serial packet, control error, lock/lost flag, rate limit, heartbeat.
8. Display/debug layer: FPS upper-left only by default; optional overlays appear only when the user needs a visual check, with lower OSD refresh rate when needed.
9. Tuning/recovery layer: what to adjust when FPS is low, jitter appears, target is lost, or serial is wrong.

## Zero-To-One Vs Example-First

Write from scratch when:

- The platform API is known and simple.
- The requested task has no useful baseline.
- The user wants a clean OpenCV/cv_lite framework.
- Existing examples are lower quality than a direct implementation.

Start from firmware examples or YYB code when:

- The firmware API is fragile or poorly documented.
- Camera/display/UART initialization is board-specific.
- A demo already runs on the target board.
- The user asks to optimize an existing program.

In both paths, the final design should still be multi-channel.

## Specialized High-FPS Decision

Before selecting a detector, choose the target's measurement model:

```text
coarse acquisition -> per-frame refinement -> validation gates -> coherent tracking -> recovery trigger
```

Prefer specialized staged measurement over one-shot generic detection when FPS, jitter, or latency matters. A detector may find the target occasionally; a measurement model should estimate the needed physical state every frame.

## Default Decision Tree

```text
Read problem statement
-> identify target and scoring bottleneck
-> choose board/firmware path
-> choose zero-to-one or example-first
-> build multi-channel pipeline
-> choose target-specific measurement model
-> choose coarse acquisition and per-frame refinement
-> add validation filters
-> add tracking/smoothing
-> add serial/control output
-> add clean left-top FPS display; optional overlays only when needed
-> tune with measured feedback
```

## Multi-Channel Architecture

Always plan these channels:

| Channel | Resolution | Purpose | Notes |
| --- | --- | --- | --- |
| Recognition/control | Low or task-sized | Fast target detection and control output | Lower this first to protect FPS |
| Validation/refinement | ROI or occasional high-res crop | Reject false positives, refine corners/circle/center | Run less often if CPU-bound |
| Display/debug | LCD/IDE/window size | FPS-only clean preview by default | Other overlays require user need or debug flag |
| Serial/control | Packet/event rate | Send newest stable result | Reuse packet objects when possible |

If a board cannot run true parallel channels, emulate them with frame scheduling: detect every N frames, track every frame, display every M frames, validate only on ROI.

## Strategy Selection

| Target/task | First-choice strategy | Fallback |
| --- | --- | --- |
| Black-white paper/rectangle | grayscale threshold + contour/corners + black/white validation | cv_lite rectangles, line intersections |
| Color block/blob | HSV/LAB threshold + morphology + blob geometry | RGB888 cv_lite blob threshold |
| Color line/track | HSV/LAB mask + eight-neighborhood/contour tracing | RGB threshold + ROI |
| Laser/LED spot | exposure lock + color/brightness blob + deadband | max bright component + color ratio |
| Ring/circle | radius-band coarse detection + radial/edge refinement + circle fit | pure Hough only for quick demos |
| Line following | threshold mask + eight-neighborhood tracing | contour centerline + PID |
| QR/code/text | dedicated decoder/model | ROI crop + lower display frequency |
| Complex object | OpenCV/cv_lite cascade | KPU/YOLO/YOLO-OBB |
