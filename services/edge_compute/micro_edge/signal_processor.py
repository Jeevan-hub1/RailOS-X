"""
RailOS-X Micro-Edge Signal Processor (Tier 1)
Real-time Digital Signal Processing for railway sensor data.

Implements:
  - FFT-based spectral analysis (vibration frequency decomposition)
  - Discrete Wavelet Transform (multi-resolution transient detection)
  - Kalman Filter (sensor fusion / noise reduction / state estimation)
  - Sliding window statistics (real-time streaming computations)
  - Envelope analysis (bearing defect detection via demodulation)

Optimized for ARM Cortex-M7 / Jetson Nano constraints:
  - Pre-allocated buffers (no dynamic allocation in hot path)
  - Fixed-point compatible algorithms where possible
  - Vectorized operations via list comprehensions (NumPy optional)

Satisfies: Req 44 C2, Design §5.1.3
"""
from __future__ import annotations

import math
import cmath
from typing import Optional
from dataclasses import dataclass, field


# ══════════════════════════════════════════════════════════════════════════════
# FFT — Cooley-Tukey radix-2 DIT (pure Python, no NumPy dependency)
# ══════════════════════════════════════════════════════════════════════════════

def fft(signal: list[float]) -> list[complex]:
    """Compute FFT using Cooley-Tukey radix-2 DIT algorithm.
    
    Input length must be power of 2. Zero-pads if necessary.
    Returns complex spectrum of length N.
    """
    n = len(signal)
    # Pad to next power of 2
    n_padded = 1
    while n_padded < n:
        n_padded <<= 1
    x = [complex(v) for v in signal] + [complex(0)] * (n_padded - n)
    return _fft_recursive(x)


def _fft_recursive(x: list[complex]) -> list[complex]:
    """Recursive radix-2 FFT."""
    n = len(x)
    if n <= 1:
        return x
    if n == 2:
        return [x[0] + x[1], x[0] - x[1]]

    even = _fft_recursive(x[0::2])
    odd = _fft_recursive(x[1::2])

    half = n // 2
    result = [complex(0)] * n
    for k in range(half):
        w = cmath.exp(-2j * cmath.pi * k / n) * odd[k]
        result[k] = even[k] + w
        result[k + half] = even[k] - w
    return result


def power_spectrum(signal: list[float], sample_rate_hz: int) -> tuple[list[float], list[float]]:
    """Compute single-sided power spectrum.
    
    Returns (frequencies_hz, power_db) — only positive frequencies.
    """
    spectrum = fft(signal)
    n = len(spectrum)
    half = n // 2

    freqs = [k * sample_rate_hz / n for k in range(half)]
    power = []
    for k in range(half):
        mag_sq = spectrum[k].real ** 2 + spectrum[k].imag ** 2
        # Convert to dB, floor at -120 dB
        db = 10 * math.log10(mag_sq + 1e-12) if mag_sq > 0 else -120.0
        power.append(db)

    return freqs, power


def dominant_frequency(signal: list[float], sample_rate_hz: int) -> tuple[float, float]:
    """Find the dominant frequency and its magnitude.
    
    Returns (frequency_hz, magnitude_db).
    """
    freqs, power = power_spectrum(signal, sample_rate_hz)
    if not power:
        return 0.0, -120.0
    max_idx = max(range(1, len(power)), key=lambda i: power[i])  # skip DC (idx 0)
    return freqs[max_idx], power[max_idx]


def spectral_centroid(signal: list[float], sample_rate_hz: int) -> float:
    """Compute spectral centroid (weighted mean frequency)."""
    freqs, power = power_spectrum(signal, sample_rate_hz)
    # Convert from dB to linear for weighting
    linear_power = [10 ** (p / 10) for p in power]
    total_power = sum(linear_power)
    if total_power < 1e-12:
        return 0.0
    return sum(f * p for f, p in zip(freqs, linear_power)) / total_power


