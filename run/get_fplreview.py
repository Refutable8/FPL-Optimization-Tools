import os
import shutil
from glob import glob

# Paths
downloads_folder = os.path.expanduser('~/Downloads')
target_filename1 = 'fplreview.csv'
target_filename2 = 'fplreview_md.csv'
dest_folder_1 = r'C:\Users\Andrew\Documents\Jupyter Notebooks\FPL-Optimization-Tools\data'
dest_folder_2 = r'C:\Users\Andrew\Documents\Jupyter Notebooks\data'

# Find the most recent fplreview_####.csv file
files = glob(os.path.join(downloads_folder, 'fplreview_*.csv'))
most_recent_file = max(files, key=os.path.getmtime)

# Copy and rename to the first destination
shutil.copy2(most_recent_file, os.path.join(dest_folder_1, target_filename1))
print(f"Copied to {os.path.join(dest_folder_1, target_filename1)}")

# Copy and rename to the second destination
shutil.copy2(most_recent_file, os.path.join(dest_folder_2, target_filename2))
print(f"Copied to {os.path.join(dest_folder_2, target_filename2)}")

# Copy ownership_overall.csv to the second folder
src_file = os.path.join(dest_folder_2, 'ownership_overall.csv')
shutil.copy2(src_file, dest_folder_1)
print(f"Copied {src_file} to {dest_folder_1}")
