import json
import os
import math
import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats
from scipy.stats import norm
import duckdb
import re
import ast
import operator
import threading
from pathlib import Path
import tempfile

DATASET = {}
_CON = duckdb.connect(":memory:")
_CON.execute("SET enable_external_access=false")
_CON_LOCK = threading.RLock()


SUPPORTED_EXTENSIONS = {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".xlsm", ".ods", ".json", ".jsonl", ".ndjson", ".parquet", ".feather"}


def dataset_name(filename: str) -> str:
    name = re.sub(r"\W+", "_", Path(filename).stem.lower()).strip("_") or "data"
    return f"d_{name}" if name[0].isdigit() else name


def load_data(path: str, name: str = None) -> str:
    """Loads ONE file into memory so the agent can analyse it.
    Call it manually, once per file, at the top level of core.py:
        load_data("data/sales.csv", "sales")
        load_data("data/titanic.csv")          # name defaults to the file name -> 'titanic'
    Supported: .csv .tsv .txt .xlsx .xls .json .parquet
    The name is what the agent (and SQL) will call the dataset. Spaces and symbols
    are turned into underscores so it is always a valid SQL table name.
    Raises an error if the file is missing/unreadable so a typo is noticed at start-up."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"load_data: file not found: '{path}' (current folder: {os.getcwd()})")

    ext = os.path.splitext(path)[1].lower()
    if ext in (".csv", ".txt", ".tsv"):
        sep = "\t" if ext == ".tsv" else (None if ext == ".txt" else ",")
        try:
            df = pd.read_csv(path, sep=sep, engine="python" if sep is None else "c")
        except UnicodeDecodeError:              # Excel-exported CSVs are often not UTF-8
            df = pd.read_csv(path, sep=sep, encoding="latin-1", engine="python" if sep is None else "c")
    elif ext in (".xlsx", ".xls", ".xlsm", ".ods"):
        df = pd.read_excel(path)
    elif ext == ".json":
        df = pd.read_json(path)
    elif ext in (".jsonl", ".ndjson"):
        df = pd.read_json(path, lines=True)
    elif ext == ".parquet":
        df = pd.read_parquet(path)
    elif ext == ".feather":
        df = pd.read_feather(path)
    else:
        raise ValueError(f"load_data: unsupported file type '{ext}' for '{path}'")

    if df.empty:
        raise ValueError(f"load_data: '{path}' has no rows.")

    name = dataset_name(name or path)

    with _CON_LOCK:
        DATASET[name] = df
        _CON.register(name, df)                 # re-loading the same name simply replaces it
    return f"Loaded '{name}': {len(df):,} rows x {len(df.columns)} columns (from {path})"







def calculate(expression: str) -> str:
    """Evaluate simple arithmetic and public math functions without eval()."""
    try:
        if len(expression) > 300:
            raise ValueError("Expression is too long")
        allowed_ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                       ast.Div: operator.truediv, ast.Pow: operator.pow, ast.FloorDiv: operator.floordiv}
        functions = {k: v for k, v in math.__dict__.items() if not k.startswith("_") and callable(v)}
        constants = {"pi": math.pi, "e": math.e, "tau": math.tau}

        def evaluate(node):
            if isinstance(node, ast.Expression):
                return evaluate(node.body)
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                return node.value
            if isinstance(node, ast.Name) and node.id in constants:
                return constants[node.id]
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = evaluate(node.operand)
                return value if isinstance(node.op, ast.UAdd) else -value
            if isinstance(node, ast.BinOp) and type(node.op) in allowed_ops:
                left, right = evaluate(node.left), evaluate(node.right)
                if isinstance(node.op, ast.Pow) and abs(right) > 100:
                    raise ValueError("Exponent is too large")
                return allowed_ops[type(node.op)](left, right)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in functions and not node.keywords:
                args = [evaluate(arg) for arg in node.args]
                if node.func.id in {"factorial", "comb", "perm", "isqrt"} and any(abs(value) > 10000 for value in args):
                    raise ValueError("Math argument is too large")
                return functions[node.func.id](*args)
            raise ValueError("Only arithmetic and math functions are allowed")

        result = evaluate(ast.parse(expression, mode="eval"))
        return str(result)
    except Exception as e:
        error = (f"Calculation error: {str(e)}")
        return error









# LLm calls this to see the structure of the data to know how to work with it.                                                                              
def inspect_data(name: str) -> str:
    if name not in DATASET:
        return f"Error: '{[name]}' Dataset not found. Loaded {list(DATASET)}"
    try:
        df = DATASET[name]
        summary = {
            "rows" : len(df),
            "d_types" : {col: str(dtype) for col, dtype in zip(df.columns, df.dtypes)}, # dtype is my variable name and dtypes is the function. will list all the colums with its type. So both Column list and data_type list.
            "missing_values" : df.isnull().sum().to_dict(), # isnull() returns a boolean DataFrame indicating missing   values, sum() counts them per column
            "sample" : df.head(5).to_dict(orient="records"), # head(5) is the first 5 rows of the dataset
            "stats_summary" : df.describe(include='all').fillna("").to_dict(),            
        }
    except Exception as e:
        return f"Error occurred while inspecting data: {str(e)}"

    return json.dumps(summary, indent=2, default=str) # Indent make it easy to read, pushed spaces with 2 line; like # {
                                                                                                        #   "a": 1,
                                                                                                        #   "b": 2
                                                                                                        # }








# Tool-1 SQL query tool
def safe_sql_query(query: str) -> str:
    """Executes ONE read-only query. Every loaded dataset is a table named after the dataset."""
    try:
        q = query.strip().rstrip(";").strip()
        if not q.lower().startswith(("select", "with")):
            return "Error: Only SELECT and WITH queries are allowed."
        if ";" in q:
            return "Error: Only ONE statement is allowed (remove the extra ';')."
        with _CON_LOCK:
            result = _CON.execute(q).df()  # to df() converts the result of the query to a DataFrame
        if len(result) > 50:
            return result.head(50).to_string() + f"\n\nResult truncated. Total rows: {len(result)}"
        return result.to_string()
    except Exception as e:
        return f"SQL executing error: {str(e)}. Loaded tables: {list(DATASET)}"












# Tool-2 Hypothesis testing tool
def statistical_test(name: str, test_type: str, col1: str = None, col2: str = None) -> str:
    from scipy import stats
    try:
        # 1. dataset must exist and not be empty
        if name not in DATASET:
            return f"Dataset '{name}' not found. Loaded datasets are: {list(DATASET)}"
        df = DATASET[name]
        if not isinstance(df, pd.DataFrame) or df.empty:
            return "Error: dataset is empty."

        # 2. which columns each test needs ("col1" / "col2" are the parameter names)
        needs = {
            "correlation": ["col1", "col2"],
            "two_sample_ttest": ["col1", "col2"],
            "chi_square": ["col1", "col2"],
            "zscore": ["col1"],
            "anova": ["col1", "col2"],
            "iqr": ["col1"],
            "correlation_matrix": [],
        }
        if test_type not in needs:
            return f"Unknown test_type '{test_type}'. Choose from: {list(needs)}"

        # 3. turn the parameter names into the REAL column names the user gave
        given = {"col1": col1, "col2": col2}
        cols = [given[k] for k in needs[test_type]]      # e.g. ["age", "income"]
        for c in cols:
            if c is None:
                return f"'{test_type}' needs {len(cols)} column name(s)."
            if c not in df.columns:
                return f"Column '{c}' not found. Available: {list(df.columns)}"
        if len(cols) == 2 and cols[0] == cols[1]:
            return "col1 and col2 must be two different columns."

        # 4. which of those columns must be numbers
        numeric_needed = {
            "correlation": cols, "two_sample_ttest": cols,
            "zscore": cols, "iqr": cols,
            "anova": cols[:1],        # col1 = numbers, col2 = groups (any type)
            "chi_square": [],         # categories
            "correlation_matrix": [],
        }[test_type]
        for c in numeric_needed:
            if not pd.api.types.is_numeric_dtype(df[c]):
                return f"Column '{c}' is not numeric, so '{test_type}' can't use it."

        # 5. the tests (same as yours, but using df instead of DATASET[name])
        if test_type == "correlation":
            data = df[[col1, col2]].dropna()
            if len(data) < 3:
                return "Need at least 3 complete rows for correlation."
            if data[col1].nunique() < 2 or data[col2].nunique() < 2:
                return "A column has all the same value; correlation is undefined."
            corr, p_val = stats.pearsonr(data[col1], data[col2])
            result = {"test": "Pearson Correlation", "rows_used": len(data),
                      "statistic": str(corr), "p_value": str(p_val)}

        elif test_type == "two_sample_ttest":
            a, b = df[col1].dropna(), df[col2].dropna()
            if len(a) < 2 or len(b) < 2:
                return "Each column needs at least 2 values for a t-test."
            stat, p_val = stats.ttest_ind(a, b)
            result = {"test": "Two-sample T-test",
                      "t_statistic": str(stat), "p_value": str(p_val)}

        elif test_type == "chi_square":
            data = df[[col1, col2]].dropna()
            if data[col1].nunique() > 50 or data[col2].nunique() > 50:
                return "Too many unique values; chi-square needs categorical columns."
            table = pd.crosstab(data[col1], data[col2])
            if table.shape[0] < 2 or table.shape[1] < 2:
                return "Each column needs at least 2 different categories."
            chi2, p_val, dof, _ = stats.chi2_contingency(table)
            result = {"test": "Chi-square test of independence",
                      "chi2": str(chi2), "p_value": str(p_val),
                      "degrees_of_freedom": int(dof)}

        elif test_type == "correlation_matrix":
            numeric = df.select_dtypes(include="number")
            if numeric.shape[1] < 2:
                return "Need at least 2 numeric columns."
            matrix = numeric.corr().round(3).replace({np.nan: None})
            result = {"test": "Correlation matrix", "matrix": matrix.to_dict()}

        elif test_type == "zscore":
            data = df[col1].dropna()
            if len(data) < 2 or data.std() == 0:
                return "Not enough variation to compute z-scores."
            z = (data - data.mean()) / data.std()
            outliers = data[z.abs() > 3]
            result = {"test": "Z-score outliers (|z| > 3)",
                      "outlier_count": int(len(outliers)),
                      "outlier_values": str(outliers.head(10).tolist())}

        elif test_type == "iqr":
            data = df[col1].dropna()
            if len(data) < 4:
                return "Need at least 4 values for IQR."
            q1, q3 = data.quantile(0.25), data.quantile(0.75)
            iqr = q3 - q1
            low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outliers = data[(data < low) | (data > high)]
            result = {"test": "IQR outliers",
                      "lower_bound": str(low), "upper_bound": str(high),
                      "outlier_count": int(len(outliers)),
                      "outlier_values": str(outliers.head(10).tolist())}

        elif test_type == "anova":
            data = df[[col1, col2]].dropna()
            groups = [g[col1].values for _, g in data.groupby(col2) if len(g) >= 2]
            if len(groups) < 2:
                return "Need at least 2 groups with 2+ values each for ANOVA."
            f_stat, p_val = stats.f_oneway(*groups)
            result = {"test": "One-way ANOVA", "groups_compared": len(groups),
                      "f_statistic": str(f_stat), "p_value": str(p_val)}

        return json.dumps(result, indent=2)

    except Exception as e:
        return f"{type(e).__name__}: {e}"
        









# Tool-3 Data visualization tool using Seaborn 
def visualize_data(name: str, chart_type: str, filename: str, x: str = None, y: str = None, hue: str = None, width: float = 9, height: float = 5) -> str:
    """Saves a chart. chart_type: scatter, line, bar, hist, bell, box,
    violin, pie, area, heatmap, regression. x/y are column names,
    hue is an optional column used to colour groups.
    filename: a short, descriptive, unique name that you choose based on
    what the chart shows, e.g. 'age_vs_salary_scatter' or 'sales_by_region_bar'."""
    import matplotlib
    matplotlib.use("Agg")              # draw to files only, no pop-up window
    import matplotlib.pyplot as plt
    import seaborn as sns

    SUPPORTED_CHARTS = ["scatter", "line", "bar", "hist", "bell", "box", "violin", "pie", "area", "heatmap", "regression"]

    if name not in DATASET:
            return f"Dataset '{name}' not found. Loaded datasets are: {list(DATASET)}"

    try:
        df = DATASET[name]
        chart_type = chart_type.lower()

        if chart_type not in SUPPORTED_CHARTS:
            return f"Unknown chart type. Choose from: {SUPPORTED_CHARTS}"

        # check that the column names really exist
        for col in (x, y, hue):
            if col is not None and col not in df.columns:
                return f"Column '{col}' not found. Columns are: {list(df.columns)}"

        # these charts need both x and y
        if chart_type in ("scatter", "line", "area", "regression") and (x is None or y is None):
            return f"'{chart_type}' needs both x and y."
        if chart_type != "heatmap" and x is None:
            return f"'{chart_type}' needs at least x."

        plt.figure(figsize=(width, height))

        if chart_type == "scatter":
            sns.scatterplot(data=df, x=x, y=y, hue=hue)

        elif chart_type == "regression":                 # points + best-fit line
            sns.regplot(data=df, x=x, y=y)

        elif chart_type == "line":
            sns.lineplot(data=df.sort_values(x), x=x, y=y, hue=hue)

        elif chart_type == "area":                       # filled area under a line
            d = df.sort_values(x)
            plt.fill_between(d[x], d[y], alpha=0.4)
            plt.plot(d[x], d[y])
            plt.xlabel(x); plt.ylabel(y)

        elif chart_type == "bar":
            if y:
                sns.barplot(data=df, x=x, y=y, hue=hue)  # average of y per x
            else:
                sns.countplot(data=df, x=x, hue=hue)     # how many rows per x
            plt.xticks(rotation=45, ha="right")

        elif chart_type == "hist":                       # bars + smooth line + mean
            sns.histplot(data=df, x=x, hue=hue, kde=True)
            plt.axvline(df[x].mean(), color="red", linestyle="--", label="mean")
            plt.legend()

        elif chart_type == "bell":                       # histogram + normal curve
            data = df[x].dropna()
            mean, std = data.mean(), data.std()
            plt.hist(data, bins=30, density=True, alpha=0.6, label="data")
            xs = np.linspace(data.min(), data.max(), 200)
            plt.plot(xs, norm.pdf(xs, mean, std), color="red", label="bell curve")
            plt.axvline(mean, color="black", linestyle="--", label=f"mean = {mean:.2f}")
            plt.legend()

        elif chart_type == "box":
            sns.boxplot(data=df, x=x, y=y, hue=hue)
            plt.xticks(rotation=45, ha="right")

        elif chart_type == "violin":
            sns.violinplot(data=df, x=x, y=y, hue=hue)
            plt.xticks(rotation=45, ha="right")

        elif chart_type == "pie":
            if y:
                values = df.groupby(x)[y].sum().nlargest(8)    # total of y per category
            else:
                values = df[x].value_counts().head(8)          # count per category
            plt.pie(values, labels=values.index, autopct="%1.1f%%", startangle=90)
            plt.axis("equal")

        elif chart_type == "heatmap":                    # correlation between number columns
            corr = df.select_dtypes(include="number").corr()
            sns.heatmap(corr, annot=True, cmap="coolwarm", fmt=".2f")

        title = f"{chart_type.capitalize()} of {x}" + (f" vs {y}" if y else "")
        if chart_type != "heatmap":
            plt.title(title)
        plt.tight_layout()

        output_dir = os.getenv("OUTPUT_DIR", os.path.join(tempfile.gettempdir(), "data_analyst_charts") if os.getenv("VERCEL") else "output")
        os.makedirs(output_dir, exist_ok=True)
        safe_filename = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(filename).stem).strip("_") or "chart"
        out_path = os.path.join(output_dir, safe_filename + ".png")
        plt.savefig(out_path, dpi=150)
        plt.close()
        return f"Chart successfully saved to {out_path}."

    except Exception as e:
        plt.close()
        return f"Visualization Error: {str(e)}"















# Tool-4 Data quality tool: formatting problems + data drift
def data_quality_check(name: str, check: str = "format", compare_with: str = None) -> str:
    """Finds data quality problems in a loaded dataset.
    check='format': formatting problems in ONE dataset (duplicate rows, extra spaces,
    fake missing values like '-', numbers store d as text, mixed date formats,
    the same word spelled differently like Male/male).
    check='drift': has the data CHANGED? Compares an OLD chunk with a NEW chunk.
    Give compare_with=<name of another dataset> to compare two datasets, or leave
    it empty to compare the first half of the rows with the second half."""
    import pandas as pd
    from scipy import stats

    try:
        check = check.lower()
        if check not in ("format", "drift"):
            return "Unknown check. Choose 'format' or 'drift'."
        if name not in DATASET:
            return f"Dataset '{name}' not found. Loaded datasets are: {list(DATASET)}"
        df = DATASET[name]
        issues = []                     # every problem we find is added here as one sentence

        # 1. FORMAT
        if check == "format":
            n_dup = int(df.duplicated().sum())          # rows that are exact copies of an earlier row
            if n_dup:
                issues.append(f"{n_dup} duplicate rows.")

            for col in df.columns:
                # numbers and real dates are already clean, so only look at text columns
                if pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_datetime64_any_dtype(df[col]):
                    continue
                text = df[col].dropna().astype(str)
                if text.empty:
                    continue

                # 1. spaces at the start or end:  " Male"
                n_space = int((text != text.str.strip()).sum())
                if n_space:
                    issues.append(f"'{col}': {n_space} values have extra spaces, e.g. {list(text[text != text.str.strip()].unique()[:3])}")

                # 2. fake missing values: text that means "missing" but pandas does not know
                clean = text.str.strip()
                fake = clean.str.lower().isin(["-", "--", "?", "??", "missing", "unknown", "undefined", "none", "null", "na", "n/a"])
                if fake.sum():
                    issues.append(f"'{col}': {int(fake.sum())} fake missing values, e.g. {list(clean[fake].unique()[:3])}")
                real = clean[~fake]             # from now on look only at the real values
                if real.empty:
                    continue

                # 3. numbers stored as text:  "$1,200"
                as_number = pd.to_numeric(real.str.replace(r"[,$₹%\s]", "", regex=True), errors="coerce")
                is_num = as_number.notna()
                if is_num.mean() >= 0.7:
                    msg = f"'{col}': numbers stored as text"
                    if not is_num.all():
                        msg += f", {int((~is_num).sum())} values are not numbers, e.g. {list(real[~is_num].unique()[:3])}"
                    issues.append(msg)
                    continue                    # a number column needs no spelling/date checks

                # 4. mixed date formats: turn every digit into 9, so 2024-01-05 and 05/01/2024
                #    become 9999-99-99 and 99/99/9999. More than one shape = mixed formats.
                looks_like_date = real.str.contains(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}")
                if looks_like_date.mean() >= 0.8:
                    shape = real.str.replace(r"\d", "9", regex=True)
                    if shape.nunique() > 1:
                        examples = list(real.groupby(shape).first().values[:3])
                        issues.append(f"'{col}': dates written in mixed formats, e.g. {examples}")
                    continue

                # 5. same word spelled differently: group values by their lowercase form
                spellings = real.groupby(real.str.lower()).unique()
                spellings = spellings[spellings.apply(len) > 1]
                if len(spellings):
                    issues.append(f"'{col}': same value spelled differently, e.g. {list(spellings.iloc[0])}")

            if not issues:
                return f"No formatting problems found in '{name}'."
            return f"Formatting problems in '{name}':\n" + "\n".join("- " + i for i in issues)

        # 2. DRIFT
        if compare_with:
            if compare_with not in DATASET:
                return f"Dataset '{compare_with}' not found. Loaded datasets are: {list(DATASET)}"
            old, new = df, DATASET[compare_with]
            label = f"'{name}' (old) vs '{compare_with}' (new)"
        else:
            half = len(df) // 2                         # no 2nd dataset: first half = old, second half = new
            old, new = df.iloc[:half], df.iloc[half:]
            label = f"first half vs second half of '{name}' (assumes rows are in time order)"
        if len(old) < 20 or len(new) < 20:
            return "Too few rows to compare. Need at least 20 rows on each side."

        for col in old.columns:
            if col not in new.columns:
                issues.append(f"'{col}' exists in the old data but not in the new data.")
                continue
            if pd.api.types.is_datetime64_any_dtype(old[col]):
                continue                                # date columns always "drift" over time, skip them
            old_is_num = pd.api.types.is_numeric_dtype(old[col])
            new_is_num = pd.api.types.is_numeric_dtype(new[col])

            if old_is_num != new_is_num:
                issues.append(f"'{col}' changed type (number <-> text).")

            elif old_is_num:                            # NUMBER column: KS test asks "same distribution?"
                a, b = old[col].dropna(), new[col].dropna()
                if len(a) < 20 or len(b) < 20 or (a.is_unique and a.is_monotonic_increasing):
                    continue                            # too few values, or just a row counter / ID
                stat, p = stats.ks_2samp(a, b)
                if p < 0.01 and stat >= 0.1:            # clearly different AND the gap is big enough to matter
                    issues.append(f"'{col}': mean {a.mean():.2f} -> {b.mean():.2f} (KS={stat:.2f}, p={p:.3g})")

            else:                                       # TEXT column: compare the share of each value
                if old[col].nunique() > 0.5 * len(old):
                    continue                            # almost all values unique = IDs / free text, skip
                share_old = old[col].value_counts(normalize=True)
                share_new = new[col].value_counts(normalize=True)
                new_values = [v for v in share_new.index if v not in share_old.index and share_new[v] >= 0.01]
                gone_values = [v for v in share_old.index if v not in share_new.index and share_old[v] >= 0.01]
                biggest_change = share_new.sub(share_old, fill_value=0).abs().max()
                if new_values or gone_values or biggest_change >= 0.10:
                    msg = f"'{col}': value shares changed by up to {100 * biggest_change:.0f} points"
                    if new_values:
                        msg += f"; new values {new_values[:3]}"
                    if gone_values:
                        msg += f"; values that disappeared {gone_values[:3]}"
                    issues.append(msg)

        for col in new.columns:
            if col not in old.columns:
                issues.append(f"'{col}' is a new column that the old data did not have.")

        if not issues:
            return f"No drift found: {label}."
        return f"Drift found, {label}:\n" + "\n".join("- " + i for i in issues)

    except Exception as e:
        return f"Data Quality Error: {type(e).__name__} : {str(e)}"













# Tool-5 Correlation and linear regression forecasting (uses scikit-learn)
def regression_tool(name: str, mode: str, target: str = None, features: str = None, predict: str = None) -> str:
    """Finds relationships between columns of a loaded dataset (name = its name in DATASET).
 
    mode='correlation': lists pairs of number columns that move together or opposite
        (Pearson r from -1 to +1; pairs with |r| >= 0.5 are shown). Correlation is not causation.
    mode='forecast': linear regression that predicts target (must be a number column).
        features = comma-separated column names to learn from. Empty = all useful columns.
        predict = optional new values, e.g. 'rooms=3, distance=5', to get one predicted target.
        Output: R2 on held-out rows (1.0 = perfect), typical error (RMSE, in target units),
        and the biggest effects (+1 in a number column changes the target by that amount).
 
    Cleaning is automatic: text like '$1,200' becomes a number, rows with a missing target
    are skipped, missing inputs are filled (median for numbers, 'missing' for text), text
    columns with at most 30 different values become yes/no columns, and ID columns, dates
    and free text are left out. The dataset itself is never changed.
    Returns a text report. Problems are returned as text starting with 'Error' or 'Regression Error'."""

    import re
    import numpy as np
    import pandas as pd
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import r2_score
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline, make_pipeline
    from sklearn.preprocessing import OneHotEncoder

    try:
        if name not in DATASET:
            return f"Dataset '{name}' not found. Loaded datasets are: {list(DATASET)}"
        df = DATASET[name]                      # we only read it, never change it
        mode = str(mode).lower().strip()

        # "$1,200" -> 1200 ; anything that is not a number becomes NaN (missing)
        def to_number(s):
            if pd.api.types.is_numeric_dtype(s):
                return s.astype(float)
            cleaned = s.astype(str).str.replace(r"[,$₹%\s]", "", regex=True)
            return pd.to_numeric(cleaned, errors="coerce")

        def looks_like_id(col):
            low = str(col).lower()
            if re.search(r"(^|[^a-z])id($|[^a-z])", low) or low.endswith("id"):
                return True                     # names like "id", "Customer_ID", "PassengerId"
            s = df[col].dropna()                # or a column of unique whole numbers (1, 2, 3, ...)
            if len(s) >= 20 and s.nunique() == len(s):
                nums = to_number(s)
                if nums.notna().all() and (nums == np.round(nums)).all():
                    return True
            return False

        # "number" = mostly numbers, "text" = few different values (categories), "other" = dates, names, ...
        def column_kind(col):
            s = df[col].dropna()
            if len(s) == 0:
                return "other"
            sample = s.sample(min(len(s), 50_000), random_state=0)   # big columns: check a sample
            if to_number(sample).notna().mean() >= 0.7:
                return "number"
            if s.nunique() <= 30:
                return "text"
            return "other"

        kinds = {col: column_kind(col) for col in df.columns}

        # ------------------------------------------------------------ CORRELATION
        if mode == "correlation":
            number_cols = [c for c in df.columns if kinds[c] == "number" and not looks_like_id(c)]
            if len(number_cols) < 2:
                return "Need at least 2 number columns (not ID columns) for correlation."
            table = pd.DataFrame({c: to_number(df[c]) for c in number_cols})
            table = table.replace([np.inf, -np.inf], np.nan)
            corr = table.corr()                 # +1 = move together, -1 = move opposite, 0 = no link
            pairs = []
            for i, a in enumerate(number_cols):
                for b in number_cols[i + 1:]:
                    r = corr.loc[a, b]
                    if pd.notna(r) and abs(r) >= 0.5:
                        pairs.append((abs(r), a, b, r))
            pairs.sort(key=lambda p: p[0], reverse=True)
            lines = [f"Correlation in '{name}' (number columns used: {', '.join(map(str, number_cols))}):"]
            if not pairs:
                lines.append("No pair of columns has a strong correlation (|r| >= 0.5).")
            for _, a, b, r in pairs[:15]:
                direction = "move together" if r > 0 else "move opposite"
                lines.append(f"- '{a}' and '{b}': r = {r:+.2f} ({direction})")
            lines.append("Correlation shows columns move together, not that one causes the other.")
            return "\n".join(lines)

        # ------------------------------------------------------------- FORECAST
        if mode == "forecast":
            if not target or target not in df.columns:
                return f"Give target = an existing column to predict. Columns are: {list(df.columns)}"
            if kinds[target] != "number":
                return f"'{target}' is not a number column, so linear regression cannot predict it."

            if features:
                feat = [f.strip() for f in str(features).split(",") if f.strip()]
                not_found = [f for f in feat if f not in df.columns]
                if not_found:
                    return f"Column(s) not found: {not_found}. Columns are: {list(df.columns)}"
                if target in feat:
                    return "The target cannot also be a feature."
                too_many = [f for f in feat if kinds[f] == "other"]
                if too_many:
                    return (f"Cannot use {too_many}: they are not numbers and have too many "
                            f"different values (dates or names).")
                auto_left_out = []
            else:
                feat = [c for c in df.columns if c != target and kinds[c] in ("number", "text")
                        and not looks_like_id(c)]
                auto_left_out = [c for c in df.columns if c != target and c not in feat]
            if not feat:
                return "No columns to learn from."

            y_all = to_number(df[target]).replace([np.inf, -np.inf], np.nan)
            keep = y_all.notna()                # rows with a missing target cannot teach anything
            y = y_all[keep].to_numpy(dtype=float)
            if len(y) < 30:
                return f"Only {len(y)} rows have a value for '{target}'. Need at least 30."

            num_feat = [c for c in feat if kinds[c] == "number"]
            cat_feat = [c for c in feat if kinds[c] == "text"]
            X = pd.DataFrame(index=df.index[keep])
            for c in num_feat:
                X[c] = to_number(df.loc[keep, c]).replace([np.inf, -np.inf], np.nan)
            for c in cat_feat:
                col = df.loc[keep, c]
                X[c] = col.astype(str).where(col.notna(), np.nan)   # keep missing as missing

            # fill missing values (median for numbers, "missing" for text), then learn
            # text categories become 0/1 columns (one-hot), then a straight-line fit
            steps = []
            if num_feat:
                steps.append(("num", SimpleImputer(strategy="median"), num_feat))
            if cat_feat:
                text_pipe = make_pipeline(SimpleImputer(strategy="constant", fill_value="missing"),
                                          OneHotEncoder(handle_unknown="ignore", drop="first"))
                steps.append(("cat", text_pipe, cat_feat))
            model = Pipeline([("prep", ColumnTransformer(steps)), ("reg", LinearRegression())])

            # test on rows the model did not learn from, so the score is honest
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=0)
            model.fit(X_train, y_train)
            pred = model.predict(X_test)
            r2 = r2_score(y_test, pred)                              # 1.0 = perfect, 0 = as good as guessing the average
            rmse = float(np.sqrt(np.mean((y_test - pred) ** 2)))     # typical size of an error, in target units

            names = [n.split("__", 1)[1] for n in model.named_steps["prep"].get_feature_names_out()]
            coefs = model.named_steps["reg"].coef_
            biggest = np.argsort(-np.abs(coefs))[:10]

            lines = [
                f"Linear regression: predicting '{target}' from {len(feat)} column(s)",
                f"Rows used: {len(y):,} (80% to learn, 20% to test); {int((~keep).sum()):,} rows skipped "
                f"because '{target}' was missing",
                f"R² on test rows = {r2:.3f} (1.0 = perfect, 0 = no better than guessing the average)",
                f"Typical error on test rows (RMSE) = {rmse:,.2f}",
            ]
            if pd.Series(y).nunique() == 2:
                lines.append(f"Warning: '{target}' has only 2 values (yes/no). Logistic regression fits this better.")
            lines.append("Biggest effects (other things equal, +1 changes the target by):")
            if cat_feat:
                lines.append("(Text categories are compared with a baseline: the first one alphabetically.)")
            for i in biggest:
                lines.append(f"- {names[i]}: {coefs[i]:+,.2f}")
            if auto_left_out:
                lines.append("Left out automatically (ID columns, dates or names): "
                             + ", ".join(map(str, auto_left_out[:10])))

            if predict:
                given = {}
                for item in str(predict).split(","):
                    if "=" in item:
                        k, v = item.split("=", 1)
                        given[k.strip()] = v.strip()
                row, unknown = {}, []
                for c in feat:
                    if c in given:
                        if kinds[c] == "number":
                            try:
                                row[c] = float(given[c])
                            except ValueError:
                                return f"'{c}' must be a number, but you gave '{given[c]}'."
                        else:
                            row[c] = given[c]
                    else:
                        row[c] = np.nan
                        unknown.append(c)
                new_row = pd.DataFrame([row], columns=feat)
                guess = float(model.predict(new_row)[0])
                lines.append(f"Predicted '{target}' = {guess:,.2f}")
                if unknown:
                    lines.append(f"Not given, so typical values were used for: {unknown}")
            return "\n".join(lines)

        return "Unknown mode. Use 'correlation' or 'forecast'."

    except Exception as e:
        return f"Regression Error: {str(e)}"



TOOLBOX = {
    "inspect_dataset" : inspect_data,
    "calculate" : calculate,
    "generate_chart" : visualize_data,
    "statistical_test" : statistical_test,
    "forecast" : regression_tool,
    "sql_query" : safe_sql_query,
    "data_quality" : data_quality_check
    
}
