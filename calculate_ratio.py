import pandas as pd

# Load your data
salary = pd.read_csv("salary.csv")
hours = pd.read_csv("work_hours.csv")
rates = pd.read_csv("project_rates.csv")

# Merge work hours with rates
merged = hours.merge(rates, on="project")
merged["earned"] = merged["hours"] * merged["hourly_rate"]

# Sum earnings per employee per month
earned_monthly = (
    merged.groupby(["employee_id"])
    .agg({"earned": "sum"})
    .reset_index()
)

# Merge with salary
result = salary.merge(earned_monthly, on="employee_id", how="left")
result["ratio"] = (result["earned"] / result["salary"]) * 100

result.to_csv("performance.csv", index=False)
print(result)
