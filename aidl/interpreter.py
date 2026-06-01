"""Tree-walking interpreter for AIDL v2 — the Agentic AI DSL.

AIDL is a Python-like language with first-class AI/ML primitives covering the
full spectrum of machine learning:

    # supervised
    data  = load("iris.csv")
    model = classifier(target="species", algorithm="random_forest")
    model.train(data, epochs=20)
    p = model.predict(data, row=0)

    # unsupervised
    km   = cluster(k=3); km.fit(data)
    pca  = decompose(components=2); pca.fit(data)

    # neural networks / deep learning
    net  = neural_network(task="classification", layers=[64, 32], epochs=50)
    net.train(data)

    # reinforcement learning
    rl   = reinforce(episodes=300); rl.train()

    # generative + agentic AI
    text = generate("Write a haiku about data")
    plan = agent("Summarize this dataset", data)

Datasets resolve their paths against ``base_dir`` (the notebook's file area),
exactly like Colab's working directory.
"""
from __future__ import annotations

import builtins as _py_builtins
import io
import random
from pathlib import Path
from typing import Any, Callable, List, Optional

from . import ast_nodes as A
from .errors import (
    AIDLError,
    AIDLNameError,
    AIDLRuntimeError,
    AIDLTypeError,
    AIDLValueError,
)
from .parser import parse

MAX_STEPS = 5_000_000        # guard against runaway loops
MAX_OUTPUT_CHARS = 400_000   # guard against unbounded output


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class _Return(Exception):
    def __init__(self, value):
        self.value = value


# --------------------------------------------------------------------------
#  User-defined functions
# --------------------------------------------------------------------------
class Function:
    def __init__(self, name, params, body):
        self.name = name
        self.params = params          # list of (name, default_node_or_None)
        self.body = body

    def __repr__(self):
        return f"<function {self.name}({', '.join(p[0] for p in self.params)})>"


# --------------------------------------------------------------------------
#  ML object types
# --------------------------------------------------------------------------
class Dataset:
    """Thin wrapper around a pandas DataFrame loaded from the file area."""

    def __init__(self, name: str, dataframe):
        self.name = name
        self.df = dataframe

    @property
    def rows(self):
        return int(len(self.df))

    @property
    def cols(self):
        return int(len(self.df.columns))

    @property
    def columns(self):
        return [str(c) for c in self.df.columns]

    @property
    def shape(self):
        return [self.rows, self.cols]

    def head(self, n: int = 5):
        return self.df.head(int(n)).to_string()

    def tail(self, n: int = 5):
        return self.df.tail(int(n)).to_string()

    def describe(self):
        return self.df.describe(include="all").to_string()

    def column(self, name):
        if name not in self.df.columns:
            raise AIDLValueError(f"column {name!r} not found")
        return [self._scalar(v) for v in self.df[name].tolist()]

    @staticmethod
    def _scalar(v):
        try:
            return v.item()
        except Exception:
            return v

    def __repr__(self):
        return f"<Dataset {self.name!r}: {self.rows} rows x {self.cols} cols>"


_ALGORITHMS = {
    "classification": {
        "logistic": ("sklearn.linear_model", "LogisticRegression", {"max_iter": 1000}),
        "random_forest": ("sklearn.ensemble", "RandomForestClassifier", {"n_estimators": 100}),
        "svm": ("sklearn.svm", "SVC", {}),
        "knn": ("sklearn.neighbors", "KNeighborsClassifier", {}),
        "decision_tree": ("sklearn.tree", "DecisionTreeClassifier", {}),
        "gradient_boosting": ("sklearn.ensemble", "GradientBoostingClassifier", {}),
        "naive_bayes": ("sklearn.naive_bayes", "GaussianNB", {}),
    },
    "regression": {
        "linear": ("sklearn.linear_model", "LinearRegression", {}),
        "random_forest": ("sklearn.ensemble", "RandomForestRegressor", {"n_estimators": 100}),
        "svm": ("sklearn.svm", "SVR", {}),
        "knn": ("sklearn.neighbors", "KNeighborsRegressor", {}),
        "decision_tree": ("sklearn.tree", "DecisionTreeRegressor", {}),
        "gradient_boosting": ("sklearn.ensemble", "GradientBoostingRegressor", {}),
    },
}


