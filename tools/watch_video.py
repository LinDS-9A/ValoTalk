"""用项目自己的 cv2 + faster-whisper 看视频（不需要外部 ffmpeg）。

输出：关键帧图片 + 逐句转写。
"""
from __future__ import annotations
import io
import sys
from pathlib import Path

SRC = Path(r"C:\Users\小林\.dsh\douyin-duty\media\lab"
           r"\7698793274546375946-1795506121\source.mp4")
OUT = Path(r"E:\rea-work\valotalk\cache\vid")
OUT.mkdir(parents=True, exist_ok=True)

if not SRC.exists():
    print("缺视频文件", SRC)
    sys.exit(1)

# ---------- 1) 抽帧 ----------
import cv2

cap = cv2.VideoCapture(str(SRC))
fps = cap.get(cv2.CAP_PROP_FPS) or 30
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
dur = total / fps if fps else 0
print(f"视频 {dur:.1f}s  {fps:.0f}fps  {total} 帧")

# 均匀取 10 帧（避开片头片尾）
want = 10
saved = []
for i in range(want):
    t = dur * (0.06 + 0.88 * i / max(1, want - 1))
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    if not ok:
        continue
    h, w = frame.shape[:2]
    scale = 900 / max(w, 1)
    if scale < 1:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
    p = OUT / f"f{i:02d}_{int(t)}s.jpg"
    cv2.imwrite(str(p), frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
    saved.append(p)
cap.release()
print(f"抽了 {len(saved)} 帧 -> {OUT}")

# ---------- 2) 转写 ----------
import av
import numpy as np

print("解码音轨…")
container = av.open(str(SRC))
astream = next(s for s in container.streams if s.type == "audio")
resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
chunks = []
for packet in container.demux(astream):
    for frame in packet.decode():
        for rf in resampler.resample(frame):
            arr = rf.to_ndarray()
            chunks.append(arr.reshape(-1))
container.close()
audio = np.concatenate(chunks).astype(np.float32) / 32768.0
print(f"音频 {len(audio)/16000:.1f}s")

from faster_whisper import WhisperModel

print("加载模型（small，CPU）…")
LOCAL = r"E:\rea-work\valotalk\models\models--Systran--faster-whisper-small\snapshots\536b0662742c02347bc0e980a01041f333bce120"
m = WhisperModel(LOCAL, device="cpu", compute_type="int8", local_files_only=True)
segs, info = m.transcribe(audio, language="zh", vad_filter=True,
                          beam_size=1)
print(f"语言={info.language}  概率={info.language_probability:.2f}")
print("\n===== 转写 =====")
for s in segs:
    print(f"[{s.start:6.1f}-{s.end:6.1f}] {s.text.strip()}")
