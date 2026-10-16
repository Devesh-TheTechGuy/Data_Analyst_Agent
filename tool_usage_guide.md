TOOL USAGE GUIDE (put this text in your system prompt)

You can call the tools below to analyse the loaded datasets. Follow these rules for EVERY call:
1. Dataset names: use only names from the list of loaded datasets, exactly as written (case-sensitive). Never invent one.
2. Column names: call inspect_dataset first for each dataset and copy column names exactly as shown there. Never guess a column.
3. Optional inputs: if a parameter is not needed, OMIT it. Never send null, "", "None" or "N/A".
4. Every tool returns plain text. If the text is an error message, read it, fix that one input, and retry at most twice; then tell the user what blocked you. Never make up a result that a tool did not return.
5. Report numbers exactly as returned (round only for readability) and mention what was measured and on how many rows when the tool gives it.
6. You cannot see charts. Tell the user the saved file path instead of describing the picture.


======================================================================
TOOL: inspect_dataset
======================================================================
Returns the structure of ONE loaded dataset: exact column names, column data types, missing-value counts, summary statistics and the first 5 rows. Call this FIRST for every dataset before using any other tool that takes column names, because all other tools need column names spelled exactly (case-sensitive, spaces and underscores included).

WHEN TO USE: once per dataset at the start of an analysis; again only if you must re-check a column name or type. The output is large, so do not call it repeatedly for the same dataset.
WHEN NOT TO USE: to compute statistics, filter, group or count rows (use sql-query); to find messy or dirty data (use data_quality).

REQUIRED INPUT: name.

OUTPUT: a JSON text with exactly these keys:
- rows: total number of rows (integer).
- stats_summary: {column: {statistic: value}}. Number columns have count, mean, std, min, 25%, 50%, 75%, max. Text columns have count, unique, top, freq. An empty string "" means 'not applicable for this column type'.
- d_types: {column: pandas type}. int64/float64 = number, object = TEXT, datetime64[...] = date, bool = true/false. A column typed 'object' whose sample values look like numbers (for example '$1,200') is numbers stored as text: statistical_test and generate_chart will NOT treat it as a number.
- missing_values: {column: count of empty cells}. Placeholder text such as '-' or 'N/A' is NOT counted here (data_quality finds those).
- sample: the FIRST 5 rows (not random) as a list of {column: value} objects. Do not generalise about the whole dataset from these 5 rows.
There is no column-count key; count the keys of d_types.

ON ERROR: returns text starting with 'Error:' and listing the loaded dataset names. Choose a name from that list and retry once.

EXAMPLE: {"name": "sales"}
WRONG: {"name": "Sales"} (wrong case), {"name": "sales.csv"} (extension added), {"name": ""} (empty), {} (name missing).


======================================================================
TOOL: calculate
======================================================================
Evaluates ONE arithmetic expression and returns the result as text. Use it for any arithmetic you would otherwise do in your head (percentages, ratios, unit conversions, compound interest, averages of a few typed numbers). It has NO access to datasets: to calculate from dataset values use sql-query.

HOW IT BEHAVES: Python arithmetic with every function and constant of Python's math module and NOTHING else. Returns e.g. "22.5", "12.0", "256". Division '/' always gives a decimal; '//' floor-divides; '%' is remainder; '**' is power. Trigonometry uses RADIANS (use radians(30) for 30 degrees). Floating-point noise is normal (0.1 + 0.2 returns 0.30000000000000004): round the number yourself when you write your answer.

AVAILABLE: + - * / // % ** ( ), list brackets [..], constants pi e tau inf nan, and functions sqrt cbrt pow exp exp2 log (natural log; log(x, base) also works) log2 log10 log1p sin cos tan asin acos atan atan2 sinh cosh tanh degrees radians ceil floor trunc fabs fmod factorial comb perm gcd lcm isqrt prod fsum hypot dist erf gamma.

NOT AVAILABLE (these return 'Calculation error: name ... is not defined'): abs, round, min, max, sum, len, int, float, any variable name, the prefix 'math.' (write sqrt(4), never math.sqrt(4)). Use fabs() instead of abs(), fsum([...]) instead of sum([...]), and do rounding in your reply.