class Model:
    """A trainable supervised model (classification/regression), incl. neural nets."""

    def __init__(self, task: str, target: Optional[str] = None,
                 algorithm: Optional[str] = None, layers=None, epochs: int = 10,
                 kind: str = "standard"):
        self.task = task
        self.target = target
        self.algorithm = algorithm or ("linear" if task == "regression" else "logistic")
        self.kind = kind                     # 'standard' | 'neural'
        self.layers = layers or [64, 32]
        self.default_epochs = epochs
        self.pipeline = None
        self.trained = False
        self.metric_name = None
        self.metric_value = None
        self.feature_columns: List[str] = []
        self.target_col = None

    @staticmethod
    def _infer_target(df, requested):
        if requested:
            for c in df.columns:
                if str(c).lower() == str(requested).lower():
                    return c
            raise AIDLValueError(f"target column {requested!r} not found in dataset")
        preferred = ["target", "label", "class", "y", "output", "species",
                     "disease_status", "result"]
        lowered = {str(c).lower(): c for c in df.columns}
        for p in preferred:
            if p in lowered:
                return lowered[p]
        if len(df.columns) >= 2:
            return df.columns[-1]
        raise AIDLValueError("could not infer a target column")

    def _make_estimator(self, epochs):
        import importlib
        if self.kind == "neural":
            from sklearn.neural_network import MLPClassifier, MLPRegressor
            hidden = tuple(int(x) for x in self.layers)
            if self.task == "regression":
                return MLPRegressor(hidden_layer_sizes=hidden, max_iter=int(epochs) * 20)
            return MLPClassifier(hidden_layer_sizes=hidden, max_iter=int(epochs) * 20)
        table = _ALGORITHMS.get(self.task, {})
        if self.algorithm not in table:
            raise AIDLValueError(
                f"unknown algorithm {self.algorithm!r} for {self.task}; "
                f"choose from {', '.join(table)}"
            )
        mod_name, cls_name, kwargs = table[self.algorithm]
        mod = importlib.import_module(mod_name)
        return getattr(mod, cls_name)(**kwargs)

    def _build_pipeline(self, X, epochs):
        from sklearn.compose import ColumnTransformer
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler

        numeric = X.select_dtypes(include=["number", "bool"]).columns.tolist()
        categorical = [c for c in X.columns if c not in numeric]
        num_t = Pipeline([("impute", SimpleImputer(strategy="median")),
                          ("scale", StandardScaler())])
        cat_t = Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
                          ("oh", OneHotEncoder(handle_unknown="ignore"))])
        pre = ColumnTransformer([("num", num_t, numeric), ("cat", cat_t, categorical)])
        return Pipeline([("pre", pre), ("model", self._make_estimator(epochs))])

    def train(self, dataset, epochs: int = None):
        from sklearn.metrics import accuracy_score, r2_score
        if epochs is None:
            epochs = self.default_epochs
        if not isinstance(dataset, Dataset):
            raise AIDLTypeError("train() expects a dataset (use load(\"file.csv\"))")
        df = dataset.df
        target_col = self._infer_target(df, self.target)
        X = df.drop(columns=[target_col])
        y = df[target_col]
        if X.shape[1] == 0:
            raise AIDLValueError("dataset has no feature columns to train on")
        self.pipeline = self._build_pipeline(X, epochs)
        try:
            self.pipeline.fit(X, y)
        except Exception as exc:
            raise AIDLRuntimeError(f"training failed: {exc}")
        preds = self.pipeline.predict(X)
        if self.task == "regression":
            self.metric_name, self.metric_value = "r2", float(r2_score(y, preds))
        else:
            self.metric_name, self.metric_value = "accuracy", float(accuracy_score(y, preds))
        self.trained = True
        self.target_col = target_col
        self.feature_columns = list(X.columns)
        return self.metric_value

    def predict(self, dataset, row: int = 0):
        if not self.trained:
            raise AIDLRuntimeError("model is not trained yet; call model.train(data) first")
        if not isinstance(dataset, Dataset):
            raise AIDLTypeError("predict() expects a dataset")
        df = dataset.df
        X = df.drop(columns=[self.target_col]) if self.target_col in df.columns else df
        row = int(row)
        if row < 0 or row >= len(X):
            raise AIDLValueError(f"row {row} is out of range (0..{len(X) - 1})")
        try:
            value = self.pipeline.predict(X.iloc[[row]])[0]
        except Exception as exc:
            raise AIDLRuntimeError(f"prediction failed: {exc}")
        return value.item() if hasattr(value, "item") else value

    @property
    def accuracy(self):
        return self.metric_value

    @property
    def score(self):
        return self.metric_value

    def __repr__(self):
        state = "trained" if self.trained else "untrained"
        extra = f", {self.metric_name}={self.metric_value:.4f}" if self.metric_value is not None else ""
        kind = "neural_network" if self.kind == "neural" else self.algorithm
        return f"<Model {self.task}/{kind} {state}{extra}>"


