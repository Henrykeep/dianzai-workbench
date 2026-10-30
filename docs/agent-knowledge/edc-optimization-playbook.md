---
triggers: 帧率, 识别慢, 优化视觉, fps, 识别率
---
> 原样收录自 Loclove/Electronics-Design-Competition-Skill@cd46b72 `references/optimization-playbook.md`（用户提供的参考资料，见 docs/参考来源.md）。

# Optimization Playbook

Use this file when choosing or improving a vision pipeline.

## Pipeline Selection

Prefer this order unless the user chooses otherwise:

1. Target-specific staged measurement model: coarse acquisition, per-frame refinement, validation, tracking, recovery.
2. OpenCV/cv_lite accelerated primitives used inside that staged model.
3. Firmware/SDK example adapted in place when documentation is weak or platform APIs are fragile.
4. Vendor image primitives with similar contour/blob/threshold APIs.
5. Lightweight custom math only where the platform lacks an accelerated primitive.
6. Neural detection only when classical vision is unstable or the target class is visually complex.

Prefer adapting a runnable example over a blank rewrite. The user's pattern is "from 1 to infinity": establish or locate a working baseline, then stack improvements.

Do not confuse an API primitive with a full solution. Hough, blobs, contours, thresholds, and neural models are acquisition tools; high-FPS control needs a staged measurement pipeline around them.

## Multi-Channel Mixed Processing

The final implementation must be multi-channel unless the platform physically cannot support separate buffers or staged processing. When true parallel channels are unavailable, emulate them with staged per-frame work.

- Detection/control channel: low resolution, grayscale or task-specific color space, optimized for target center/corners.
- Feature validation channel: optional crop/ROI or color channel for rejecting false positives.
- Display/debug channel: clean high-res or LCD-size preview, FPS-only by default, optional overlays updated slower if needed.

Map detection coordinates back to display/control coordinates with explicit scale factors. Keep all serial coordinates in one declared coordinate frame.

Recognition channel resolution is a performance control knob, not an afterthought. Reduce it whenever the target geometry still remains measurable; keep high resolution for display, final coordinate mapping, sub-pixel refinement, or occasional validation only.

## Parallel And Pipelined Execution

On Linux/OpenCV:

- Use one capture thread that always keeps the latest frame.
- Use one processing worker for low-res detection.
- Use optional display/serial workers if they block.
- Drop old frames instead of processing a queue backlog.

On MicroPython/vendor firmware:

- Use staged work across frames: heavy detection every N frames, tracking every frame, display every M frames.
- Restrict expensive operations to ROI once the target is locked.
- Preallocate buffers where possible and avoid repeated large allocations.
- Run garbage collection at controlled intervals, not every frame unless memory requires it.

## Low-Resolution Detection

Lower the recognition channel before adding exotic filters:

- Try 320x192, 400x240, or QVGA for target detection.
- If FPS is below target, lower recognition resolution before changing the whole algorithm.
- Use high-res display only for clean visualization and final coordinate mapping; keep screen overlays FPS-only unless debugging requires more.
- For black-white tasks, use grayscale thresholding, edge/contour, and morphology on the low-res channel.
- For colored targets, use HSV/LAB/RGB threshold only in the feature channel or ROI unless the whole frame requires color segmentation.

## Color Target Strategy

For color blocks, colored rings, laser dots, LEDs, traffic-light targets, and colored guide lines:

- Lock exposure, gain, and white balance when possible; color thresholds drift heavily under auto settings.
- Prefer HSV or LAB thresholds for robustness; use RGB thresholds only when the firmware/cv_lite API exposes RGB directly or lighting is controlled.
- Use low-resolution color segmentation for detection, then optionally refine on a high-resolution ROI.
- Apply `gaussian(1)` or small mean blur before thresholding when sensor noise causes speckles.
- Use open/erode to remove isolated color noise; use close/dilate to connect broken colored areas.
- Validate color candidates with geometry: area, aspect ratio, circularity, solidity, convexity, centroid, distance from prediction, and border distance.
- For red targets in HSV, handle hue wrap-around with two masks and merge them.
- For laser spots, use color threshold plus brightness/saturation and reject large blobs.

## Color Algorithm Menu

- RGB threshold: simple and fast; good for cv_lite `rgb888_find_blobs` examples and controlled light.
- HSV threshold: robust to brightness changes; best default for colored objects in OpenCV.
- LAB threshold: useful for OpenMV-style thresholds and perceptual color separation.
- YCrCb threshold: useful for separating chroma from luminance under uneven brightness.
- Color ratio rules: compare R/G/B ratios when absolute brightness changes but color ratio stays stable.
- Gray-world white balance: fast global correction before color thresholding.
- White-patch white balance: useful when a reliable white reference exists.
- Exposure gain adjustment: brighten/darken before segmentation, but avoid saturation.
- Histogram check: use channel histograms to choose or verify thresholds.

