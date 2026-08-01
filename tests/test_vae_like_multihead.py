from __future__ import annotations

import torch

from algorithms.vae_like_multihead import vae_like_multihead as vae_module
from algorithms.vae_like_multihead.vae_like_multihead import VAELikeMultiheadModel


def test_vae_like_multihead_shapes_and_positive_sigma() -> None:
    torch.manual_seed(7)
    model = VAELikeMultiheadModel(hidden_dim=16, backbone_depth=2, n_heads=3, sigma_eps=1e-6)
    preferences = torch.tensor([[0.2, 0.3, 0.5], [0.6, 0.1, 0.3]], dtype=torch.float32)
    mu_raw, sigma_raw = model(preferences)
    assert mu_raw.shape == (2, 3, 3)
    assert sigma_raw.shape == (2, 3, 3)
    assert torch.all(sigma_raw > 0)
    epsilon = torch.randn(2, 3, 4, 3)
    samples = mu_raw[:, :, None, :] + sigma_raw[:, :, None, :] * epsilon
    assert samples.shape == (2, 3, 4, 3)
    samples.sum().backward()
    assert all(parameter.grad is not None for parameter in model.parameters())


def test_validation_loss_uses_exact_minimum_center_score(monkeypatch) -> None:
    class DummyModel(torch.nn.Module):
        def forward(self, preferences: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
            shape = (preferences.shape[0], 2, 3)
            return torch.zeros(shape), torch.ones(shape)

    model = DummyModel()
    preferences = torch.tensor([[0.2, 0.3, 0.5], [0.6, 0.1, 0.3]], dtype=torch.float32)
    monkeypatch.setattr(vae_module, "_evaluate_objectives", lambda *args: (None, {}))
    monkeypatch.setattr(
        vae_module,
        "_scores",
        lambda *args: torch.tensor([3.0, 1.0, 4.0, 2.0], dtype=torch.float32),
    )

    value = vae_module._validation_loss(
        model,
        object(),
        object(),
        object(),
        {},
        preferences,
    )

    assert value == 1.5
    assert model.training
