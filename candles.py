import json
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
import numpy as np
import os
import subprocess
import time  # for a tiny delay

# 1. Read JSON file path
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

# 3. Plot
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

ax_main = axes[0]
ax_vol = axes[1]

# 4. Hover annotation
annotation = ax_main.annotate(
    '',
    xy=(0, 0),
    xytext=(10, 10),
    textcoords='offset points',
    bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.7),
    fontsize=9,
    visible=False
)

def on_motion(event):
    if event.inaxes != ax_main:
        annotation.set_visible(False)
        fig.canvas.draw_idle()
        return
    xdata = event.xdata
    if xdata is None:
        return
    x_index = int(round(xdata))
    if x_index < 0 or x_index >= len(df):
        return
    timestamp = df.index[x_index]
    row = df.iloc[x_index]
    text = (f'زمان: {timestamp.strftime("%H:%M:%S")}\n'
            f'Open: {row["Open"]:.2f}\n'
            f'High: {row["High"]:.2f}\n'
            f'Low: {row["Low"]:.2f}\n'
            f'Close: {row["Close"]:.2f}\n'
            f'Volume: {row["Volume"]:.4f}')
    annotation.xy = (xdata, event.ydata)
    annotation.set_text(text)
    annotation.set_visible(True)
    fig.canvas.draw_idle()

fig.canvas.mpl_connect('motion_notify_event', on_motion)

# 5. Save figure with absolute path
script_dir = os.path.dirname(os.path.abspath(__file__))
output_filename = os.path.join(script_dir, 'candle_chart.png')

print(f"Attempting to save chart to: {output_filename}")
try:
    fig.savefig(output_filename, dpi=300, bbox_inches='tight')
    time.sleep(0.1)  # give the OS a moment to finish writing
    print("Save completed.")
except Exception as e:
    print(f"Error saving chart: {e}")
    exit()

# 6. Verify the file exists before opening
if os.path.isfile(output_filename):
    print(f"File exists at: {output_filename}")
    # Open with default program
    if os.name == 'nt':  # Windows
        # Use 'start' via subprocess – handles spaces and special characters
        subprocess.Popen(['start', output_filename], shell=True)
    elif os.name == 'posix':  # Linux / macOS
        try:
            subprocess.Popen(['xdg-open', output_filename])
        except:
            subprocess.Popen(['open', output_filename])
    else:
        print(f"File saved, but can't auto-open on this OS: {output_filename}")
else:
    print(f"ERROR: File was NOT saved at {output_filename}")
    print("Please check permissions or disk space.")

# 7. Show interactive window
plt.show()