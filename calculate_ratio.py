import pandas as pd
import requests
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import os
from pathlib import Path

# Try to load .env file if it exists
env_file = Path('.env')
if env_file.exists():
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip().strip('"').strip("'")

# Clockify API Configuration
CLOCKIFY_API_KEY = os.getenv("CLOCKIFY_API_KEY")
WORKSPACE_ID = os.getenv("CLOCKIFY_WORKSPACE_ID")
BASE_URL = "https://api.clockify.me/api/v1"

def get_last_three_months():
    """Get start and end dates for the last 3 complete months"""
    today = datetime.now()
    
    # Get first day of current month
    current_month_start = today.replace(day=1)
    
    # Go back 3 months to get the start date
    start_date = current_month_start - relativedelta(months=3)
    
    # End date is last day of previous month
    end_date = current_month_start - timedelta(days=1)
    
    return start_date, end_date

def get_headers():
    """Return API headers"""
    return {
        "X-Api-Key": CLOCKIFY_API_KEY,
        "Content-Type": "application/json"
    }

def fetch_user_groups():
    """Fetch all user groups from workspace"""
    url = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/user-groups"
    response = requests.get(url, headers=get_headers())
    
    if response.status_code != 200:
        print(f"Error fetching user groups: {response.status_code}")
        return []
    
    return response.json()

def fetch_users():
    """Fetch only users in the 'full-time' group"""
    # Get all user groups
    groups = fetch_user_groups()
    
    # Find the 'full-time' group (case-insensitive)
    full_time_group = None
    for group in groups:
        if group['name'].lower() == 'full-time':
            full_time_group = group
            break
    
    if not full_time_group:
        print("⚠️  Warning: 'full-time' group not found. Fetching all users instead.")
        print("   Available groups:", [g['name'] for g in groups])
        # Fallback to all users
        url = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/users"
        response = requests.get(url, headers=get_headers())
        return response.json() if response.status_code == 200 else []
    
    # Get user IDs from the full-time group
    full_time_user_ids = set(full_time_group.get('userIds', []))
    
    # Fetch all users
    url = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/users"
    response = requests.get(url, headers=get_headers())
    
    if response.status_code != 200:
        print(f"Error fetching users: {response.status_code}")
        return []
    
    all_users = response.json()
    
    # Filter only full-time users
    full_time_users = [user for user in all_users if user['id'] in full_time_user_ids]
    
    return full_time_users

def fetch_time_entries(user_id, start_date, end_date):
    """Fetch time entries for a specific user"""
    url = f"{BASE_URL}/workspaces/{WORKSPACE_ID}/user/{user_id}/time-entries"
    params = {
        'start': start_date.strftime('%Y-%m-%dT00:00:00Z'),
        'end': end_date.strftime('%Y-%m-%dT23:59:59Z'),
        'page-size': 5000
    }
    
    response = requests.get(url, headers=get_headers(), params=params)
    
    if response.status_code == 200:
        return response.json()
    return []

def load_project_rates():
    """Load project rates from CSV file"""
    csv_file = "project_rates.csv"
    
    if not Path(csv_file).exists():
        print(f"❌ Error: {csv_file} not found!")
        print(f"   Run 'python update_project_rates.py' first to create it")
        return {}
    
    df = pd.read_csv(csv_file)
    
    # Create dictionary: project_id -> {name, hourly_rate}
    rates = {}
    for _, row in df.iterrows():
        rates[row['project_id']] = {
            'name': row['project_name'],
            'hourly_rate': row['hourly_rate']
        }
    
    return rates

def load_salaries():
    """Load employee salaries from CSV file"""
    csv_file = "salary.csv"
    
    if not Path(csv_file).exists():
        print(f"❌ Error: {csv_file} not found!")
        print(f"   Please create {csv_file} with columns: employee_id,employee_name,month,salary")
        return pd.DataFrame()
    
    df = pd.read_csv(csv_file)
    
    # Validate required columns
    required_cols = ['employee_id', 'employee_name', 'month', 'salary']
    if not all(col in df.columns for col in required_cols):
        print(f"❌ Error: {csv_file} must have columns: {', '.join(required_cols)}")
        return pd.DataFrame()
    
    return df

