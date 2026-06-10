"""
RailOS Predictive Maintenance LSTM Model (Task 7.2)
2-layer LSTM(128), dropout=0.0 at inference (EN 50128 deterministic).
Satisfies: Req 4, Design §6.2
"""
from __future__ import annotations

import torch
import torch.nn as nn


class MaintenanceLSTM(nn.Module):
    """2-layer LSTM for bearing/track failure probability prediction.

    Dropout is 0.0 at inference time (deterministic, EN 50128 compliant).
    input_size = 8 features (vibration_rms, kurtosis, peak, temperature,
                              wheel_load_left, wheel_load_right, acoustic_rms, speed_kmh)
    seq_len    = 1800  (30 minutes × 1Hz)
    output     = failure probability [0, 1]
    """

    FEATURES = [
        "vibration_rms", "vibration_kurtosis", "vibration_peak",
        "temperature_bogie", "wheel_load_left", "wheel_load_right",
        "acoustic_emission_rms", "speed_kmh",
    ]

    def __init__(self, input_size: int = 8, hidden_size: int = 128, num_layers: int = 2) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.0,   # deterministic at all times
        )
        self.head = nn.Sequential(
            nn.Linear(hidden_size, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: (batch, seq_len, input_size) → (batch, 1) failure probability"""
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :])  # last timestep

    def predict_deterministic(self, x: torch.Tensor) -> torch.Tensor:
        """Deterministic inference: eval mode + no_grad + fixed seed.

        Guarantees identical output for identical input (EN 50128 §7.4.4).
        """
        self.eval()
        torch.manual_seed(42)
        with torch.no_grad():
            return self.forward(x)
