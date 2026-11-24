"""The regression test: the model of Regression/docs/single_feature_model.md, tested with leave-one-out.

    leaf area = c x optical mass          (a line through zero, one number c learned from the plants)

Every plant in turn is left out, c is learned from the other plants, and the left-out plant is predicted. Each
plant is predicted by a model that never saw it.

Typical error = RMSE of those predictions as a % of the mean leaf area (the number the regression reports).
"""
import numpy as np

MODELS = ["origin", "line", "power", "mean"]
MODEL_NAME = {"origin": "c × optical mass", "line": "a + b × optical mass", "power": "a × optical mass^b",
              "mean": "average plant (no photo)"}


# ----------------------------------------------------------------------------------------------
# one run
# ----------------------------------------------------------------------------------------------

def fit(kind, x, y):
    if kind == "mean":
        return (y.mean(),)
    if kind == "origin":
        return ((x @ y) / (x @ x),)
    if kind == "line":
        b, a = np.polyfit(x, y, 1)
        return (a, b)
    if kind == "power":                        # a straight line in log-log, back-transformed (Duan smearing)
        b, la = np.polyfit(np.log(x), np.log(y), 1)
        smear = np.mean(np.exp(np.log(y) - (la + b * np.log(x))))
        return (np.exp(la) * smear, b)
    raise ValueError(kind)


def predict(kind, prm, x):
    x = np.asarray(x, float)
    if kind == "mean":
        return np.full(x.shape, prm[0])
    if kind == "origin":
        return prm[0] * x
    if kind == "line":
        return prm[0] + prm[1] * x
    return prm[0] * x ** prm[1]


def loo(kind, x, y):
    """Leave-one-out predictions, and the parameters fitted in every round."""
    n = len(x)
    pred, prms = np.zeros(n), []
    for i in range(n):
        m = np.arange(n) != i
        prm = fit(kind, x[m], y[m])
        pred[i] = predict(kind, prm, x[i:i + 1])[0]
        prms.append(prm)
    return pred, prms


def rmse(y, p):
    return float(np.sqrt(np.mean((y - p) ** 2)))


def scores(y, p):
    err = (p - y) / y * 100
    return dict(r2=float(1 - ((y - p) ** 2).sum() / ((y - y.mean()) ** 2).sum()),
                typical=100 * rmse(y, p) / y.mean(),
                mape=float(np.mean(np.abs(err))),
                mae=float(np.mean(np.abs(y - p))),
                worst=float(np.max(np.abs(err))),
                within5=int(np.sum(np.abs(err) <= 5)))


def nested_model(x, y):
    """The honest score of "pick the best of MODELS, then predict": for every left-out plant the model is chosen on
    the other plants only. Returns the predictions and the chosen model per plant."""
    n = len(x)
    pred, chosen = np.zeros(n), []
    for i in range(n):
        m = np.arange(n) != i
        best = min(MODELS, key=lambda k: rmse(y[m], loo(k, x[m], y[m])[0]))
        pred[i] = predict(best, fit(best, x[m], y[m]), x[i:i + 1])[0]
        chosen.append(best)
    return pred, chosen


def permutation(x, y, n_perm=1000, seed=0):
    """How often does c x optical mass predict as well when the leaf areas are shuffled between the plants?
    Returns (real RMSE, shuffled RMSEs, p)."""
    real = rmse(y, loo("origin", x, y)[0])
    rng = np.random.default_rng(seed)
    perm = np.array([rmse(ys, loo("origin", x, ys)[0]) for ys in (rng.permutation(y) for _ in range(n_perm))])
    return real, perm, float((np.sum(perm <= real) + 1) / (n_perm + 1))


# ----------------------------------------------------------------------------------------------
# many runs at once (c x optical mass only)
# ----------------------------------------------------------------------------------------------

def loo_origin(X, y):
    """Leave-one-out predictions of c x optical mass for many runs at once. X: runs x plants."""
    X = np.atleast_2d(X)
    sxy, sxx = X @ y, (X * X).sum(1)
    c = (sxy[:, None] - X * y) / (sxx[:, None] - X * X)      # c without plant j, per run
    return c * X


def typical(y, P):
    """Typical error (RMSE as % of the mean leaf area). P: plants, or runs x plants."""
    return 100 * np.sqrt(np.mean((P - y) ** 2, axis=-1)) / y.mean()


def nested_runs(X, y):
    """The honest score of "pick the best run, then predict": for every plant the run with the lowest leave-one-out
    error on the OTHER plants is chosen, c is learned on them, and the plant is predicted.
    Returns the predictions and the index of the chosen run per plant."""
    n = len(y)
    pred, chosen = np.zeros(n), []
    for i in range(n):
        m = np.arange(n) != i
        best = int(np.argmin(typical(y[m], loo_origin(X[:, m], y[m]))))
        c = X[best, m] @ y[m] / (X[best, m] @ X[best, m])
        pred[i] = c * X[best, i]
        chosen.append(best)
    return pred, chosen