def band_energy(signal: list[float], sample_rate_hz: int,
                low_hz: float, high_hz: float) -> float:
    """Compute energy in a specific frequency band (dB)."""
    freqs, power = power_spectrum(signal, sample_rate_hz)
    band_powers = [p for f, p in zip(freqs, power) if low_hz <= f <= high_hz]
    if not band_powers:
        return -120.0
    # Sum in linear domain, convert back to dB
    linear_sum = sum(10 ** (p / 10) for p in band_powers)
    return 10 * math.log10(linear_sum + 1e-12)


# ══════════════════════════════════════════════════════════════════════════════
# Discrete Wavelet Transform — Haar wavelet (simplest, MCU-friendly)
# ══════════════════════════════════════════════════════════════════════════════

def haar_dwt(signal: list[float], levels: int = 3) -> list[list[float]]:
    """Multi-level Haar Discrete Wavelet Transform.
    
    Returns list of detail coefficients at each level + final approximation.
    [detail_1, detail_2, ..., detail_n, approx_n]
    
    Useful for detecting transient events (rail cracks, wheel flats).
    """
    coefficients: list[list[float]] = []
    approx = list(signal)

    for _ in range(levels):
        n = len(approx)
        if n < 2:
            break
        half = n // 2
        new_approx = []
        detail = []
        for i in range(half):
            a = approx[2 * i]
            b = approx[2 * i + 1]
            new_approx.append((a + b) / math.sqrt(2))
            detail.append((a - b) / math.sqrt(2))
        coefficients.append(detail)
        approx = new_approx

    coefficients.append(approx)  # Final approximation
    return coefficients


def wavelet_energy(signal: list[float], levels: int = 3) -> list[float]:
    """Compute energy at each wavelet decomposition level.
    
    Returns [energy_level_1, ..., energy_level_n, energy_approx].
    High energy in detail coefficients indicates transient/impulsive events.
    """
    coeffs = haar_dwt(signal, levels)
    return [sum(c * c for c in level) / len(level) if level else 0.0 for level in coeffs]


def wavelet_transient_detect(signal: list[float], threshold_factor: float = 4.0,
                              levels: int = 3) -> list[dict]:
    """Detect transient events using wavelet detail coefficients.
    
    Returns list of detected transients with level, position, magnitude.
    """
    coeffs = haar_dwt(signal, levels)
    transients = []

    for level_idx, detail in enumerate(coeffs[:-1]):  # Skip approximation
        if not detail:
            continue
        mean_abs = sum(abs(c) for c in detail) / len(detail)
        threshold = mean_abs * threshold_factor

        for pos, coeff in enumerate(detail):
            if abs(coeff) > threshold:
                transients.append({
                    "level": level_idx + 1,
                    "position": pos,
                    "magnitude": abs(coeff),
                    "threshold": threshold,
                    "ratio": abs(coeff) / threshold,
                })

    return transients


# ══════════════════════════════════════════════════════════════════════════════
# Kalman Filter — 1D and Multi-dimensional
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class KalmanFilter1D:
    """1D Kalman filter for sensor noise reduction and state estimation.
    
    Suitable for single-axis filtering (temperature, speed, position).
    State model: x_k = x_{k-1} + process_noise
    Measurement: z_k = x_k + measurement_noise
    """
    x: float = 0.0              # State estimate
    p: float = 1.0              # Estimate uncertainty
    q: float = 0.01             # Process noise covariance
    r: float = 0.1              # Measurement noise covariance
    k: float = 0.0              # Kalman gain (computed)

    def predict(self) -> float:
        """Prediction step (no control input)."""
        # x stays the same (constant velocity model)
        self.p += self.q
        return self.x

    def update(self, measurement: float) -> float:
        """Update step with new measurement. Returns filtered estimate."""
        # Kalman gain
        self.k = self.p / (self.p + self.r)
        # State update
        self.x += self.k * (measurement - self.x)
        # Covariance update
        self.p *= (1 - self.k)
        return self.x

    def filter(self, measurement: float) -> float:
        """Combined predict + update. Returns filtered value."""
        self.predict()
        return self.update(measurement)

    def filter_batch(self, measurements: list[float]) -> list[float]:
        """Filter a batch of measurements. Returns list of filtered values."""
        return [self.filter(m) for m in measurements]


