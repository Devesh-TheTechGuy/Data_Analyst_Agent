tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "inspect_dataset",
            "description": "Returns the structure of ONE loaded dataset as JSON text: exact column names, pandas data types, missing-value counts, summary statistics and the first 5 rows. Call it FIRST for every dataset, before any tool that takes column names. Required: name (exact loaded dataset name, case-sensitive). Do not call it repeatedly for the same dataset. Not for computing statistics (use sql-query). Example: {\"name\": \"sales\"}. Full rules: see the TOOL USAGE GUIDE in the system prompt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "Exact name of a loaded dataset, copied character-for-character from the list of loaded datasets you were given (or from any 'Loaded datasets are: [...]' error message). Case-sensitive. Do not guess, translate, add a file extension, or change spaces/underscores. Example: \"sales\".",
                        "examples": ["sales"],
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluates ONE arithmetic expression with Python math-module functions (sqrt, log10, fsum, comb, ...) and returns the result as text. No dataset access. Use ** for power (never ^); no thousands separators (1200, not 1,200); a space after commas between arguments; no abs/round/min/max/sum (use fabs/fsum); no 'math.' prefix, variables, % or currency symbols (15% of 200 is 200 * 15 / 100). Example: {\"expression\": \"sqrt(144) + log10(1000)\"}. Full rules: see the TOOL USAGE GUIDE in the system prompt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                        "pattern": "^(?!.*,\\S)[0-9A-Za-z+\\-*/%().,\\s\\[\\]]+$",
                        "description": "One arithmetic expression using only numbers, + - * / // % **, parentheses, list brackets and math-module function names (sqrt, log10, fsum, comb, ...). Use ** for power (never ^), no thousands separators (1200 not 1,200), a space after every comma between function arguments, no 'math.' prefix, no abs/round/min/max/sum, no variables, no quotes, no text, no currency or % symbols. Example: \"(15 * 3) / 2\".",
                        "examples": ["(15 * 3) / 2", "200 * 15 / 100", "sqrt(144) + log10(1000)"],
                    },
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "statistical_test",
            "description": "Runs ONE statistical test and returns JSON text. test_type is exactly one of: correlation, two_sample_ttest, chi_square, anova, zscore, iqr, correlation_matrix. correlation and two_sample_ttest need col1+col2 (both numeric); chi_square needs col1+col2 (both categories); anova needs col1 (numeric measure) + col2 (grouping column); zscore and iqr need col1 (numeric) only; correlation_matrix needs no columns. Omit unused columns (never null or empty string); col1 and col2 must differ. Text columns that merely look like numbers are rejected. Example: {\"name\": \"sales\", \"test_type\": \"anova\", \"col1\": \"income\", \"col2\": \"region\"}. Full rules: see the TOOL USAGE GUIDE in the system prompt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "Exact name of a loaded dataset, copied character-for-character from the list of loaded datasets you were given (or from any 'Loaded datasets are: [...]' error message). Case-sensitive. Do not guess, translate, add a file extension, or change spaces/underscores. Example: \"sales\".",
                        "examples": ["sales"],
                    },
                    "test_type": {
                        "type": "string",
                        "enum": ["correlation", "two_sample_ttest", "chi_square", "anova", "zscore", "iqr", "correlation_matrix"],
                        "description": "Which test to run. Exactly one of: correlation | two_sample_ttest | chi_square | anova | zscore | iqr | correlation_matrix (lowercase, underscores, no hyphens). Required columns: correlation = col1+col2 (both numbers); two_sample_ttest = col1+col2 (both numbers); chi_square = col1+col2 (both categories); anova = col1 (number) + col2 (grouping column); zscore = col1 (number) only; iqr = col1 (number) only; correlation_matrix = no columns.",
                        "examples": ["correlation"],
                    },
                    "col1": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "First column, exact name from inspect_dataset (case-sensitive). Required for every test_type EXCEPT correlation_matrix. For anova it is the NUMBER column being measured. For zscore and iqr it is the only column. Omit for correlation_matrix. Never null or empty string.",
                        "examples": ["age"],
                    },
                    "col2": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "Second, DIFFERENT column, exact name. Required ONLY for correlation, two_sample_ttest, chi_square (category) and anova (the grouping column). OMIT for zscore, iqr and correlation_matrix. Never null or empty string.",
                        "examples": ["spend"],
                    },
                },
                "required": ["name", "test_type"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_chart",
            "description": "Saves ONE chart as a PNG and returns only the file path; you cannot see the image, so never describe how it looks. Needs x AND y: scatter, line, area, regression. Needs x, y optional: bar (average of y per x, else row count), box, violin, pie. Needs x only (omit y): hist, bell. Needs no columns: heatmap. filename: a new lowercase snake_case name ending in .png, no folders (income_by_region_box.png). Omit unused params; never null or empty string. Example: {\"name\": \"sales\", \"chart_type\": \"scatter\", \"filename\": \"age_vs_income_scatter.png\", \"x\": \"age\", \"y\": \"income\", \"hue\": \"region\"}. Full rules: see the TOOL USAGE GUIDE in the system prompt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "Exact name of a loaded dataset, copied character-for-character from the list of loaded datasets you were given (or from any 'Loaded datasets are: [...]' error message). Case-sensitive. Do not guess, translate, add a file extension, or change spaces/underscores. Example: \"sales\".",
                        "examples": ["sales"],
                    },
                    "chart_type": {
                        "type": "string",
                        "enum": ["scatter", "line", "bar", "hist", "bell", "box", "violin", "pie", "area", "heatmap", "regression"],
                        "description": "Chart to draw. Exactly one of: scatter | line | bar | hist | bell | box | violin | pie | area | heatmap | regression (lowercase). Needs x AND y: scatter, line, area, regression. Needs x only: hist, bell, pie (y optional), bar (y optional), box and violin (y optional). Needs no columns: heatmap.",
                        "examples": ["scatter"],
                    },
                    "filename": {
                        "type": "string",
                        "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,79}\\.png$",
                        "minLength": 5,
                        "maxLength": 84,
                        "description": "Output file name: descriptive lowercase snake_case that ends with .png; letters, digits, underscore, hyphen only; no folders, slashes, spaces or dots other than the final .png. Must be different for every chart (an existing name is overwritten). Example: \"income_by_region_box.png\".",
                        "examples": ["age_vs_income_scatter.png"],
                    },
                    "x": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "Column for the x-axis / the category or number being summarised. Exact name from inspect_dataset. Required for every chart_type except heatmap (omit for heatmap). Never null or empty string.",
                        "examples": ["age"],
                    },
                    "y": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "Column for the y-axis. REQUIRED (a number column) for scatter, line, area, regression. OPTIONAL for bar, box, violin, pie (see the chart_type table). OMIT for hist, bell, heatmap. Never null or empty string.",
                        "examples": ["income"],
                    },
                    "hue": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "Optional category column that colours groups (at most ~8 distinct values). Only used by scatter, line, bar, hist, box, violin. OMIT for regression, area, bell, pie, heatmap (ignored there). Never null or empty string.",
                        "examples": ["region"],
                    },
                    "width": {
                        "type": "number",
                        "minimum": 4,
                        "maximum": 20,
                        "default": 9,
                        "description": "Figure width in inches, 4 to 20. Omit to use the default 9.",
                    },
                    "height": {
                        "type": "number",
                        "minimum": 3,
                        "maximum": 15,
                        "default": 5,
                        "description": "Figure height in inches, 3 to 15. Omit to use the default 5.",
                    },
                },
                "required": ["name", "chart_type", "filename"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sql_query",
            "description": "Runs ONE read-only DuckDB query over the loaded datasets and returns a text table (at most 50 rows shown). Each dataset is a table named after the dataset. The statement must start with SELECT or WITH: no DESCRIBE, SHOW, FROM-first syntax, comments before the first word, or second statement. Double-quote names containing spaces; single-quote text values; use GROUP BY or LIMIT. Example: {\"query\": \"SELECT region, COUNT(*) AS n FROM sales GROUP BY region\"}. Full rules: see the TOOL USAGE GUIDE in the system prompt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "minLength": 6,
                        "maxLength": 4000,
                        "pattern": "^\\s*([Ss][Ee][Ll][Ee][Cc][Tt]|[Ww][Ii][Tt][Hh])\\b",
                        "description": "One DuckDB SQL statement whose first word is SELECT or WITH (no comments before it, no second statement). Query loaded datasets by their dataset name as the table name; double-quote names with spaces/capitals; single-quote text values; use GROUP BY or LIMIT so the result stays under 50 rows. Example: \"SELECT region, COUNT(*) AS customers FROM sales GROUP BY region\".",
                        "examples": ["SELECT region, COUNT(*) AS customers FROM sales GROUP BY region ORDER BY customers DESC"],
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "data_quality",
            "description": "Reports data-quality problems; never modifies data. check='format' (default): duplicates, extra spaces, fake missing values like '-', numbers stored as text, mixed date formats, inconsistent capitalisation. check='drift': detects change between old and new data: compare_with = a DIFFERENT dataset holding the new data (name = old data), or omit it to compare the first half of the rows with the second half. Never pass compare_with with check='format'. Example: {\"name\": \"sales\", \"check\": \"drift\", \"compare_with\": \"sales_new\"}. Full rules: see the TOOL USAGE GUIDE in the system prompt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "Exact name of a loaded dataset, copied character-for-character from the list of loaded datasets you were given (or from any 'Loaded datasets are: [...]' error message). Case-sensitive. Do not guess, translate, add a file extension, or change spaces/underscores. Example: \"sales\". For check='drift' with compare_with, this is the OLD dataset.",
                        "examples": ["sales"],
                    },
                    "check": {
                        "type": "string",
                        "enum": ["format", "drift"],
                        "default": "format",
                        "description": "'format' = find formatting problems in this one dataset (duplicates, extra spaces, fake missing values, numbers stored as text, mixed date formats, inconsistent spelling/capitalisation). 'drift' = detect whether the data changed between an old and a new chunk. Omit to use 'format'.",
                        "examples": ["format"],
                    },
                    "compare_with": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "ONLY for check='drift': name of a DIFFERENT loaded dataset that is the NEW data (name = old data). Copy it exactly from the loaded datasets list. Omit it to compare the first half of the rows of 'name' with the second half (rows must be in time order). Omit it for check='format' (it is ignored there). Never null or empty string.",
                        "examples": ["sales_new"],
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forecast",
            "description": "Correlation or LINEAR regression; NOT time-series forecasting. mode='correlation' lists strongly related numeric column pairs (give only name and mode). mode='forecast' predicts the numeric column target from features (ONE comma-separated string such as \"age, income, region\"; always list them) and optionally predict = one new row as \"age=40, income=60000, region=North\" (plain numbers, no thousands commas). Reports R-squared on held-out rows; say so when it is low. Example: {\"name\": \"sales\", \"mode\": \"forecast\", \"target\": \"spend\", \"features\": \"age, income, region\", \"predict\": \"age=40, income=60000, region=North\"}. Full rules: see the TOOL USAGE GUIDE in the system prompt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "Exact name of a loaded dataset, copied character-for-character from the list of loaded datasets you were given (or from any 'Loaded datasets are: [...]' error message). Case-sensitive. Do not guess, translate, add a file extension, or change spaces/underscores. Example: \"sales\".",
                        "examples": ["sales"],
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["correlation", "forecast"],
                        "description": "'correlation' = list strongly related number-column pairs (|r| >= 0.5); needs only name and mode. 'forecast' = linear regression predicting the number column 'target' from other columns, optionally predicting one new row; needs target.",
                        "examples": ["forecast"],
                    },
                    "target": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "description": "REQUIRED when mode='forecast'; OMIT when mode='correlation'. The single NUMBER column to predict (at least 30 rows with a value). Exact name. Never null or empty string.",
                        "examples": ["spend"],
                    },
                    "features": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1000,
                        "description": "OPTIONAL, mode='forecast' only. ONE STRING (not an array) of exact column names separated by commas, e.g. \"age, income, region\". Must not contain the target. Number columns or category columns with <= 30 distinct values only (no dates, no names/free text). Strongly recommended: always list them; if omitted, all usable columns are used and columns that look like IDs (including all-different whole numbers) are dropped silently.",
                        "examples": ["age, income, region"],
                    },
                    "predict": {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 1000,
                        "pattern": "^\\s*[^=,]+=[^=,]+(\\s*,\\s*[^=,]+=[^=,]+)*\\s*$",
                        "description": "OPTIONAL, mode='forecast' only. Values for ONE new row as comma-separated column=value pairs, e.g. \"age=40, income=60000, region=North\". Each column must be one of the features. Numbers: plain digits only (60000, not 60,000 or Rs60000 or 60%). Categories: exact text from the data, same capitalisation. No commas or equals signs inside a value.",
                        "examples": ["age=40, income=60000, region=North"],
                    },
                },
                "required": ["name", "mode"],
                "additionalProperties": False,
            },
        },
    },
]