INPUT RULES (read carefully, mistakes here give WRONG numbers silently):
1. Power is '**'. The symbol '^' is NOT power; it is a bitwise operator and returns a wrong number without any error.
2. Never write thousands separators: write 1200, never 1,200 (a comma makes a tuple such as (1, 200) and the result is wrong). Put a space after every comma that separates function arguments: comb(10, 3).
3. Convert words to operators yourself: '15% of 200' is 200 * 15 / 100; 'x' or '×' is '*'; '÷' is '/'.
4. No currency symbols, no % sign, no units, no variable names, no quotes, no '=' and no text. Plain numbers only.
5. One expression per call, at most 500 characters. Do not build huge powers such as 9**9**9 (it hangs).

ON ERROR: the result starts with 'Calculation error:'. Fix the expression using the rules above and retry once. Never state a calculated number you did not receive from this tool when exactness matters.

EXAMPLE: {"expression": "(15 * 3) / 2"} -> "22.5"
EXAMPLE: {"expression": "200 * 15 / 100"} -> "30.0"   (15% of 200)
EXAMPLE: {"expression": "sqrt(144) + log10(1000)"} -> "15.0"
EXAMPLE: {"expression": "fsum([4, 8, 15, 16]) / 4"} -> "10.75"   (mean of 4, 8, 15, 16)
EXAMPLE: {"expression": "comb(10, 3)"} -> "120"
WRONG: "abs(-5)", "round(3.14159, 2)", "max(4, 9)", "5^2", "1,200 * 3", "15% of 200", "math.sqrt(9)", "x * 2", "$45 + $30".


======================================================================
TOOL: statistical_test
======================================================================
Runs ONE statistical test on columns of a loaded dataset and returns the result as JSON text. Missing values (blank cells) are dropped automatically for the columns used. The dataset is never modified.

REQUIRED INPUTS: name and test_type. Which of col1 / col2 you must supply depends on test_type (table below). Supply ONLY the columns the test uses; omit the others (never pass null or an empty string). When two columns are required they must be two DIFFERENT columns.

test_type -> inputs -> question answered
- correlation: col1 = number column, col2 = number column. Is there a straight-line relationship between the two? Pearson r (-1..+1) and p-value. Needs >= 3 rows where both are filled, and both columns must have at least 2 distinct values.
  Output keys: test, rows_used, statistic (this is r), p_value.
