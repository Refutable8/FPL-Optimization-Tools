import os
import pandas as pd
import requests

# Fetch data from the API
r = requests.get('https://fantasy.premierleague.com/api/bootstrap-static/')
fpl_data = r.json()

# Create a DataFrame with selected columns
element_data = pd.DataFrame(fpl_data['elements'])
ownership_df = element_data[['web_name', 'selected_by_percent', 'id']].copy()

# Set index and rename columns
ownership_df.set_index('id', inplace=True)
ownership_df.index.rename(name='ID', inplace=True)
ownership_df.rename(columns={'web_name': 'Name', 'selected_by_percent': 'Current Own%'}, inplace=True)

# Get the script's directory
script_dir = os.path.dirname(os.path.abspath(__file__))

# Construct the full path for the output file
output_path = os.path.join(script_dir, '../data', 'ownership_overall.csv')

# Save DataFrame to a CSV file
ownership_df.to_csv(output_path)