class ClusterModel:
    """Unsupervised KMeans clustering."""

    def __init__(self, k: int = 3):
        self.k = int(k)
        self.model = None
        self.trained = False
        self._labels = []
        self._centers = []

    def fit(self, dataset, epochs: int = None):
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
        from sklearn.impute import SimpleImputer
        if not isinstance(dataset, Dataset):
            raise AIDLTypeError("fit() expects a dataset")
        X = dataset.df.select_dtypes(include=["number", "bool"])
        if X.shape[1] == 0:
            raise AIDLValueError("clustering needs numeric columns")
        X = SimpleImputer(strategy="median").fit_transform(X)
        X = StandardScaler().fit_transform(X)
        self.model = KMeans(n_clusters=self.k, n_init=10, random_state=0)
        labels = self.model.fit_predict(X)
        self._labels = [int(v) for v in labels]
        self._centers = [[float(v) for v in c] for c in self.model.cluster_centers_]
        self.trained = True
        return self.inertia

    @property
    def labels(self):
        return list(self._labels)

    @property
    def centers(self):
        return [list(c) for c in self._centers]

    @property
    def inertia(self):
        return float(self.model.inertia_) if self.model is not None else None

    def __repr__(self):
        return f"<ClusterModel k={self.k} {'fitted' if self.trained else 'unfitted'}>"


class Decomposer:
    """Dimensionality reduction with PCA."""

    def __init__(self, components: int = 2):
        self.components = int(components)
        self.model = None
        self.trained = False
        self._explained = []

    def fit(self, dataset):
        from sklearn.decomposition import PCA
        from sklearn.preprocessing import StandardScaler
        from sklearn.impute import SimpleImputer
        if not isinstance(dataset, Dataset):
            raise AIDLTypeError("fit() expects a dataset")
        X = dataset.df.select_dtypes(include=["number", "bool"])
        if X.shape[1] == 0:
            raise AIDLValueError("PCA needs numeric columns")
        X = SimpleImputer(strategy="median").fit_transform(X)
        X = StandardScaler().fit_transform(X)
        n = min(self.components, X.shape[1])
        self.model = PCA(n_components=n)
        self.model.fit(X)
        self._explained = [float(v) for v in self.model.explained_variance_ratio_]
        self.trained = True
        return self.explained

    @property
    def explained(self):
        return list(self._explained)

    @property
    def total_explained(self):
        return float(sum(self._explained))

    def __repr__(self):
        return f"<Decomposer components={self.components} {'fitted' if self.trained else 'unfitted'}>"


