"""
RailOS Cybersecurity LSTM Autoencoder (Tasks 12.1–12.3)
Trained on normal SCADA traffic. Anomaly = reconstruction MSE > threshold.
Satisfies: Req 9, Design §6.6
"""
from __future__ import annotations

import torch
import torch.nn as nn
import numpy as np


class LSTMAutoencoder(nn.Module):
    """LSTM encoder-decoder for SCADA traffic anomaly detection.

    Input:  (batch, seq_len=60, n_features) — 60-second window of SCADA traffic features
    Latent: 64-dim encoding
    Output: (batch, seq_len, n_features) — reconstructed traffic window
    """

    N_FEATURES = 5  # packet_rate, query_type_dist, inter_arrival_ms, payload_size, src_ip_entropy

    def __init__(self, n_features: int = N_FEATURES, hidden: int = 128, latent: int = 64) -> None:
        super().__init__()
        self.encoder_lstm1 = nn.LSTM(n_features, hidden, batch_first=True)
        self.encoder_lstm2 = nn.LSTM(hidden, latent,   batch_first=True)
        self.decoder_lstm1 = nn.LSTM(latent,  hidden,  batch_first=True)
        self.decoder_lstm2 = nn.LSTM(hidden,  hidden,  batch_first=True)
        self.output_layer  = nn.Linear(hidden, n_features)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Encode
        out, _ = self.encoder_lstm1(x)
        out, _ = self.encoder_lstm2(out)
        # Decode (reverse direction)
        out, _ = self.decoder_lstm1(out)
        out, _ = self.decoder_lstm2(out)
        return self.output_layer(out)

    def reconstruction_error(self, x: torch.Tensor) -> float:
        """Return MSE between input and reconstruction."""
        self.eval()
        with torch.no_grad():
            recon = self.forward(x)
            return float(nn.functional.mse_loss(recon, x).item())

    @classmethod
    def load(cls, path: str) -> "LSTMAutoencoder":
        model = cls()
        model.load_state_dict(torch.load(path, map_location="cpu"))
        model.eval()
        return model
