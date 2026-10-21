"""Phase 8 sequence models (PyTorch, CPU): LSTM, GRU, LSTM/GRU + attention, temporal transformer.

Input (batch, length, n_features) -> 3 logits (DOWN / NEUTRAL / UP). The last time step is the
prediction row; nothing after it is ever part of the window (see datasets/sequences.py).
"""

from __future__ import annotations

from typing import Any

import torch
from torch import nn

ARCHITECTURES = ("lstm", "gru", "lstm_attn", "gru_attn", "transformer")


class AttnPool(nn.Module):
    """Additive attention over time steps; returns a weighted sum of the sequence."""

    def __init__(self, hidden: int, attn: int) -> None:
        super().__init__()
        self.score = nn.Sequential(nn.Linear(hidden, attn), nn.Tanh(), nn.Linear(attn, 1))

    def forward(self, h: torch.Tensor) -> torch.Tensor:
        w = torch.softmax(self.score(h).squeeze(-1), dim=1)
        return (w.unsqueeze(-1) * h).sum(dim=1)


class RecurrentNet(nn.Module):
    def __init__(
        self, n_features: int, cell: str, hidden: int, layers: int, dropout: float, attn: int | None
    ) -> None:
        super().__init__()
        rnn = nn.LSTM if cell == "lstm" else nn.GRU
        self.rnn = rnn(
            n_features, hidden, num_layers=layers, batch_first=True, dropout=dropout if layers > 1 else 0.0
        )
        self.pool = AttnPool(hidden, attn) if attn else None
        width = 2 * hidden if attn else hidden
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(width, 3))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h, _ = self.rnn(x)
        last = h[:, -1]
        z = torch.cat([last, self.pool(h)], dim=1) if self.pool is not None else last
        out: torch.Tensor = self.head(z)
        return out


class TemporalTransformer(nn.Module):
    def __init__(
        self, n_features: int, d_model: int, heads: int, layers: int, dropout: float, max_len: int
    ) -> None:
        super().__init__()
        self.proj = nn.Linear(n_features, d_model)
        self.pos = nn.Parameter(torch.zeros(1, max_len, d_model))
        nn.init.normal_(self.pos, std=0.02)
        layer = nn.TransformerEncoderLayer(
            d_model, heads, dim_feedforward=2 * d_model, dropout=dropout, batch_first=True, norm_first=True
        )
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.head = nn.Sequential(nn.LayerNorm(2 * d_model), nn.Dropout(dropout), nn.Linear(2 * d_model, 3))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        length = x.shape[1]
        h = self.encoder(self.proj(x) + self.pos[:, -length:])
        out: torch.Tensor = self.head(torch.cat([h[:, -1], h.mean(dim=1)], dim=1))
        return out


def make(arch: str, n_features: int, length: int, p: dict[str, Any]) -> nn.Module:
    if arch in ("lstm", "gru"):
        return RecurrentNet(n_features, arch, p["hidden"], p["layers"], p["dropout"], None)
    if arch in ("lstm_attn", "gru_attn"):
        return RecurrentNet(n_features, arch.split("_")[0], p["hidden"], p["layers"], p["dropout"], p["attn"])
    if arch == "transformer":
        return TemporalTransformer(n_features, p["d_model"], p["heads"], p["layers"], p["dropout"], length)
    raise ValueError(f"unknown architecture {arch}")
