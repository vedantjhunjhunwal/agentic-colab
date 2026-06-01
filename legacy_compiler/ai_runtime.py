from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, LinearRegression
from sklearn.metrics import accuracy_score, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


@dataclass
class AIRuntimeError(Exception):
    message: str
    line: int
    col: int = 1

    def __str__(self) -> str:
        return self.message


class AIWorkflowRuntime:
    def __init__(self, source: str, base_dir: Optional[str] = None):
        self.source = source
        self.lines = source.splitlines()
        self.base_dir = Path(base_dir or '.').resolve()
        self.pipeline_name = None
        self.datasets: Dict[str, Dict[str, Any]] = {}
        self.models: Dict[str, Dict[str, Any]] = {}
        self.settings: Dict[str, Any] = {}
        self.output: List[str] = []
        self.warnings: List[str] = []

    def execute(self) -> Dict[str, Any]:
        active = False
        for idx, raw in enumerate(self.lines, start=1):
            line = raw.strip()
            if not line or line.startswith('#'):
                continue

            m = re.match(r'^PIPELINE\s+(\w+)$', line, re.I)
            if m:
                self.pipeline_name = m.group(1)
                active = True
                self.output.append(f'Pipeline Started: {self.pipeline_name}')
                continue

            if re.match(r'^ENDPIPELINE$', line, re.I):
                if self.pipeline_name:
                    self.output.append(f'Pipeline Completed: {self.pipeline_name}')
                active = False
                continue

            if not active:
                raise AIRuntimeError('Statements must appear inside PIPELINE ... ENDPIPELINE', idx, 1)

            m = re.match(r"^DATASET\s+(\w+)\s+FROM\s+'([^']+)'$", line, re.I)
            if m:
                self._load_dataset(m.group(1), m.group(2), idx)
                continue

            m = re.match(r"^MODEL\s+(\w+)\s+TASK\s+'([^']+)'$", line, re.I)
            if m:
                self._register_model(m.group(1), m.group(2), idx)
                continue

            m = re.match(r'^SET\s+(\w+)\s*=\s*(-?\d+)$', line, re.I)
            if m:
                name, value = m.groups()
                self.settings[name.lower()] = int(value)
                self.output.append(f'Set {name} = {value}')
                continue

            m = re.match(r'^TRAIN\s+(\w+)\s+ON\s+(\w+)\s+EPOCHS\s+(\d+)$', line, re.I)
            if m:
                self._train_model(m.group(1), m.group(2), int(m.group(3)), idx)
                continue

            m = re.match(r'^EVALUATE\s+(\w+)$', line, re.I)
            if m:
                self._evaluate(m.group(1), idx)
                continue

            m = re.match(r'^PREDICT\s+(\w+)\s+INPUT\s*(-?\d+)\s+INTO\s+(\w+)$', line, re.I)
            if m:
                self._predict(m.group(1), int(m.group(2)), m.group(3), idx)
                continue

            m = re.match(r"^DEPLOY\s+(\w+)\s+TO\s+'([^']+)'$", line, re.I)
            if m:
                model, target = m.groups()
                self._require_model(model, idx)
                self.models[model.lower()]['deployed_to'] = target
                self.output.append(f'Deployment Successful: {model} -> {target}')
                continue

            m = re.match(r'^MONITOR\s+(\w+)$', line, re.I)
            if m:
                model = self._require_model(m.group(1), idx)
                info = self.models[model]
                status = 'trained' if info.get('trained') else 'registered'
                metric = info.get('metric_name')
                value = info.get('metric_value')
                suffix = f', {metric}={value:.4f}' if metric and value is not None else ''
                self.output.append(f'Monitoring {model}: status={status}{suffix}')
                continue

            m = re.match(r"^LOG\s+'([^']*)'$", line, re.I)
            if m:
                self.output.append(m.group(1))
                continue

            raise AIRuntimeError('Unsupported AI DSL statement', idx, 1)

        return {'output': '\n'.join(self.output), 'warnings': self.warnings}

    def _dataset_path(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = (self.base_dir / path).resolve()
        return p

    def _load_dataset(self, name: str, path: str, line: int):
        file_path = self._dataset_path(path)
        if not file_path.exists():
            raise AIRuntimeError(f"Dataset file not found: {path}", line, 1)
        try:
            df = pd.read_csv(file_path)
        except Exception as exc:
            raise AIRuntimeError(f"Failed to read dataset '{path}': {exc}", line, 1)
        if df.empty:
            raise AIRuntimeError(f"Dataset '{path}' is empty", line, 1)
        self.datasets[name.lower()] = {'path': str(file_path), 'dataframe': df}
        self.output.append(f"Dataset Loaded: {name} ({len(df)} rows, {len(df.columns)} columns)")

    def _register_model(self, name: str, task: str, line: int):
        task_normalized = task.strip().lower()
        if task_normalized not in {'classification', 'regression'}:
            self.warnings.append(f"Line {line}: task '{task}' is not fully supported; using classification semantics when possible.")
        self.models[name.lower()] = {
            'task': task_normalized,
            'trained': False,
            'pipeline': None,
            'dataset': None,
            'metric_name': None,
            'metric_value': None,
            'prediction': None,
            'prediction_var': None,
        }
        self.output.append(f"Model Registered: {name} [{task}]")

    def _require_model(self, name: str, line: int) -> str:
        key = name.lower()
        if key not in self.models:
            raise AIRuntimeError(f"Unknown model '{name}'", line, 1)
        return key

    def _require_dataset(self, name: str, line: int) -> str:
        key = name.lower()
        if key not in self.datasets:
            raise AIRuntimeError(f"Unknown dataset '{name}'", line, 1)
        return key

    def _infer_target_column(self, df: pd.DataFrame) -> Optional[str]:
        preferred = ['target', 'label', 'class', 'y', 'output']
        lowered = {c.lower(): c for c in df.columns}
        for pref in preferred:
            if pref in lowered:
                return lowered[pref]
        if len(df.columns) >= 2:
            return df.columns[-1]
        return None

    def _build_pipeline(self, X: pd.DataFrame, task: str):
        numeric_cols = X.select_dtypes(include=['number', 'bool']).columns.tolist()
        categorical_cols = [c for c in X.columns if c not in numeric_cols]
        numeric_transformer = Pipeline([
            ('imputer', SimpleImputer(strategy='median')),
            ('scaler', StandardScaler()),
        ])
        categorical_transformer = Pipeline([
            ('imputer', SimpleImputer(strategy='most_frequent')),
            ('onehot', OneHotEncoder(handle_unknown='ignore')),
        ])
        preprocess = ColumnTransformer([
            ('num', numeric_transformer, numeric_cols),
            ('cat', categorical_transformer, categorical_cols),
        ])
        if task == 'regression':
            estimator = LinearRegression()
        else:
            estimator = LogisticRegression(max_iter=1000)
        return Pipeline([
            ('preprocess', preprocess),
            ('model', estimator),
        ])

    def _train_model(self, model_name: str, dataset_name: str, epochs: int, line: int):
        model_key = self._require_model(model_name, line)
        dataset_key = self._require_dataset(dataset_name, line)
        df = self.datasets[dataset_key]['dataframe']
        target_col = self._infer_target_column(df)
        if not target_col:
            raise AIRuntimeError(f"Could not infer target column for dataset '{dataset_name}'", line, 1)
        X = df.drop(columns=[target_col])
        y = df[target_col]
        if X.empty:
            raise AIRuntimeError(f"Dataset '{dataset_name}' has no feature columns", line, 1)
        task = self.models[model_key]['task']
        effective_task = 'regression' if task == 'regression' else 'classification'
        pipeline = self._build_pipeline(X, effective_task)
        try:
            pipeline.fit(X, y)
        except Exception as exc:
            raise AIRuntimeError(f"Training failed for model '{model_name}': {exc}", line, 1)
        preds = pipeline.predict(X)
        if effective_task == 'regression':
            metric_name = 'r2'
            metric_value = float(r2_score(y, preds))
        else:
            metric_name = 'accuracy'
            metric_value = float(accuracy_score(y, preds))
        info = self.models[model_key]
        info.update({
            'trained': True,
            'pipeline': pipeline,
            'dataset': dataset_key,
            'metric_name': metric_name,
            'metric_value': metric_value,
            'epochs': epochs,
            'target_col': target_col,
            'feature_columns': list(X.columns),
        })
        self.output.append(f"Training Started: {model_name} on {dataset_name} for {epochs} epochs")
        self.output.append(f"Training {metric_name.title()}: {metric_value:.4f}")

    def _evaluate(self, model_name: str, line: int):
        model_key = self._require_model(model_name, line)
        info = self.models[model_key]
        if not info.get('trained'):
            raise AIRuntimeError(f"Model '{model_name}' has not been trained", line, 1)
        self.output.append(f"Evaluation {info['metric_name'].title()}: {info['metric_value']:.4f}")

    def _predict(self, model_name: str, row_index: int, out_var: str, line: int):
        model_key = self._require_model(model_name, line)
        info = self.models[model_key]
        if not info.get('trained'):
            raise AIRuntimeError(f"Model '{model_name}' has not been trained", line, 1)
        dataset_info = self.datasets[info['dataset']]
        df = dataset_info['dataframe']
        target_col = info['target_col']
        X = df.drop(columns=[target_col])
        if row_index < 0 or row_index >= len(X):
            raise AIRuntimeError(f"Prediction input row {row_index} is out of bounds for dataset '{info['dataset']}'", line, 1)
        row = X.iloc[[row_index]]
        try:
            pred = info['pipeline'].predict(row)[0]
        except Exception as exc:
            raise AIRuntimeError(f"Prediction failed for model '{model_name}': {exc}", line, 1)
        info['prediction'] = pred
        info['prediction_var'] = out_var
        self.output.append(f"Prediction [{out_var}] for row {row_index}: {pred}")