class RLAgent:
    """A tabular Q-learning agent on a built-in grid-world (real RL, no deps)."""

    def __init__(self, size: int = 4, episodes: int = 200, alpha: float = 0.1,
                 gamma: float = 0.95, epsilon: float = 0.1):
        self.size = int(size)
        self.episodes = int(episodes)
        self.alpha = float(alpha)
        self.gamma = float(gamma)
        self.epsilon = float(epsilon)
        self.Q = {}
        self.trained = False
        self._reward = None
        self._steps = None

    def _step(self, s, a):
        x, y = s
        if a == 0: y -= 1
        elif a == 1: y += 1
        elif a == 2: x -= 1
        elif a == 3: x += 1
        x = max(0, min(self.size - 1, x))
        y = max(0, min(self.size - 1, y))
        ns = (x, y)
        goal = (self.size - 1, self.size - 1)
        if ns == goal:
            return ns, 1.0, True
        return ns, -0.01, False

    def train(self, episodes: int = None):
        rng = random.Random(0)
        ep = int(episodes) if episodes is not None else self.episodes
        goal = (self.size - 1, self.size - 1)
        total = 0.0
        last_steps = 0
        for _ in range(ep):
            s = (0, 0)
            done = False
            steps = 0
            ep_reward = 0.0
            while not done and steps < 100:
                self.Q.setdefault(s, [0.0, 0.0, 0.0, 0.0])
                if rng.random() < self.epsilon:
                    a = rng.randint(0, 3)
                else:
                    a = max(range(4), key=lambda i: self.Q[s][i])
                ns, r, done = self._step(s, a)
                self.Q.setdefault(ns, [0.0, 0.0, 0.0, 0.0])
                best_next = max(self.Q[ns])
                self.Q[s][a] += self.alpha * (r + self.gamma * best_next - self.Q[s][a])
                s = ns
                ep_reward += r
                steps += 1
            total += ep_reward
            last_steps = steps
        self.trained = True
        self._reward = total / ep
        self._steps = last_steps
        return self.reward

    @property
    def reward(self):
        return None if self._reward is None else round(self._reward, 4)

    @property
    def steps(self):
        return self._steps

    @property
    def policy(self):
        names = ["up", "down", "left", "right"]
        out = []
        for y in range(self.size):
            row = []
            for x in range(self.size):
                q = self.Q.get((x, y))
                row.append(names[max(range(4), key=lambda i: q[i])] if q else "?")
            out.append(row)
        return out

    def __repr__(self):
        return f"<RLAgent grid={self.size}x{self.size} {'trained' if self.trained else 'untrained'}>"