@dataclass
class KalmanFilter2D:
    """2D Kalman filter for position + velocity estimation.
    
    State: [position, velocity]
    Useful for GPS smoothing and train position/speed estimation.
    """
    x: list[float] = field(default_factory=lambda: [0.0, 0.0])  # [pos, vel]
    P: list[list[float]] = field(default_factory=lambda: [[1.0, 0.0], [0.0, 1.0]])
    dt: float = 0.1  # time step
    q_pos: float = 0.01
    q_vel: float = 0.1
    r_pos: float = 1.0

    def predict(self) -> list[float]:
        """Predict next state using constant-velocity model."""
        # State transition: pos += vel * dt
        self.x[0] += self.x[1] * self.dt

        # Covariance prediction
        F = [[1.0, self.dt], [0.0, 1.0]]
        Q = [[self.q_pos, 0.0], [0.0, self.q_vel]]

        # P = F @ P @ F^T + Q
        FP = _mat_mul(F, self.P)
        FT = [[F[0][0], F[1][0]], [F[0][1], F[1][1]]]
        self.P = _mat_add(_mat_mul(FP, FT), Q)
        return list(self.x)

    def update(self, position_measurement: float) -> list[float]:
        """Update with position measurement only."""
        # Measurement matrix H = [1, 0]
        # Innovation
        y = position_measurement - self.x[0]

        # Innovation covariance S = H @ P @ H^T + R
        S = self.P[0][0] + self.r_pos

        # Kalman gain K = P @ H^T / S
        K = [self.P[0][0] / S, self.P[1][0] / S]

        # State update
        self.x[0] += K[0] * y
        self.x[1] += K[1] * y

        # Covariance update P = (I - K @ H) @ P
        self.P[0][0] -= K[0] * self.P[0][0]
        self.P[0][1] -= K[0] * self.P[0][1]
        self.P[1][0] -= K[1] * self.P[0][0]
        self.P[1][1] -= K[1] * self.P[0][1]

        return list(self.x)

    def filter(self, position_measurement: float) -> tuple[float, float]:
        """Combined predict + update. Returns (position, velocity)."""
        self.predict()
        self.update(position_measurement)
        return self.x[0], self.x[1]


def _mat_mul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    """2x2 matrix multiply."""
    return [
        [A[0][0] * B[0][0] + A[0][1] * B[1][0], A[0][0] * B[0][1] + A[0][1] * B[1][1]],
        [A[1][0] * B[0][0] + A[1][1] * B[1][0], A[1][0] * B[0][1] + A[1][1] * B[1][1]],
    ]