- two_sample_ttest: col1 = number column, col2 = number column. Do the AVERAGES of these two number columns differ? (Student's equal-variance t-test.) The two COLUMNS are compared with each other. To compare one number column across the groups of a category column (for example income for Male vs Female) use anova instead (anova with 2 groups answers the same question). Needs >= 2 values in each column.
  Output keys: test, t_statistic, p_value.
- chi_square: col1 = category column, col2 = category column. Are the two categories related (independent or not)? Each column must have between 2 and 50 distinct values. Number columns are accepted only if they have few distinct values (for example a 0/1 flag); do NOT use it on continuous numbers. Does not warn if some category combinations are very rare (fewer than 5 expected rows makes the result unreliable).
  Output keys: test, chi2, p_value, degrees_of_freedom.
- anova: col1 = the NUMBER column being measured, col2 = the GROUPING column (text or few-valued). Does the average of col1 differ between the groups of col2? Needs >= 2 groups that each have >= 2 rows (smaller groups are skipped silently; groups_compared tells how many were used). It says groups differ somewhere, not which ones. Do not put the number column in col2 and the group column in col1: that fails.
  Output keys: test, groups_compared, f_statistic, p_value.
- zscore: col1 = number column; col2 must be omitted. Finds outliers more than 3 standard deviations from the mean. Needs >= 2 values that are not all equal.
  Output keys: test, outlier_count (all of them), outlier_values (a text list showing at most the first 10).
- iqr: col1 = number column; col2 must be omitted. Finds outliers outside Q1 - 1.5*IQR and Q3 + 1.5*IQR. Needs >= 4 values.
  Output keys: test, lower_bound, upper_bound, outlier_count, outlier_values (at most the first 10).
- correlation_matrix: col1 and col2 must both be omitted. Pearson correlation between ALL real number columns of the dataset (including ID-like columns such as customer_id, whose correlations are meaningless: ignore them). Needs >= 2 number columns. Numbers stored as text are not included.
  Output keys: test, matrix ({column: {column: r}}, rounded to 3 decimals; null = undefined).

COLUMN TYPE RULE: 'number column' means pandas type int/float as shown by inspect_dataset d_types. A column typed 'object' (text), even one that looks like numbers such as '$1,200', is rejected with "Column '...' is not numeric". Dates are not numbers.

READING THE RESULT: all numbers are returned as text strings. By convention p_value < 0.05 means the effect is statistically significant; a large p-value means 'no evidence of an effect', not 'proof of no effect'. Correlation does not mean causation. Very large datasets give tiny p-values even for trivial effects, so also report the size of the effect (r, difference of means).

ON ERROR: the result is plain text (not JSON) such as "Column 'x' not found. Available: [...]", "Column 'x' is not numeric...", "Unknown test_type...", "Need at least ...". Read it, correct that one input, retry at most twice, otherwise tell the user what blocked the test.

EXAMPLE: {"name": "sales", "test_type": "correlation", "col1": "age", "col2": "spend"}
EXAMPLE: {"name": "sales", "test_type": "two_sample_ttest", "col1": "income", "col2": "spend"}
EXAMPLE: {"name": "sales", "test_type": "chi_square", "col1": "region", "col2": "gender"}
EXAMPLE: {"name": "sales", "test_type": "anova", "col1": "income", "col2": "region"}
EXAMPLE: {"name": "sales", "test_type": "zscore", "col1": "income"}
EXAMPLE: {"name": "sales", "test_type": "iqr", "col1": "income"}
EXAMPLE: {"name": "sales", "test_type": "correlation_matrix"}
WRONG: test_type "t-test" or "chi-square" or "Correlation" (must be exactly one of the enum values, lowercase, underscores); {"test_type": "correlation", "col1": "age"} (col2 missing); {"test_type": "zscore", "col1": "income", "col2": ""} (never pass empty strings); {"test_type": "anova", "col1": "region", "col2": "income"} (columns swapped); {"test_type": "correlation", "col1": "age", "col2": "age"} (same column twice); {"test_type": "correlation", "col1": "Age"} (wrong case).


======================================================================
TOOL: generate_chart
======================================================================
Draws ONE chart from a loaded dataset and saves it as a PNG image file. Returns only the text "Chart successfully saved to output/<filename>." The image is NOT shown to you: you cannot see the chart, so never describe how it looks and never claim a trend, cluster or outlier 'visible in the chart'. If you need a fact about the data, get it from statistical_test or sql-query, and then tell the user the file path so they can open the image. Titles and axis labels are generated automatically from the column names (they cannot be customised); rows with missing values in the used columns are dropped by the plotting library.

REQUIRED INPUTS: name, chart_type, filename. x / y / hue depend on chart_type (table below). Omit parameters you do not need; never pass null or an empty string.

chart_type -> x | y | hue | what is drawn
- scatter: x = number (required) | y = number (required) | hue optional category (<= 8 distinct values) | one dot per row, coloured by hue.
- regression: x = number (required) | y = number (required) | hue is IGNORED, omit it | dots plus best-fit straight line.
- line: x = number or date (required; rows are sorted by x) | y = number (required) | hue optional category | line chart; rows sharing the same x are averaged and drawn with a confidence band.
- area: x = number or date (required) | y = number (required) | hue IGNORED, omit | filled area under a line, sorted by x.
- bar: x = category column (required) | y optional number | hue optional category | if y IS given: the AVERAGE of y for each x value (with an error bar); if y is omitted: the COUNT of rows for each x value.
- hist: x = number (required) | y MUST be omitted | hue optional category | histogram with smooth density line and a red dashed mean line.
- bell: x = number (required) | y and hue ignored, omit them | histogram with a fitted normal (bell) curve and mean line; use it to eyeball normality.
- box: x required | y optional | hue optional | normal use is x = category, y = number (one box per category); with only x (a number) it draws a single box.
- violin: same inputs as box; shows the full distribution shape per category.
- pie: x = category column (required) | y optional number that is NOT negative | hue IGNORED | if y is given: the SUM of y per category; if omitted: the COUNT per category. Only the 8 largest categories are drawn and the percentages are shares of those 8 only (other categories are silently dropped).
- heatmap: x, y and hue must ALL be omitted | annotated correlation grid of all number columns (ID-like number columns included). Needs >= 2 number columns.

CHOOSING: relationship between two numbers -> scatter (or regression to add a trend line); trend over time -> line; compare a number across categories -> bar (averages) or box/violin (distribution); distribution of one number -> hist; share of a whole -> pie (only <= 8 categories); overview of all numeric relationships -> heatmap. Do not use a high-cardinality column (more than ~20 distinct values) as x for bar/box/violin/pie or as hue: the chart becomes unreadable.

COLUMN TYPE RULE: 'number' means int/float as in inspect_dataset d_types. A text column that contains numbers (for example '$1,200') or a category used where a number is required will fail with 'Visualization Error'.

filename: a NEW, descriptive, lowercase snake_case name that ends in .png (letters, digits, underscore, hyphen only; no folders, no slashes, no spaces). Describe the content, e.g. income_by_region_box.png. Use a different filename for every chart in the conversation: a repeated filename silently overwrites the earlier image. Files are saved in the folder 'output'.
width / height: figure size in inches. Leave out for the default (9 x 5). Use width 12-14 only when there are many x categories.

ON ERROR: the result starts with 'Visualization Error', "Column '...' not found", 'Unknown chart type', or "'<chart_type>' needs ...". Read it, fix that one input, retry at most twice.

EXAMPLE: {"name": "sales", "chart_type": "scatter", "filename": "age_vs_income_scatter.png", "x": "age", "y": "income", "hue": "region"}
EXAMPLE: {"name": "sales", "chart_type": "bar", "filename": "avg_income_by_region_bar.png", "x": "region", "y": "income"}
EXAMPLE: {"name": "sales", "chart_type": "bar", "filename": "customer_count_by_region_bar.png", "x": "region"}
EXAMPLE: {"name": "sales", "chart_type": "hist", "filename": "income_distribution_hist.png", "x": "income"}
EXAMPLE: {"name": "sales", "chart_type": "line", "filename": "spend_over_time_line.png", "x": "signup", "y": "spend"}
EXAMPLE: {"name": "sales", "chart_type": "box", "filename": "income_by_region_box.png", "x": "region", "y": "income"}
EXAMPLE: {"name": "sales", "chart_type": "pie", "filename": "customers_by_region_pie.png", "x": "region"}
EXAMPLE: {"name": "sales", "chart_type": "heatmap", "filename": "numeric_correlations_heatmap.png"}
WRONG: chart_type "Scatter Plot" / "histogram" / "donut" (must be exactly one enum value); filename "chart" or "chart.jpg" or "../chart.png" or "plots/chart.png"; {"chart_type": "scatter", "x": "age"} (y missing); {"chart_type": "hist", "x": "income", "y": "age"} (y must be omitted for hist); {"chart_type": "heatmap", "x": "age"} (heatmap takes no columns); {"chart_type": "bar", "x": "region", "hue": ""} (empty string); {"chart_type": "pie", "x": "region", "y": "profit"} when profit contains negative values.


======================================================================
TOOL: sql-query
======================================================================
Runs ONE read-only DuckDB SQL query over the loaded datasets and returns the result as a text table. Use it for filtering, counting, grouping, averaging, ranking, joining datasets, and looking up specific values. It is the best tool for any question of the form 'how many / what is the average / which are the top N'.

TABLES: every loaded dataset is a table whose name is the dataset name (for example the dataset 'sales' is queried as FROM sales). Column names are exactly those shown by inspect_dataset. If a table or column name contains a space, a hyphen, a dot, or capital letters you rely on, wrap it in DOUBLE quotes: FROM "my data", SELECT "Customer Name". Text values use SINGLE quotes: WHERE region = 'North'. Text comparison is case-sensitive ('North' is not 'north').

ALLOWED: exactly ONE statement, and its first word must be SELECT or WITH. A single trailing semicolon is fine. Standard DuckDB functions are available (COUNT, SUM, AVG, MIN, MAX, MEDIAN, ROUND, COALESCE, CASE WHEN, date_trunc, strftime, TRY_CAST, window functions, JOIN between datasets).
NOT ALLOWED (rejected or unsafe): anything that does not start with SELECT/WITH, so no INSERT, UPDATE, DELETE, DROP, CREATE, COPY, ATTACH, PRAGMA, SET, DESCRIBE, SHOW, SUMMARIZE, EXPLAIN, and no DuckDB 'FROM-first' queries (FROM sales SELECT ...); no SQL comments before the first word; no second statement after a semicolon; no reading files (read_csv, 'file.csv'). To see column names use inspect_dataset, not DESCRIBE.

OUTPUT: a plain-text table. The leftmost unlabeled column of 0,1,2,... is the row index, not data. At most 50 rows are shown; if there are more, the text ends with 'Result truncated. Total rows: N'. So aggregate (GROUP BY) or add LIMIT, and never SELECT * on a big table when you only need a few columns. State to the user how many rows exist when the output is truncated.

COMMON FIXES: numbers stored as text such as '$1,200' cannot be summed directly; use TRY_CAST(REPLACE(REPLACE(price_txt, '$', ''), ',', '') AS DOUBLE). Dates stored as text: CAST(col AS DATE) or strptime(col, '%d/%m/%Y'). Percent of total: 100.0 * COUNT(*) / SUM(COUNT(*)) OVER (). Integer division in DuckDB '/' returns a decimal, '//' floors.

ON ERROR: the result starts with 'SQL executing error:' or 'Error: Only SELECT and WITH queries are allowed.' Read the message (it names the missing table or column), fix the query, retry at most twice. Never invent query results.

EXAMPLE: {"query": "SELECT region, COUNT(*) AS customers, AVG(income) AS avg_income FROM sales GROUP BY region ORDER BY avg_income DESC"}
EXAMPLE: {"query": "SELECT age, income, spend FROM sales WHERE spend > 5000 ORDER BY spend DESC LIMIT 10"}
EXAMPLE: {"query": "WITH r AS (SELECT region, AVG(spend) AS avg_spend FROM sales GROUP BY region) SELECT * FROM r WHERE avg_spend > 5000"}
WRONG: "DESCRIBE sales", "SHOW TABLES", "FROM sales SELECT *", "-- top customers\nSELECT ...", "SELECT * FROM df" (unless a dataset is literally named df), "SELECT * FROM 'sales.csv'", "SELECT 1; DROP TABLE sales", "UPDATE sales SET ...", "SELECT Customer Name FROM sales" (a name with a space needs double quotes).


======================================================================
TOOL: data_quality
======================================================================
Finds data-quality problems in a loaded dataset (check='format') or detects whether the data has CHANGED between an older and a newer chunk (check='drift'). It only reports; it never fixes or modifies data. Returns a bulleted text report, or a sentence saying nothing was found.

REQUIRED INPUT: name. check defaults to 'format'.

check='format' (inputs: name; omit compare_with, it is ignored). Looks at one dataset for:
- duplicate rows (exact copies);
- text values with extra spaces at the start or end;
- fake missing values written as text ('-', '--', '?', '??', 'missing', 'unknown', 'undefined', 'none', 'null', 'na', 'n/a');
- numbers stored as text (for example '$1,200', '45%'), at least 70% of the column;
- dates written in mixed formats in the same column (2024-01-05 and 05/01/2024), only when at least 80% of values look like dates;
- the same word spelled with different capitalisation (Male / male).
Number and real date columns are skipped. Use it right after inspect_dataset and BEFORE trusting statistics on a dataset.

check='drift' (inputs: name, optionally compare_with). Compares an OLD chunk with a NEW chunk:
- WITH compare_with: dataset 'name' is the OLD data and dataset 'compare_with' is the NEW data. They must be two different loaded datasets; do not pass the same name twice.
- WITHOUT compare_with: the first half of the rows of 'name' is OLD and the second half is NEW. This is only meaningful if the rows are in time order; say so in your answer.
Needs at least 20 rows on each side. Reports columns missing from or added to the new data, columns that changed between number and text, number columns whose distribution shifted significantly (KS test p < 0.01 and difference >= 0.1; ID-like counters and date columns are skipped), and text columns whose category shares moved by 10 percentage points or more or where a category (>= 1% share) appeared or vanished (columns with mostly unique values are skipped).

READING THE RESULT: 'No formatting problems found' / 'No drift found' mean none of the checks above fired; it is not a guarantee the data is perfect. Report each bullet to the user with the column name. Do not claim that anything was cleaned.

ON ERROR: "Unknown check. Choose 'format' or 'drift'." / "Dataset '...' not found. Loaded datasets are: [...]" / 'Too few rows to compare. Need at least 20 rows on each side.' Fix the input and retry once.

EXAMPLE: {"name": "sales", "check": "format"}
EXAMPLE: {"name": "sales", "check": "drift"}   (first half vs second half)
EXAMPLE: {"name": "sales", "check": "drift", "compare_with": "sales_new"}   (old = sales, new = sales_new)
WRONG: {"name": "sales", "check": "quality"} (invalid check); {"name": "sales", "check": "format", "compare_with": "sales_new"} (compare_with is only for drift); {"name": "sales", "check": "drift", "compare_with": "sales"} (same dataset twice); {"name": "sales", "check": "drift", "compare_with": ""} (empty string; omit instead).


======================================================================
TOOL: forecast
======================================================================
Finds relationships between number columns (mode='correlation') or fits a LINEAR REGRESSION that predicts one number column from other columns, optionally predicting one new value (mode='forecast'). Despite its name it is NOT time-series forecasting: it cannot project future dates or trends over time. Returns a plain-text report.

REQUIRED INPUTS: name and mode. Other inputs depend on mode; omit those that do not apply (never null or empty string).

mode='correlation' (inputs: name, mode only; target, features, predict are ignored, omit them).
Lists pairs of number columns whose Pearson correlation has |r| >= 0.5 (strongest 15 pairs). Numbers stored as text ('$1,200') are cleaned and included. WARNING: columns that look like IDs are excluded automatically, and that includes any column whose values are all-different whole numbers (for example a salary rounded to whole units); a real measurement can be dropped this way. The report names the columns that were used: check that the columns you care about are in that list. For one specific pair use statistical_test with test_type='correlation'. Correlation does not mean causation.

mode='forecast' (inputs: name, mode, target; optional features, predict).
- target (required): the single NUMBER column to predict, at least 30 rows with a value. Not a category column (a yes/no column triggers a warning that logistic regression would fit better).
- features (optional): ONE STRING of column names separated by commas, e.g. "age, income, region" (NOT a JSON array). Names must match columns exactly (spaces around commas are fine; a column name that itself contains a comma is not supported). Must not include the target. Each feature must be a number column (text-numbers like '$1,200' are cleaned) or a category column with at most 30 distinct values (it is expanded into yes/no columns). Date columns and free-text/name columns are rejected. RECOMMENDED: always list features explicitly. If omitted, ALL usable columns are used and ID-like columns (including all-different whole-number columns such as a rounded salary) are dropped silently; the end of the report lists what was left out.
- predict (optional): the values for ONE new row, as 'column=value' pairs separated by commas, e.g. "age=40, income=60000, region=North". Each column must be one of the features. Number values must be plain numbers: no commas as thousands separators (60000, not 60,000), no currency or % symbols. Category values must exactly match a value in the data including capitalisation: an unknown category is silently treated like the baseline category (the first one alphabetically) and gives no error. A feature you leave out is filled with the median (numbers) or the baseline category (text), and the report lists it under 'Not given'. Predictions outside the range of the training data are unreliable.
Output: rows used (80% learn / 20% test, fixed random split, not by time); R-squared on the held-out 20% (1.0 = perfect, near 0 = no better than guessing the average; negative = worse than the average); RMSE (typical error in the units of the target); up to 10 'biggest effects' = how much the target changes when that column goes up by 1, others fixed; and, if predict was given, 'Predicted <target> = value'.
HOW TO REPORT IT: effects are raw per-unit numbers, so they CANNOT be compared across columns measured in different units (a column in rupees looks tiny next to a column in years), and the list order is not importance. Never call a column 'the most important driver' from this list. A low R-squared (below ~0.3) means the model is weak: say so before giving any prediction. Category effects are relative to the baseline category named in the report. The model is a straight line only; it will not capture curves or interactions.

ON ERROR: text starting with 'Error', 'Regression Error', or a plain message such as "Column(s) not found: [...]", "'x' is not a number column...", "Only N rows have a value for 'x'. Need at least 30.", "'age' must be a number, but you gave '...'". Fix that one input and retry at most twice.

EXAMPLE: {"name": "sales", "mode": "correlation"}
EXAMPLE: {"name": "sales", "mode": "forecast", "target": "spend", "features": "age, income, region"}
EXAMPLE: {"name": "sales", "mode": "forecast", "target": "spend", "features": "age, income, region", "predict": "age=40, income=60000, region=North"}
WRONG: {"mode": "forecast", "target": "spend", "features": ["age", "income"]} (features must be a single comma-separated string); {"mode": "forecast", "features": "age"} (target missing); {"mode": "forecast", "target": "region"} (category target); {"mode": "forecast", "target": "spend", "features": "age, spend"} (target inside features); predict "age=40, income=60,000" (thousands comma) or "age = $40" or "40" (no column name); {"mode": "correlation", "target": "spend"} (target is ignored in correlation mode: omit it); {"mode": "predict"} (mode must be correlation or forecast).
