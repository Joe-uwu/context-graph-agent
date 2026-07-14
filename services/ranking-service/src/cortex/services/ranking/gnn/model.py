"""A 2-layer message-passing GNN (GCN-style) with a scalar urgency readout, in NumPy.

forward: H1 = relu(A X W1 + b1); H2 = relu(A H1 W2 + b2); p = sigmoid(H2[anchor] w_out + b_out).
backward: analytic gradients for BCE loss w.r.t. every parameter (no autograd framework).
Graphs are batched block-diagonally (one big sparse-ish A) so a whole minibatch scores in a few
matmuls. Weights serialize to a single .npz with the feature schema for reproducible inference.
"""

from __future__ import annotations

import numpy as np

from cortex.services.ranking.gnn.features import FEATURE_DIM, FEATURE_VERSION, LABELS, SOURCES


def _relu(x: np.ndarray) -> np.ndarray:
    return np.maximum(0.0, x)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0)))


class GNNModel:
    def __init__(self, in_dim: int = FEATURE_DIM, hidden: int = 32, seed: int = 0) -> None:
        rng = np.random.default_rng(seed)

        def he(a: int, b: int) -> np.ndarray:
            return rng.standard_normal((a, b)) * np.sqrt(2.0 / a)

        self.in_dim = in_dim
        self.hidden = hidden
        self.W1 = he(in_dim, hidden)
        self.b1 = np.zeros(hidden)
        self.W2 = he(hidden, hidden)
        self.b2 = np.zeros(hidden)
        self.wout = he(hidden, 1) * 0.5
        self.bout = np.zeros(1)
        self._cache: tuple | None = None

    # --- inference / training forward ------------------------------------------

    def forward(self, X: np.ndarray, A: np.ndarray, anchor_idx, *, train: bool = False) -> np.ndarray:
        Z1 = A @ (X @ self.W1) + self.b1
        H1 = _relu(Z1)
        Z2 = A @ (H1 @ self.W2) + self.b2
        H2 = _relu(Z2)
        idx = np.asarray(anchor_idx)
        Ha = H2[idx]
        logit = Ha @ self.wout + self.bout
        p = _sigmoid(logit)[:, 0]
        if train:
            self._cache = (X, A, Z1, H1, Z2, H2, idx, p)
        return p

    def score_one(self, X: np.ndarray, A: np.ndarray, anchor_idx: int) -> float:
        return float(self.forward(X, A, [anchor_idx])[0])

    # --- backprop (BCE loss, mean over the batch) ------------------------------

    def backward(self, y: np.ndarray) -> dict[str, np.ndarray]:
        X, A, Z1, H1, Z2, H2, idx, p = self._cache
        batch = len(idx)
        dlogit = ((p - y) / batch)[:, None]           # dL/dlogit  [B,1]
        g_wout = H2[idx].T @ dlogit                   # [hidden,1]
        g_bout = dlogit.sum(axis=0)
        dHa = dlogit @ self.wout.T                    # [B,hidden]

        dH2 = np.zeros_like(H2)
        np.add.at(dH2, idx, dHa)                      # scatter anchor grads
        dZ2 = dH2 * (Z2 > 0)
        g_W2 = (A @ H1).T @ dZ2
        g_b2 = dZ2.sum(axis=0)

        dH1 = A.T @ (dZ2 @ self.W2.T)
        dZ1 = dH1 * (Z1 > 0)
        g_W1 = (A @ X).T @ dZ1
        g_b1 = dZ1.sum(axis=0)
        return {"W1": g_W1, "b1": g_b1, "W2": g_W2, "b2": g_b2, "wout": g_wout, "bout": g_bout}

    def params(self) -> dict[str, np.ndarray]:
        return {"W1": self.W1, "b1": self.b1, "W2": self.W2, "b2": self.b2,
                "wout": self.wout, "bout": self.bout}

    # --- persistence -----------------------------------------------------------

    def save(self, path: str) -> None:
        np.savez(
            path,
            W1=self.W1, b1=self.b1, W2=self.W2, b2=self.b2, wout=self.wout, bout=self.bout,
            in_dim=np.array(self.in_dim), hidden=np.array(self.hidden),
            feature_version=np.array(FEATURE_VERSION),
            labels=np.array(LABELS), sources=np.array(SOURCES),
        )

    @classmethod
    def load(cls, path: str) -> GNNModel:
        data = np.load(path, allow_pickle=False)
        if int(data["feature_version"]) != FEATURE_VERSION:
            raise ValueError("GNN weights feature_version mismatch; retrain the model")
        if list(data["labels"]) != LABELS or list(data["sources"]) != SOURCES:
            raise ValueError("GNN weights schema mismatch; retrain the model")
        model = cls(in_dim=int(data["in_dim"]), hidden=int(data["hidden"]))
        model.W1, model.b1 = data["W1"], data["b1"]
        model.W2, model.b2 = data["W2"], data["b2"]
        model.wout, model.bout = data["wout"], data["bout"]
        return model


class Adam:
    """Minimal Adam optimizer over the model's parameter dict."""

    def __init__(self, model: GNNModel, lr: float = 0.01, betas=(0.9, 0.999), eps: float = 1e-8) -> None:
        self._m = model
        self._lr = lr
        self._b1, self._b2 = betas
        self._eps = eps
        self._t = 0
        self._mt = {k: np.zeros_like(v) for k, v in model.params().items()}
        self._vt = {k: np.zeros_like(v) for k, v in model.params().items()}

    def step(self, grads: dict[str, np.ndarray]) -> None:
        self._t += 1
        for k, p in self._m.params().items():
            g = grads[k]
            self._mt[k] = self._b1 * self._mt[k] + (1 - self._b1) * g
            self._vt[k] = self._b2 * self._vt[k] + (1 - self._b2) * (g * g)
            m_hat = self._mt[k] / (1 - self._b1 ** self._t)
            v_hat = self._vt[k] / (1 - self._b2 ** self._t)
            p -= self._lr * m_hat / (np.sqrt(v_hat) + self._eps)


def bce_loss(p: np.ndarray, y: np.ndarray) -> float:
    eps = 1e-7
    p = np.clip(p, eps, 1 - eps)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