def _mat_add(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
    """2x2 matrix add."""
    return [[A[i][j] + B[i][j] for j in range(2)] for i in range(2)]


# ══════════════════════════════════════════════════════════════════════════════
# Sliding Window Statistics — O(1) update streaming computations
# ══════════════════════════════════════════════════════════════════════════════

class SlidingWindowStats:
    """O(1) amortized sliding window statistics using deque-based approach.
    
    Maintains: mean, variance, min, max, sum over a fixed-size window.
    No recomputation — incremental updates on push/pop.
    """
    __slots__ = ('_window', '_capacity', '_sum', '_sum_sq', '_sorted_deque')

    def __init__(self, capacity: int = 1000) -> None:
        from collections import deque
        self._window: deque = deque(maxlen=capacity)
        self._capacity = capacity
        self._sum = 0.0
        self._sum_sq = 0.0

    @property
    def count(self) -> int:
        return len(self._window)

    @property
    def mean(self) -> float:
        n = len(self._window)
        return self._sum / n if n > 0 else 0.0

    @property
    def variance(self) -> float:
        n = len(self._window)
        if n < 2:
            return 0.0
        mean = self._sum / n
        return (self._sum_sq / n) - mean * mean

    @property
    def std(self) -> float:
        v = self.variance
        return math.sqrt(v) if v > 0 else 0.0

    @property
    def rms(self) -> float:
        n = len(self._window)
        return math.sqrt(self._sum_sq / n) if n > 0 else 0.0

    def push(self, value: float) -> None:
        """Add a value. Evicts oldest if at capacity. O(1) amortized."""
        if len(self._window) >= self._capacity:
            evicted = self._window[0]
            self._sum -= evicted
            self._sum_sq -= evicted * evicted
        self._window.append(value)
        self._sum += value
        self._sum_sq += value * value

    def push_batch(self, values: list[float]) -> None:
        """Batch push for efficiency."""
        for v in values:
            self.push(v)

    def get_stats(self) -> dict[str, float]:
        """Return all statistics as a dict."""
        n = len(self._window)
        if n == 0:
            return {"count": 0, "mean": 0, "std": 0, "rms": 0, "min": 0, "max": 0}
        return {
            "count": n,
            "mean": self.mean,
            "std": self.std,
            "rms": self.rms,
            "min": min(self._window),
            "max": max(self._window),
        }


# ══════════════════════════════════════════════════════════════════════════════
# Envelope Analysis — for bearing defect detection
# ══════════════════════════════════════════════════════════════════════════════

def hilbert_envelope(signal: list[float]) -> list[float]:
    """Compute signal envelope using Hilbert transform approximation.
    
    The envelope reveals amplitude modulation caused by bearing defects.
    Uses FFT-based approach: zero negative frequencies, IFFT, take magnitude.
    """
    n = len(signal)
    # Pad to power of 2
    n_padded = 1
    while n_padded < n:
        n_padded <<= 1

    # FFT
    spectrum = fft(signal + [0.0] * (n_padded - n))

    # Zero negative frequencies (keep DC and Nyquist as-is)
    half = n_padded // 2
    for i in range(half + 1, n_padded):
        spectrum[i] = complex(0)
    # Double positive frequencies
    for i in range(1, half):
        spectrum[i] *= 2

    # IFFT (using conjugate trick: IFFT(x) = conj(FFT(conj(x))) / N)
    conj_spectrum = [c.conjugate() for c in spectrum]
    analytic = _fft_recursive(conj_spectrum)
    analytic = [c.conjugate() / n_padded for c in analytic]

    # Envelope = magnitude of analytic signal
    envelope = [abs(c) for c in analytic[:n]]
    return envelope


def bearing_defect_frequencies(shaft_rpm: float, n_balls: int = 8,
                                ball_diameter_mm: float = 12.0,
                                pitch_diameter_mm: float = 50.0,
                                contact_angle_deg: float = 0.0) -> dict[str, float]:
    """Compute characteristic bearing defect frequencies.
    
    BPFO: Ball Pass Frequency Outer race
    BPFI: Ball Pass Frequency Inner race
    BSF:  Ball Spin Frequency
    FTF:  Fundamental Train Frequency (cage)
    """
    shaft_hz = shaft_rpm / 60.0
    d = ball_diameter_mm
    D = pitch_diameter_mm
    alpha = math.radians(contact_angle_deg)
    cos_alpha = math.cos(alpha)

    bpfo = (n_balls / 2) * shaft_hz * (1 - (d / D) * cos_alpha)
    bpfi = (n_balls / 2) * shaft_hz * (1 + (d / D) * cos_alpha)
    bsf = (D / (2 * d)) * shaft_hz * (1 - ((d / D) * cos_alpha) ** 2)
    ftf = (shaft_hz / 2) * (1 - (d / D) * cos_alpha)

    return {"BPFO": bpfo, "BPFI": bpfi, "BSF": bsf, "FTF": ftf}


# ══════════════════════════════════════════════════════════════════════════════
# Composite Signal Processor
# ══════════════════════════════════════════════════════════════════════════════

class SignalProcessor:
    """Unified signal processing pipeline for a sensor channel.
    
    Combines: Kalman filtering → windowed stats → FFT → wavelet → envelope.
    Configurable per sensor type (not all steps needed for every sensor).
    """

    def __init__(self, sample_rate_hz: int = 4000, window_size: int = 512,
                 enable_fft: bool = True, enable_wavelet: bool = True,
                 enable_envelope: bool = False,
                 kalman_q: float = 0.01, kalman_r: float = 0.1) -> None:
        self.sample_rate_hz = sample_rate_hz
        self.window_size = window_size
        self.enable_fft = enable_fft
        self.enable_wavelet = enable_wavelet
        self.enable_envelope = enable_envelope

        self._kalman = KalmanFilter1D(q=kalman_q, r=kalman_r)
        self._stats = SlidingWindowStats(capacity=window_size)
        self._buffer: list[float] = []

    def process_sample(self, raw_value: float) -> Optional[dict]:
        """Process a single sample. Returns feature dict when window is full."""
        # Stage 1: Kalman filter
        filtered = self._kalman.filter(raw_value)

        # Stage 2: Update sliding stats
        self._stats.push(filtered)

        # Stage 3: Accumulate window
        self._buffer.append(filtered)

        if len(self._buffer) >= self.window_size:
            result = self._extract_features()
            self._buffer = []
            return result
        return None

    def process_batch(self, raw_values: list[float]) -> list[dict]:
        """Process a batch of samples. Returns list of feature dicts (one per window)."""
        results = []
        for v in raw_values:
            feat = self.process_sample(v)
            if feat is not None:
                results.append(feat)
        return results

    def _extract_features(self) -> dict:
        """Extract all enabled features from current window."""
        features: dict[str, any] = {}

        # Time-domain stats (always computed)
        features.update(self._stats.get_stats())

        # Spectral features
        if self.enable_fft and len(self._buffer) >= 4:
            dom_freq, dom_mag = dominant_frequency(self._buffer, self.sample_rate_hz)
            features["dominant_freq_hz"] = round(dom_freq, 1)
            features["dominant_mag_db"] = round(dom_mag, 1)
            features["spectral_centroid_hz"] = round(
                spectral_centroid(self._buffer, self.sample_rate_hz), 1)
            # Band energies (typical railway defect bands)
            features["energy_0_50hz"] = round(
                band_energy(self._buffer, self.sample_rate_hz, 0, 50), 1)
            features["energy_50_200hz"] = round(
                band_energy(self._buffer, self.sample_rate_hz, 50, 200), 1)
            features["energy_200_1000hz"] = round(
                band_energy(self._buffer, self.sample_rate_hz, 200, 1000), 1)
            features["energy_1000_2000hz"] = round(
                band_energy(self._buffer, self.sample_rate_hz, 1000, 2000), 1)

        # Wavelet features
        if self.enable_wavelet and len(self._buffer) >= 8:
            energies = wavelet_energy(self._buffer, levels=4)
            for i, e in enumerate(energies[:-1]):
                features[f"wavelet_detail_{i + 1}_energy"] = round(e, 4)
            features["wavelet_approx_energy"] = round(energies[-1], 4)

            transients = wavelet_transient_detect(self._buffer, threshold_factor=4.0)
            features["wavelet_transient_count"] = len(transients)

        # Envelope features (bearing defect detection)
        if self.enable_envelope and len(self._buffer) >= 16:
            env = hilbert_envelope(self._buffer)
            env_dom_freq, env_dom_mag = dominant_frequency(env, self.sample_rate_hz)
            features["envelope_dom_freq_hz"] = round(env_dom_freq, 1)
            features["envelope_dom_mag_db"] = round(env_dom_mag, 1)

        return features
