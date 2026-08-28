"""M6 — Implement scaled dot-product attention and multi-head attention.

No nn.MultiheadAttention, no nn.functional.scaled_dot_product_attention — the
point is to write it yourself. Tests check shapes, causal masking, and numerical
agreement with PyTorch's own implementation.

Requires: torch (already installed with CUDA in this environment).
"""

from __future__ import annotations

import math

import torch
import torch.nn as nn


def scaled_dot_product_attention(
    q: torch.Tensor,          # (B, H, T, d_head)
    k: torch.Tensor,          # (B, H, S, d_head)
    v: torch.Tensor,          # (B, H, S, d_head)
    causal: bool = False,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return (output, attention_weights).

    output shape:  (B, H, T, d_head)
    weights shape: (B, H, T, S), each row summing to 1

    If causal=True, position t may not attend to any position > t.
    Use -inf (not a large negative number) for masked logits before the softmax.
    """
    raise NotImplementedError


class MultiHeadAttention(nn.Module):
    """Standard multi-head self-attention.

    Use four nn.Linear(d_model, d_model) layers named q_proj, k_proj, v_proj,
    out_proj so the tests can load reference weights into your module.
    """

    def __init__(self, d_model: int, n_heads: int, causal: bool = False):
        super().__init__()
        if d_model % n_heads != 0:
            raise ValueError("d_model must be divisible by n_heads")
        self.d_model = d_model
        self.n_heads = n_heads
        self.d_head = d_model // n_heads
        self.causal = causal
        raise NotImplementedError

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: (B, T, d_model) -> (B, T, d_model)"""
        raise NotImplementedError
