"""Hidden tests for attention."""

import math

import pytest

torch = pytest.importorskip("torch")

import solution as s


def test_output_and_weight_shapes():
    q = torch.randn(2, 4, 6, 8)
    k = torch.randn(2, 4, 6, 8)
    v = torch.randn(2, 4, 6, 8)
    out, w = s.scaled_dot_product_attention(q, k, v)
    assert out.shape == (2, 4, 6, 8)
    assert w.shape == (2, 4, 6, 6)


def test_weights_are_a_distribution():
    q, k, v = (torch.randn(1, 2, 5, 4) for _ in range(3))
    _, w = s.scaled_dot_product_attention(q, k, v)
    assert torch.allclose(w.sum(dim=-1), torch.ones(1, 2, 5), atol=1e-5)
    assert (w >= 0).all()


def test_causal_mask_blocks_the_future():
    q, k, v = (torch.randn(1, 1, 6, 4) for _ in range(3))
    _, w = s.scaled_dot_product_attention(q, k, v, causal=True)
    upper = torch.triu(torch.ones(6, 6), diagonal=1).bool()
    assert w[0, 0][upper].abs().max().item() == 0.0, "attended to future positions"


def test_scaling_is_by_sqrt_d_head():
    """Compare against a hand-computed value for a tiny deterministic case."""
    q = torch.tensor([[[[1.0, 0.0]]]])          # (1,1,1,2)
    k = torch.tensor([[[[1.0, 0.0], [0.0, 1.0]]]])  # (1,1,2,2)
    v = torch.tensor([[[[1.0, 0.0], [0.0, 1.0]]]])
    out, w = s.scaled_dot_product_attention(q, k, v)
    logits = torch.tensor([1.0, 0.0]) / math.sqrt(2)
    expected = torch.softmax(logits, dim=-1)
    assert torch.allclose(w[0, 0, 0], expected, atol=1e-5), (
        "logits must be divided by sqrt(d_head) before the softmax"
    )


def test_matches_pytorch_reference():
    torch.manual_seed(0)
    q, k, v = (torch.randn(2, 3, 7, 16) for _ in range(3))
    mine, _ = s.scaled_dot_product_attention(q, k, v)
    ref = torch.nn.functional.scaled_dot_product_attention(q, k, v)
    assert torch.allclose(mine, ref, atol=1e-5)


def test_matches_pytorch_reference_causal():
    torch.manual_seed(1)
    q, k, v = (torch.randn(2, 3, 7, 16) for _ in range(3))
    mine, _ = s.scaled_dot_product_attention(q, k, v, causal=True)
    ref = torch.nn.functional.scaled_dot_product_attention(q, k, v, is_causal=True)
    assert torch.allclose(mine, ref, atol=1e-5)


def test_multihead_shape_and_heads():
    mha = s.MultiHeadAttention(d_model=32, n_heads=4)
    x = torch.randn(2, 9, 32)
    assert mha(x).shape == (2, 9, 32)
    assert mha.d_head == 8


def test_multihead_rejects_bad_head_count():
    with pytest.raises(ValueError):
        s.MultiHeadAttention(d_model=30, n_heads=4)


def test_multihead_causal_is_autoregressive():
    """Changing a later token must not change an earlier token's output."""
    torch.manual_seed(0)
    mha = s.MultiHeadAttention(d_model=16, n_heads=2, causal=True).eval()
    x = torch.randn(1, 6, 16)
    with torch.no_grad():
        a = mha(x)
        x2 = x.clone()
        x2[0, 5] = torch.randn(16)
        b = mha(x2)
    assert torch.allclose(a[0, :5], b[0, :5], atol=1e-6), (
        "earlier positions changed when a later token changed — mask is wrong"
    )


def test_does_not_call_builtin_attention():
    import inspect

    src = inspect.getsource(s)
    assert "nn.MultiheadAttention" not in src
    assert "F.scaled_dot_product_attention" not in src
    assert "functional.scaled_dot_product_attention" not in src
