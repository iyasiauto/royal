"""Measure per-frame translational jitter of a video via phase correlation.
sd < 0.10 px = smooth to the eye; ~0.20 = slight; > 0.40 = visible shake."""
import sys, numpy as np, cv2

def measure(path, max_frames=200, skip_edge=10):
    """Per-frame translation via phase correlation, fade frames skipped, and the
    smooth Ken Burns drift removed so only real jitter (the residual) remains."""
    cap = cv2.VideoCapture(path)
    frames = []
    while len(frames) < max_frames:
        ok, frame = cap.read()
        if not ok: break
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        frames.append(cv2.resize(g, (640, 360)))
    cap.release()
    if len(frames) < 2 * skip_edge + 5:
        skip_edge = 2
    dxs, dys = [], []
    for i in range(1, len(frames)):
        (dx, dy), _ = cv2.phaseCorrelate(frames[i-1], frames[i])
        dxs.append(dx); dys.append(dy)
    dxs, dys = np.array(dxs), np.array(dys)
    # drop fade regions at both ends
    core_dx = dxs[skip_edge:len(dxs)-skip_edge] if len(dxs) > 2*skip_edge else dxs
    core_dy = dys[skip_edge:len(dys)-skip_edge] if len(dys) > 2*skip_edge else dys
    if len(core_dx) < 3:
        return None
    # residual jitter = per-frame motion minus its linear trend (the intended pan/zoom)
    def resid_sd(a):
        t = np.arange(len(a))
        coef = np.polyfit(t, a, 1)
        return float(np.std(a - np.polyval(coef, t)))
    return {
        "frames": len(frames),
        "dx_sd": resid_sd(core_dx), "dy_sd": resid_sd(core_dy),
        "dx_mean": float(np.mean(core_dx)), "dy_mean": float(np.mean(core_dy)),
    }

if __name__ == "__main__":
    for p in sys.argv[1:]:
        r = measure(p)
        if r is None:
            print(f"{p}: no frames"); continue
        verdict = "SMOOTH" if max(r['dx_sd'], r['dy_sd']) < 0.12 else \
                  "slight" if max(r['dx_sd'], r['dy_sd']) < 0.25 else "SHAKE"
        print(f"{p.split(chr(92))[-1]:20s} frames={r['frames']:3d} "
              f"dx_sd={r['dx_sd']:.3f} dy_sd={r['dy_sd']:.3f} "
              f"mean=({r['dx_mean']:+.2f},{r['dy_mean']:+.2f}) [{verdict}]")