def process_time_entries(entries, project_rates):
    """Convert time entries to work hours with earnings"""
    data = []
    
    for entry in entries:
        # Parse time interval
        start = datetime.fromisoformat(entry['timeInterval']['start'].replace('Z', '+00:00'))
        
        # Handle ongoing entries (no end time)
        if entry['timeInterval'].get('end'):
            end = datetime.fromisoformat(entry['timeInterval']['end'].replace('Z', '+00:00'))
            duration = (end - start).total_seconds() / 3600
        else:
            continue  # Skip ongoing entries
        
        # Get project info
        project_id = entry.get('projectId', 'No Project')
        project_info = project_rates.get(project_id, {'name': 'No Project', 'hourly_rate': 0})
        
        # Calculate earnings
        earned = duration * project_info['hourly_rate']
        
        data.append({
            'employee_id': entry['userId'],
            'project_id': project_id,
            'project_name': project_info['name'],
            'hours': duration,
            'hourly_rate': project_info['hourly_rate'],
            'earned': earned,
            'month': start.strftime('%Y-%m'),
            'date': start.date()
        })
    
    return pd.DataFrame(data) if data else pd.DataFrame()

def main():
    # Check API credentials
    if not CLOCKIFY_API_KEY or not WORKSPACE_ID:
        print("❌ ERROR: Please set CLOCKIFY_API_KEY and CLOCKIFY_WORKSPACE_ID")
        print("\nCreate a .env file with:")
        print("CLOCKIFY_API_KEY=your_api_key_here")
        print("CLOCKIFY_WORKSPACE_ID=your_workspace_id_here")
        print("\nGet your API key from: https://app.clockify.me/user/settings")
        return
    
    # Get date range for last 3 months
    start_date, end_date = get_last_three_months()
    print(f"📅 Fetching data from {start_date.date()} to {end_date.date()}")
    
    # Load data from CSV files
    print("\n📂 Loading data from CSV files...")
    
    print("  → Loading project_rates.csv...")
    project_rates = load_project_rates()
    if not project_rates:
        return
    print(f"     Loaded {len(project_rates)} projects")
    
    print("  → Loading salary.csv...")
    salary_df = load_salaries()
    if salary_df.empty:
        return
    print(f"     Loaded {len(salary_df)} salary records")
    
    # Fetch data from Clockify
    print("\n🔄 Fetching time entries from Clockify...")
    
    print("  → Getting users from 'full-time' group...")
    users = fetch_users()
    print(f"     Found {len(users)} full-time users")
    
    # Fetch time entries for all users
    print("  → Fetching time entries...")
    all_entries = []
    for user in users:
        entries = fetch_time_entries(user['id'], start_date, end_date)
        all_entries.extend(entries)
    print(f"     Retrieved {len(all_entries)} time entries")
    
    # Process time entries
    print("\n📊 Processing data...")
    hours_df = process_time_entries(all_entries, project_rates)
    
    if hours_df.empty:
        print("⚠️  No time entries found for the selected period")
        return
    
    # Calculate earnings per employee per month
    earned_monthly = (
        hours_df.groupby(["employee_id", "month"])
        .agg({
            "earned": "sum",
            "hours": "sum"
        })
        .reset_index()
    )
    
    # Merge earnings with salaries from CSV
    result = salary_df.merge(
        earned_monthly,
        on=["employee_id", "month"],
        how="left"
    )
    
    result["earned"] = result["earned"].fillna(0)
    result["hours"] = result["hours"].fillna(0)
    
    # Calculate ratio (earned / salary)
    # Handle division by zero
    result["ratio"] = result.apply(
        lambda row: row["earned"] / row["salary"] if row["salary"] > 0 else 0,
        axis=1
    )
    result["ratio"] = result["ratio"].round(6)
    
    # Sort by month and employee
    result = result.sort_values(['month', 'employee_name'])
    
    # Save results
    result.to_csv("performance.csv", index=False)
    hours_df.to_csv("detailed_hours.csv", index=False)
    
    print("\n✅ Processing complete!")
    print(f"\n📈 Performance Summary:")
    print(result[['employee_name', 'month', 'hours', 'salary', 'earned', 'ratio']].to_string(index=False))
    print(f"\n💾 Files saved:")
    print(f"   • performance.csv - Performance ratios per employee/month")
    print(f"   • detailed_hours.csv - Detailed time entries with earnings")
    
    # Warnings
    if (result['salary'] == 0).any():
        print(f"\n⚠️  Warning: Some employees have salary = 0 in salary.csv")
    
    if (hours_df['hourly_rate'] == 0).any():
        print(f"\n⚠️  Warning: Some projects have hourly_rate = 0 in project_rates.csv")
        zero_rate_projects = hours_df[hours_df['hourly_rate'] == 0]['project_name'].unique()
        print(f"   Projects with rate = 0:")
        for project in zero_rate_projects:
            print(f"   • {project}")

if __name__ == "__main__":
    main()