## Black-White Target Strategy

For black-white paper, ring, rectangle, and line targets:

- Convert to grayscale early.
- Lock exposure and white balance once the scene is stable.
- Use threshold/binary, Canny/contour, rectangle/corner extraction, and geometric validation.
- Validate candidates by dark border hits, white interior hits, area ratio, axis ratio, opposite-edge consistency, and ROI gate.
- Smooth center/corners with adaptive alpha: low alpha when still, high alpha when motion is fast.

## Threshold Strategy Menu

- Otsu adaptive: recompute gray threshold every N frames when light changes slowly.
- Otsu + EMA: smooth the threshold to avoid frame-to-frame flicker.
- Local threshold: compute thresholds per region when illumination is uneven.
- Dual threshold: separate white-paper and black-frame thresholds for target validation.

## Validation Filter Menu

- Area: reject targets that are too large or too small.
- Aspect ratio: check whether the paper/target ratio is plausible.
- Edge margin: distrust candidates stuck to image borders.
- Density/solidity/convexity: reject blobs whose shape is unlike the target.
- Four-side black-frame sampling: check whether the outer border is dark.
- Interior white-paper sampling: check whether the inner region is bright.
- Black-white contrast: compare paper mean minus border mean.
- Temporal consistency: require two or more consistent frames before lock.
- Prediction consistency: after lock, reject candidates far from the predicted state.

## Tracking And Smoothing Menu

- Direct center output: simplest baseline.
- Moving average: smooth coordinates with a short window.
- EMA first-order low-pass: stable and cheap.
- Alpha-beta filter: estimate position and velocity with little CPU.
- Kalman filter: use when motion model and noise tuning are worth the overhead.
- Deadband: avoid responding to tiny jitter.
- ROI tracking: after lock, search near the target only.
- Coast prediction: keep output through one or two missed frames.
- Corner smoothing: smooth all four corners so the frame does not shake.

## Incremental Line-Following Upgrade

For line-following or black-track examples:

1. Preserve the firmware example's camera/display/UART setup.
2. Keep the original binary threshold path working.
3. Add eight-neighborhood search to connect line pixels or trace connected components.
4. Use area, continuity, branch count, and ROI position to reject noise.
5. Convert the traced line into center error, angle error, or cross/intersection state.
6. Add PID, deadband, and serial packet reuse only after detection is stable.

## cv_lite/OpenCV Patterns

Use assets as examples:

- `assets/cv-lite-examples/grayscale_find_rectangle_with_corners.py`: grayscale rectangle/corner detection.
- `assets/cv-lite-examples/rgb888_pnp_distance_from_corners_and_find_target.py`: contour plus PnP and target validation.
- `assets/cv-lite-examples/rgb888_adjust_exposure_fast.py`: fast exposure adjustment.
- `assets/cv-lite-examples/rgb888_white_balance_gray_world_fast.py`: fast gray-world white balance.
- `assets/k230/k230-25e-optimized.py`: single-frame K230 target tracker baseline.
- `assets/k230/k230-25e-dual-frame-high-fps.py`: high-FPS dual-frame style K230 baseline.

## Filter Choices For Smooth High FPS

- Prefer 3x3 or 5x5 kernels; raise kernel size only after measuring FPS.
- Use Gaussian blur before Canny when edge noise is high; use mean/box blur only if it is faster and sufficient.
- Use open/close morphology on binary masks only inside ROI.
- Avoid full-frame Hough or large connected-component scans when contour/corner extraction works.
- Limit candidate validation count. Sort by area/score and validate the top candidates.
- Use temporal gates to avoid jumping to false positives: center gate, size ratio gate, aspect-ratio delta, and acquire confirmation frames.

## Specialized Measurement Upgrade

When a generic detector jitters, misses, or drops FPS, upgrade it instead of only tuning thresholds:

- Run the heavy detector only for coarse acquisition or recovery.
- Add a cheap per-frame local measurement near the predicted state.
- Fit the target's physical variables directly: center/radius, line/angle, corners/pose, blob center/area, or spot center/intensity.
- Validate the full physical state, not isolated detections.
- Smooth coherent state variables together so one bad frame cannot update only part of the target.

## Output Quality Targets

Prefer measurable targets:

- FPS: show current FPS in the upper-left corner; keep other screen overlays off unless requested.
- Latency: serial output should represent the newest processed frame, not stale queue data.
- Stability: report lost frames, coast frames, and re-acquisition behavior.
- Precision: report coordinate frame, scale mapping, and center/corner smoothing.
