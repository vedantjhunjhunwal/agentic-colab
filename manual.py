"""The AIDL (Agentic AI DSL) syntax manual, surfaced inside each notebook."""

AIDL_MANUAL = r"""# Agentic AI DSL (AIDL) — syntax manual

AIDL is a **Python-like** language with first-class AI primitives. Any cell can
run **Python** or **AIDL** — pick the language from the selector on the cell.
Reference uploaded datasets by name, exactly like Colab.

---

## 1. Values & variables
```
name = "Ada"
count = 42
ratio = 3.14
ok = true            # booleans: true / false
nothing = none       # null value
items = [1, 2, 3]    # lists
```

## 2. Printing & expressions
```
print("hello", name, count)
total = (count + 8) * 2
print(total % 5, total ** 2, total // 3)
```
Operators: `+  -  *  /  //  %  **`, comparisons `== != < <= > >=`,
membership `in`, logic `and or not`.

## 3. Lists & indexing
```
xs = [10, 20, 30]
print(xs[0], xs[-1], len(xs))
xs[1] = 99
```

## 4. Conditionals
```
if count > 40:
    print("big")
elif count == 40:
    print("exactly forty")
else:
    print("small")
```

## 5. Loops
```
for i in range(5):
    print(i)

n = 3
while n > 0:
    print(n)
    n = n - 1        # break / continue supported
```

## 6. Functions
```
def square(n):
    return n * n

def greet(name, prefix="Hello"):
    return prefix + ", " + name

print(square(7))
print(greet("Ada"))
```

## 7. Datasets
```
data = load("titanic.csv")     # CSV / XLSX / JSON from the Files panel
print(data.rows, data.cols)
print(data.columns)
print(data.head(5))
print(data.describe())
values = data.column("age")
```

---

# Machine learning primitives

## 8. Supervised learning
```
data  = load("data.csv")
model = classifier(target="label", algorithm="random_forest")
model.train(data, epochs=20)
print("accuracy", model.accuracy)
print(model.predict(data, row=0))
```
* `classifier(target=, algorithm=)` — algorithms: `logistic`, `random_forest`,
  `svm`, `knn`, `decision_tree`, `gradient_boosting`, `naive_bayes`.
* `regressor(target=, algorithm=)` — `linear`, `random_forest`, `svm`, `knn`,
  `decision_tree`, `gradient_boosting`. Metric is `model.score` (R²).
* If `target=` is omitted, AIDL infers it (a column named target/label/class/y…
  or the last column).

## 9. Unsupervised learning
```
data = load("data.csv")

km = cluster(k=3)              # K-Means
km.fit(data)
print(km.labels, km.centers, km.inertia)

pca = decompose(components=2)  # PCA dimensionality reduction
pca.fit(data)
print(pca.explained, pca.total_explained)
```

## 10. Neural networks & deep learning
```
net = neural_network(task="classification", layers=[64, 32], epochs=50)
net.train(load("data.csv"))
print(net.accuracy)
```
`neural_network(task=, layers=[...], epochs=, target=)` builds a multi-layer
network; `layers` sets the hidden-layer sizes. `deep_network(...)` is an alias.

## 11. Reinforcement learning
```
rl = reinforce(episodes=300)   # Q-learning on a built-in grid-world
rl.train()
print("avg reward", rl.reward)
print(rl.policy)               # learned action per state
```

## 12. Generative & agentic AI
```
text = generate("Write a haiku about machine learning")
print(text)

data = load("data.csv")
plan = agent("Profile this dataset and suggest a model", data)
print(plan)
```
`generate(prompt)` and `agent(task, data)` use a hosted LLM when one is
configured (server `AGENT_LLM_PROVIDER` + API key, or a provider chosen in
**Assistant settings**). Without a key they return a deterministic plan/notice,
so cells still run.

---

## 13. Built-in functions
`print  len  range  str  int  float  bool  round  abs  min  max  sum  mean
sorted  list  type` — plus the ML builtins above (`load`, `classifier`,
`regressor`, `neural_network`, `deep_network`, `cluster`, `decompose`/`pca`,
`reinforce`/`q_learning`, `generate`, `agent`).

## 14. A complete example
```
data  = load("customers.csv")
print("rows", data.rows, "cols", data.cols)

model = classifier(target="target", algorithm="gradient_boosting")
model.train(data, epochs=30)
print("accuracy", round(model.accuracy, 3))

for i in range(5):
    print("row", i, "->", model.predict(data, row=i))
```

> Tip: in **Python** cells you also have the full scientific stack
> (`pandas`, `numpy`, `scikit-learn`, `matplotlib`), shell commands with
> `!pip install ...`, and cell magics like `%%writefile`.
"""
