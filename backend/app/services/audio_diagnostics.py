"""Local numeric audio inspection; never logs or stores candidate audio/text."""
import math
from pathlib import Path
import av
import numpy as np

class AudioDurationLimitError(ValueError):
    """Decoded sample count exceeded the caller's duration policy."""


def decode_audio(path, sampling_rate=16000, *, max_duration_seconds=None, check=None):
    """Decode supported containers with PyAV to float32 mono PCM, without an ASR model."""
    chunks = []
    sample_count = 0
    max_samples = None if max_duration_seconds is None else math.floor(max_duration_seconds * sampling_rate)
    check = check or (lambda: None)
    check()
    resampler = av.AudioResampler(format='s16', layout='mono', rate=sampling_rate)
    def append(output):
        nonlocal sample_count
        check()
        # Reject before copying the frame into a NumPy array or retaining it.
        if max_samples is not None and sample_count + output.samples > max_samples:
            raise AudioDurationLimitError('Decoded audio exceeds the recording duration limit.')
        values = output.to_ndarray().reshape(-1)
        sample_count += values.size
        chunks.append(values)
    with av.open(str(path)) as container:
        for frame in container.decode(audio=0):
            check()
            frame.pts = None
            for output in resampler.resample(frame):
                append(output)
        check()
        for output in resampler.resample(None):
            append(output)
    check()
    samples = np.concatenate(chunks).astype(np.float32) if chunks else np.empty(0, dtype=np.float32)
    samples /= 32768.0
    check()
    return samples


def inspect_audio(path, *, max_duration_seconds=None, check=None):
    check = check or (lambda: None)
    check()
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        metadata = dict(container=container.format.name, codec=stream.codec_context.name,
                        source_sample_rate=stream.codec_context.sample_rate,
                        source_channels=stream.codec_context.channels)
    samples = decode_audio(str(path), sampling_rate=16000, max_duration_seconds=max_duration_seconds, check=check)
    if not samples.size:
        raise ValueError('No valid audio samples could be decoded.')
    # Fixed-size statistics avoid several full-recording float64 allocations.
    peak = energy = 0.0
    clipped = quiet_frames = frame_count = 0
    for offset in range(0, len(samples), 16000):
        check()
        block = samples[offset:offset + 16000]
        if not np.isfinite(block).all():
            raise ValueError('No valid audio samples could be decoded.')
        peak = max(peak, float(np.max(np.abs(block))))
        values = block.astype(np.float64)
        energy += float(np.sum(values * values))
        clipped += int(np.count_nonzero(np.abs(block) >= 0.999))
        frames = values[:len(values)//320*320].reshape(-1, 320)
        quiet_frames += int(np.count_nonzero(np.sqrt(np.mean(frames ** 2, axis=1)) < 0.0031623))
        frame_count += len(frames)
    check()
    rms = math.sqrt(energy / len(samples))
    quiet = quiet_frames / frame_count if frame_count else 1.0
    metadata.update(bytes=Path(path).stat().st_size, decoded_sample_rate=16000, decoded_channels=1,
                    duration_seconds=round(len(samples)/16000,3), peak=round(peak,6),
                    rms_dbfs=round(20*math.log10(max(rms,1e-10)),2),
                    near_clip_fraction=round(clipped / len(samples),6),
                    quiet_frame_fraction=round(quiet,4))
    return samples, metadata