# --------------------------------------------------------------------------
#  Interpreter
# --------------------------------------------------------------------------
class Interpreter:
    def __init__(self, base_dir: str = ".", env: Optional[dict] = None,
                 llm: Optional[Callable[[str], str]] = None):
        self.base_dir = Path(base_dir).resolve()
        self.global_env: dict = env if env is not None else {}
        self.scopes: List[dict] = [self.global_env]
        self.llm = llm                       # optional callable(prompt)->str
        self.out = io.StringIO()
        self.steps = 0
        self.builtins = self._make_builtins()

    # ---- public ----
    def run(self, source: str) -> dict:
        program = parse(source)
        last = None
        for stmt in program.body:
            last = self.exec_stmt(stmt)
        text = self.out.getvalue()
        result_repr = None
        if last is not None:
            result_repr = self._display(last)
        return {"output": text, "result": result_repr}

    # ---- output helpers ----
    def _emit(self, text: str):
        self.out.write(text)
        if self.out.tell() > MAX_OUTPUT_CHARS:
            raise AIDLRuntimeError("output limit exceeded (possible runaway program)")

    @classmethod
    def _display(cls, value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "none"
        if isinstance(value, str):
            return value
        return repr(value)

    @staticmethod
    def _stringify(value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "none"
        if isinstance(value, float):
            return repr(value)
        return str(value)

    def _tick(self):
        self.steps += 1
        if self.steps > MAX_STEPS:
            raise AIDLRuntimeError("execution step limit exceeded (possible infinite loop)")

    # ---- statement execution ----
    def exec_block(self, body: List[A.Node]):
        result = None
        for stmt in body:
            result = self.exec_stmt(stmt)
        return result

    def exec_stmt(self, node: A.Node):
        self._tick()
        method = getattr(self, "_st_" + type(node).__name__, None)
        if method is None:
            raise AIDLRuntimeError(f"cannot execute {type(node).__name__}", node.line)
        return method(node)

    def _st_ExprStmt(self, node: A.ExprStmt):
        return self.eval(node.value)

    def _st_FuncDef(self, node: A.FuncDef):
        self._set(node.name, Function(node.name, node.params, node.body))
        return None

    def _st_Return(self, node: A.Return):
        value = self.eval(node.value) if node.value is not None else None
        raise _Return(value)

    def _st_Assign(self, node: A.Assign):
        value = self.eval(node.value)
        target = node.target
        if isinstance(target, A.Name):
            if node.op != "=":
                cur = self._lookup(target.ident, target.line)
                value = self._apply_aug(node.op, cur, value, node.line)
            self._set(target.ident, value)
        elif isinstance(target, A.Index):
            container = self.eval(target.target)
            idx = self.eval(target.index)
            if not isinstance(container, list):
                raise AIDLTypeError("only list items can be assigned by index", node.line)
            i = self._as_index(idx, len(container), node.line)
            if node.op != "=":
                value = self._apply_aug(node.op, container[i], value, node.line)
            container[i] = value
        else:
            raise AIDLRuntimeError("invalid assignment target", node.line)
        return None

    def _apply_aug(self, op, cur, value, line):
        base = op[0]
        try:
            if base == "+":
                return cur + value
            if base == "-":
                return cur - value
            if base == "*":
                return cur * value
            if base == "/":
                return cur / value
        except Exception as exc:
            raise AIDLTypeError(str(exc), line)

    def _st_Print(self, node: A.Print):
        parts = [self._stringify(self.eval(a)) for a in node.args]
        self._emit(" ".join(parts) + "\n")
        return None

    def _st_If(self, node: A.If):
        if self._truthy(self.eval(node.test)):
            self.exec_block(node.body)
        elif node.orelse:
            self.exec_block(node.orelse)
        return None

    def _st_While(self, node: A.While):
        while self._truthy(self.eval(node.test)):
            self._tick()
            try:
                self.exec_block(node.body)
            except _Break:
                break
            except _Continue:
                continue
        return None

    def _st_For(self, node: A.For):
        iterable = self.eval(node.iterable)
        seq = self._as_iterable(iterable, node.line)
        for item in seq:
            self._tick()
            self._set(node.var, item)
            try:
                self.exec_block(node.body)
            except _Break:
                break
            except _Continue:
                continue
        return None

    def _st_Break(self, node: A.Break):
        raise _Break()

    def _st_Continue(self, node: A.Continue):
        raise _Continue()

    # ---- expression evaluation ----
    def eval(self, node: A.Node):
        self._tick()
        method = getattr(self, "_ev_" + type(node).__name__, None)
        if method is None:
            raise AIDLRuntimeError(f"cannot evaluate {type(node).__name__}", node.line)
        return method(node)

    def _ev_Literal(self, node: A.Literal):
        return node.value

    def _ev_Name(self, node: A.Name):
        return self._lookup(node.ident, node.line)

    def _ev_ListExpr(self, node: A.ListExpr):
        return [self.eval(e) for e in node.elements]

    def _ev_Unary(self, node: A.Unary):
        v = self.eval(node.operand)
        if node.op == "not":
            return not self._truthy(v)
        if node.op == "-":
            return -v
        if node.op == "+":
            return +v
        raise AIDLRuntimeError(f"unknown unary operator {node.op}", node.line)

    def _ev_Binary(self, node: A.Binary):
        a = self.eval(node.left)
        b = self.eval(node.right)
        op = node.op
        try:
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if op == "/":
                if b == 0:
                    raise AIDLValueError("division by zero", node.line)
                return a / b
            if op == "//":
                if b == 0:
                    raise AIDLValueError("division by zero", node.line)
                return a // b
            if op == "%":
                if b == 0:
                    raise AIDLValueError("modulo by zero", node.line)
                return a % b
            if op == "**":
                return a ** b
        except (TypeError, ValueError) as exc:
            if isinstance(exc, AIDLError):
                raise
            raise AIDLTypeError(
                f"unsupported operands for {op}: {self._typename(a)} and {self._typename(b)}",
                node.line,
            )
        raise AIDLRuntimeError(f"unknown operator {op}", node.line)

    def _ev_Compare(self, node: A.Compare):
        a = self.eval(node.left)
        b = self.eval(node.right)
        op = node.op
        try:
            if op == "==":
                return a == b
            if op == "!=":
                return a != b
            if op == "<":
                return a < b
            if op == "<=":
                return a <= b
            if op == ">":
                return a > b
            if op == ">=":
                return a >= b
            if op == "in":
                return a in b
        except TypeError:
            raise AIDLTypeError(
                f"cannot compare {self._typename(a)} and {self._typename(b)} with {op}",
                node.line,
            )

    def _ev_Logical(self, node: A.Logical):
        left = self.eval(node.left)
        if node.op == "or":
            return left if self._truthy(left) else self.eval(node.right)
        return self.eval(node.right) if self._truthy(left) else left

    def _ev_Index(self, node: A.Index):
        target = self.eval(node.target)
        idx = self.eval(node.index)
        if isinstance(target, (list, str)):
            i = self._as_index(idx, len(target), node.line)
            return target[i]
        raise AIDLTypeError(f"{self._typename(target)} is not indexable", node.line)

    def _ev_Attribute(self, node: A.Attribute):
        target = self.eval(node.target)
        attr = node.attr
        if isinstance(target, (Dataset, Model, ClusterModel, Decomposer, RLAgent)):
            if hasattr(target, attr) and not attr.startswith("_"):
                return getattr(target, attr)
            raise AIDLNameError(f"{self._typename(target)} has no attribute {attr!r}", node.line)
        raise AIDLTypeError(f"{self._typename(target)} has no attribute {attr!r}", node.line)

    def _ev_Call(self, node: A.Call):
        # method call?  target.method(...)
        if isinstance(node.func, A.Attribute):
            obj = self.eval(node.func.target)
            name = node.func.attr
            args = [self.eval(a) for a in node.args]
            kwargs = {k: self.eval(v) for k, v in node.kwargs.items()}
            method = getattr(obj, name, None)
            if method is None or name.startswith("_") or not callable(method):
                raise AIDLNameError(f"{self._typename(obj)} has no method {name!r}", node.line)
            try:
                return method(*args, **kwargs)
            except (AIDLError,) as exc:
                if not exc.line:
                    exc.line = node.line
                raise
            except TypeError as exc:
                raise AIDLTypeError(str(exc), node.line)
        # plain function
        if isinstance(node.func, A.Name):
            fname = node.func.ident
            val = self._maybe_lookup(fname)
            if isinstance(val, Function):
                args = [self.eval(a) for a in node.args]
                kwargs = {k: self.eval(v) for k, v in node.kwargs.items()}
                return self._call_function(val, args, kwargs, node.line)
            fn = self.builtins.get(fname)
            if fn is None:
                raise AIDLNameError(f"{fname!r} is not defined", node.line)
            args = [self.eval(a) for a in node.args]
            kwargs = {k: self.eval(v) for k, v in node.kwargs.items()}
            try:
                return fn(*args, **kwargs)
            except (AIDLError,) as exc:
                if not exc.line:
                    exc.line = node.line
                raise
            except TypeError as exc:
                raise AIDLTypeError(f"{fname}(): {exc}", node.line)
        raise AIDLTypeError("expression is not callable", node.line)

    def _call_function(self, fn: Function, args, kwargs, line):
        if len(args) > len(fn.params):
            raise AIDLTypeError(
                f"{fn.name}() takes {len(fn.params)} argument(s) but {len(args)} given", line)
        local = {}
        for i, (pname, default) in enumerate(fn.params):
            if i < len(args):
                local[pname] = args[i]
            elif pname in kwargs:
                local[pname] = kwargs[pname]
            elif default is not None:
                local[pname] = self.eval(default)
            else:
                raise AIDLTypeError(f"{fn.name}() missing argument {pname!r}", line)
        self.scopes.append(local)
        try:
            self.exec_block(fn.body)
            return None
        except _Return as r:
            return r.value
        finally:
            self.scopes.pop()

    # ---- support ----
    def _set(self, name, value):
        self.scopes[-1][name] = value

    def _maybe_lookup(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def _lookup(self, name: str, line: int):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        if name in self.builtins:
            return self.builtins[name]
        raise AIDLNameError(f"{name!r} is not defined", line)

    @staticmethod
    def _truthy(v) -> bool:
        if isinstance(v, (list, str)):
            return len(v) > 0
        return bool(v)

    @staticmethod
    def _typename(v) -> str:
        if isinstance(v, bool):
            return "bool"
        if isinstance(v, int):
            return "int"
        if isinstance(v, float):
            return "float"
        if isinstance(v, str):
            return "string"
        if isinstance(v, list):
            return "list"
        if isinstance(v, Dataset):
            return "dataset"
        if isinstance(v, Model):
            return "model"
        if isinstance(v, ClusterModel):
            return "cluster"
        if isinstance(v, Decomposer):
            return "decomposer"
        if isinstance(v, RLAgent):
            return "rl_agent"
        if isinstance(v, Function):
            return "function"
        if v is None:
            return "none"
        return type(v).__name__

    def _as_index(self, idx, length, line):
        if isinstance(idx, bool) or not isinstance(idx, int):
            raise AIDLTypeError("index must be an integer", line)
        if idx < 0:
            idx += length
        if idx < 0 or idx >= length:
            raise AIDLValueError(f"index {idx} out of range (0..{length - 1})", line)
        return idx

    def _as_iterable(self, value, line):
        if isinstance(value, (list, str, range)):
            return value
        raise AIDLTypeError(f"{self._typename(value)} is not iterable", line)

    # ---- builtins / ML primitives ----
    def _make_builtins(self):
        def _load(path):
            import pandas as pd
            p = Path(str(path))
            if not p.is_absolute():
                p = (self.base_dir / str(path)).resolve()
            if not p.exists():
                raise AIDLValueError(
                    f"file not found: {path}. Upload it in the Files sidebar first."
                )
            try:
                if str(p).lower().endswith((".xlsx", ".xls")):
                    df = pd.read_excel(p)
                elif str(p).lower().endswith(".json"):
                    df = pd.read_json(p)
                else:
                    df = pd.read_csv(p)
            except Exception as exc:
                raise AIDLValueError(f"could not read {path}: {exc}")
            if df.empty:
                raise AIDLValueError(f"dataset {path} is empty")
            return Dataset(str(path), df)

        # ---- supervised ----
        def _classifier(target=None, algorithm=None):
            return Model("classification", target, algorithm=algorithm)

        def _regressor(target=None, algorithm=None):
            return Model("regression", target, algorithm=algorithm)

        # ---- neural networks / deep learning ----
        def _neural_network(task="classification", layers=None, epochs=10, target=None):
            task = str(task).lower()
            if task not in ("classification", "regression"):
                raise AIDLValueError("neural_network task must be 'classification' or 'regression'")
            return Model(task, target, layers=layers, epochs=int(epochs), kind="neural")

        # ---- unsupervised ----
        def _cluster(k=3):
            return ClusterModel(k=int(k))

        def _decompose(components=2):
            return Decomposer(components=int(components))

        # ---- reinforcement learning ----
        def _reinforce(episodes=200, size=4):
            return RLAgent(size=int(size), episodes=int(episodes))

        # ---- generative / agentic AI ----
        def _generate(prompt, max_tokens=256):
            text = str(prompt)
            if self.llm:
                try:
                    return self.llm(text)
                except Exception as exc:
                    return f"[generate] LLM error: {exc}"
            return ("[generate] No language model is configured. Set AGENT_LLM_PROVIDER "
                    "and an API key on the server, or pick a provider in Assistant "
                    f"settings, to generate real text for: {text!r}")

        def _agent(task, data=None, steps=3):
            t = str(task)
            ctx = ""
            if isinstance(data, Dataset):
                ctx = (f"\nDataset {data.name!r}: {data.rows} rows x {data.cols} cols; "
                       f"columns: {', '.join(data.columns[:12])}.")
            if self.llm:
                try:
                    return self.llm(
                        f"You are an autonomous data agent. Task: {t}.{ctx}\n"
                        f"Think step by step and produce a concise result.")
                except Exception as exc:
                    return f"[agent] LLM error: {exc}"
            plan = [f"1. Understand the task: {t}",
                    "2. Inspect the available data",
                    "3. Choose an approach and produce a result"]
            return ("[agent] No language model configured — returning a deterministic plan." +
                    ctx + "\nPlan:\n" + "\n".join(plan))

        # ---- general helpers ----
        def _range(*a):
            try:
                return list(_py_builtins.range(*[int(x) for x in a]))
            except TypeError as exc:
                raise AIDLTypeError(f"range(): {exc}")

        def _len(x):
            if isinstance(x, Dataset):
                return x.rows
            try:
                return len(x)
            except TypeError:
                raise AIDLTypeError(f"len(): {self._typename(x)} has no length")

        def _round(x, ndigits=None):
            return round(x, ndigits) if ndigits is not None else round(x)

        def _sorted(x, reverse=False):
            return sorted(x, reverse=bool(reverse))

        def _mean(x):
            seq = list(x)
            if not seq:
                raise AIDLValueError("mean() of empty sequence")
            return sum(seq) / len(seq)

        def _print_fn(*a):
            self._emit(" ".join(self._stringify(v) for v in a) + "\n")
            return None

        return {
            "load": _load,
            "classifier": _classifier,
            "regressor": _regressor,
            "neural_network": _neural_network,
            "deep_network": _neural_network,
            "cluster": _cluster,
            "decompose": _decompose,
            "pca": _decompose,
            "reinforce": _reinforce,
            "q_learning": _reinforce,
            "generate": _generate,
            "agent": _agent,
            "range": _range,
            "len": _len,
            "str": lambda x: self._stringify(x),
            "int": lambda x: int(x),
            "float": lambda x: float(x),
            "bool": lambda x: self._truthy(x),
            "round": _round,
            "abs": abs,
            "min": lambda *a: min(a[0]) if len(a) == 1 else min(a),
            "max": lambda *a: max(a[0]) if len(a) == 1 else max(a),
            "sum": lambda x: sum(x),
            "mean": _mean,
            "sorted": _sorted,
            "list": lambda x=None: list(x) if x is not None else [],
            "type": lambda x: self._typename(x),
            "print": _print_fn,
        }


def run_source(source: str, base_dir: str = ".", env: Optional[dict] = None,
               llm: Optional[Callable[[str], str]] = None) -> dict:
    """Convenience wrapper used by the kernel/server."""
    return Interpreter(base_dir=base_dir, env=env, llm=llm).run(source)
