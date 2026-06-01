from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional

AI_KEYWORDS = (
    'PIPELINE', 'DATASET', 'MODEL', 'TRAIN', 'EVALUATE', 'PREDICT', 'DEPLOY', 'LOG', 'MONITOR', 'SET', 'ENDPIPELINE'
)


@dataclass
class AIDSLCompileError(Exception):
    message: str
    line: int
    col: int = 1

    def __str__(self):
        return f"[AI DSL ERROR] Line {self.line}, Col {self.col}: {self.message}"


@dataclass
class TranspileResult:
    source_language: str
    translated_source: str
    pipeline_name: str


def detect_ai_dsl(source: str) -> bool:
    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        upper = line.upper()
        return any(upper.startswith(k) for k in AI_KEYWORDS)
    return False


def _sanitize(name: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9]', '', name.strip())
    if not cleaned:
        return 'item'
    if cleaned[0].isdigit():
        cleaned = 'n' + cleaned
    return cleaned.lower()


def transpile_ai_dsl(source: str) -> TranspileResult:
    lines = source.splitlines()
    pipeline_name = 'AIPipeline'
    body: List[str] = []
    vars_needed = set()
    model_tasks: Dict[str, str] = {}
    datasets: Dict[str, str] = {}
    active = False

    def ensure_var(*names: str):
        for n in names:
            if n:
                vars_needed.add(_sanitize(n))

    def emit(stmt: str):
        body.append(stmt)

    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        upper = line.upper()

        if upper.startswith('PIPELINE '):
            name = line[len('PIPELINE '):].strip()
            if not name:
                raise AIDSLCompileError('PIPELINE requires a name', idx, 1)
            pipeline_name = re.sub(r'[^A-Za-z0-9_]', '', name) or 'AIPipeline'
            active = True
            emit(f"write('Starting AI pipeline: {pipeline_name}');")
            continue

        if upper == 'ENDPIPELINE':
            emit(f"write('Pipeline completed: {pipeline_name}');")
            active = False
            continue

        if not active:
            raise AIDSLCompileError('AI DSL statements must appear inside PIPELINE ... ENDPIPELINE', idx, 1)

        m = re.match(r"DATASET\s+(\w+)\s+FROM\s+'([^']+)'$", line, re.I)
        if m:
            name, path = m.groups()
            var = f"dataset_{name}"
            datasets[name.lower()] = path
            ensure_var(var)
            emit(f"{_sanitize(var)} := 1;")
            emit(f"write('Loaded dataset {name} from {path}');")
            continue

        m = re.match(r"MODEL\s+(\w+)\s+TASK\s+'([^']+)'$", line, re.I)
        if m:
            name, task = m.groups()
            model_tasks[name.lower()] = task
            ensure_var(f"model_{name}", f"trained_{name}", f"accuracy_{name}", f"deployed_{name}")
            emit(f"{_sanitize('model_' + name)} := 1;")
            emit(f"write('Registered model {name} for task {task}');")
            continue

        m = re.match(r"SET\s+(\w+)\s*=\s*(-?\d+)$", line, re.I)
        if m:
            name, value = m.groups()
            ensure_var(name)
            emit(f"{_sanitize(name)} := {value};")
            emit(f"write('Set {name} = ', {_sanitize(name)});")
            continue

        m = re.match(r"TRAIN\s+(\w+)\s+ON\s+(\w+)\s+EPOCHS\s+(\d+)$", line, re.I)
        if m:
            model, dataset, epochs = m.groups()
            if dataset.lower() not in datasets:
                raise AIDSLCompileError(f"Unknown dataset '{dataset}'", idx, 1)
            ensure_var(f"trained_{model}", f"accuracy_{model}", f"epochs_{model}")
            emit(f"{_sanitize('epochs_' + model)} := {epochs};")
            emit(f"{_sanitize('trained_' + model)} := 1;")
            emit(f"{_sanitize('accuracy_' + model)} := 70 + {epochs};")
            emit(f"write('Training model {model} on dataset {dataset} for {epochs} epochs');")
            emit(f"write('Training accuracy for {model} = ', {_sanitize('accuracy_' + model)});")
            continue

        m = re.match(r"EVALUATE\s+(\w+)$", line, re.I)
        if m:
            (model,) = m.groups()
            ensure_var(f"accuracy_{model}")
            emit(f"write('Evaluation accuracy for {model} = ', {_sanitize('accuracy_' + model)});")
            continue

        m = re.match(r"PREDICT\s+(\w+)\s+INPUT\s*(-?\d+)(?:\s+INTO\s+(\w+))?$", line, re.I)
        if m:
            model, value, out = m.groups()
            out = out or f"prediction_{model}"
            ensure_var(out, f"accuracy_{model}")
            emit(f"{_sanitize(out)} := {value} + {_sanitize('accuracy_' + model)};")
            emit(f"write('Prediction from {model} = ', {_sanitize(out)});")
            continue

        m = re.match(r"DEPLOY\s+(\w+)\s+TO\s+'([^']+)'$", line, re.I)
        if m:
            model, target = m.groups()
            ensure_var(f"deployed_{model}")
            emit(f"{_sanitize('deployed_' + model)} := 1;")
            emit(f"write('Deployed model {model} to {target}');")
            continue

        m = re.match(r"MONITOR\s+(\w+)$", line, re.I)
        if m:
            (model,) = m.groups()
            ensure_var(f"accuracy_{model}", f"deployed_{model}")
            emit(f"write('Monitoring {model}: accuracy=', {_sanitize('accuracy_' + model)}, ', deployed=', {_sanitize('deployed_' + model)});")
            continue

        m = re.match(r"LOG\s+'([^']*)'$", line, re.I)
        if m:
            (text,) = m.groups()
            emit(f"write('{text}');")
            continue

        raise AIDSLCompileError('Unsupported AI DSL statement', idx, 1)

    var_lines = []
    if vars_needed:
        ordered = sorted(vars_needed)
        # chunk declarations to keep lines readable
        chunk = []
        for name in ordered:
            chunk.append(name)
            if len(chunk) == 5:
                var_lines.append('    ' + ', '.join(chunk) + ' : integer;')
                chunk = []
        if chunk:
            var_lines.append('    ' + ', '.join(chunk) + ' : integer;')

    translated = ['program ' + pipeline_name + ';', '']
    if var_lines:
        translated.append('var')
        translated.extend(var_lines)
        translated.append('')
    translated.append('begin')
    for stmt in body:
        translated.append('    ' + stmt)
    translated.append('end.')
    translated_source = '\n'.join(translated)
    return TranspileResult(source_language='ai_workflow_dsl', translated_source=translated_source, pipeline_name=pipeline_name)
