import json
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
import os
import time
import subprocess

# 1. Get JSON file path
file_path = input('Json File Please : ').strip()
if not file_path:
    print("No file specified. Exiting.")
    exit()

# 2. Load data
with open(file_path, 'r') as f:
    data = json.load(f)

df = pd.DataFrame(data)
df['timestamp'] = pd.to_datetime(df['timestamp'])
df.set_index('timestamp', inplace=True)

df.rename(columns={
    'open': 'Open',
    'high': 'High',
    'low': 'Low',
    'close': 'Close',
    'volume': 'Volume'
}, inplace=True)

df.sort_index(inplace=True)

# 3. Create candlestick chart (save only, no interactive window)
fig, axes = mpf.plot(
    df,
    type='candle',
    volume=True,
    style='charles',
    title='نمودار کندلی BTC/USD (دقیقه‌ای)',
    ylabel='قیمت (دلار)',
    ylabel_lower='حجم معاملات',
    figsize=(14, 8),
    datetime_format='%H:%M',
    xrotation=0,
    returnfig=True
)

# 4. Save the figure
script_dir = os.path.dirname(os.path.abspath(__file__))
output_filename = os.path.join(script_dir, 'candle_chart.png')

print(f"Saving chart to: {output_filename}")
try:
    fig.savefig(output_filename, dpi=300, bbox_inches='tight')
    time.sleep(0.3)  # ensure file is flushed to disk
    print("Save completed.")
except Exception as e:
    print(f"Error saving chart: {e}")
    exit()

# 5. Open the PNG without a CMD window
if os.path.isfile(output_filename):
    print("File verified, opening...")
    if os.name == 'nt':  # Windows
        try:
            os.startfile(output_filename)          # preferred – no window
        except Exception as e:
            print(f"os.startfile failed: {e}, trying explorer...")
            # Fallback: use explorer – no CMD window
            subprocess.Popen(['explorer', output_filename])
    elif os.name == 'posix':  # Linux / macOS
        try:
            subprocess.Popen(['xdg-open', output_filename])
        except:
            subprocess.Popen(['open', output_filename])
    else:
        print(f"File saved, but auto-open not supported on this OS: {output_filename}")
else:
    print(f"ERROR: File not found after save: {output_filename}")

# (Optional) If you want the interactive hover window, uncomment:
# plt.show()