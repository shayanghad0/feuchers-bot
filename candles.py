import json
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
import numpy as np
import os  # <-- اضافه شده برای باز کردن فایل

# خواندن فایل JSON
file_path = input ('Json File Please : ')

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

# رسم نمودار با قابلیت بازگشت figure و axes
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

# دریافت محورهای اصلی و پایین
ax_main = axes[0]
ax_vol = axes[1]

# annotation برای نمایش اطلاعات
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

# ذخیره تصویر به‌صورت PNG با کیفیت بالا
output_filename = 'candle_chart.png'
fig.savefig(output_filename, dpi=300, bbox_inches='tight')

# --- باز کردن فایل PNG با برنامه پیش‌فرض سیستم ---
if os.name == 'nt':  # ویندوز
    os.startfile(output_filename)
elif os.name == 'posix':  # لینوکس / مک
    # برای لینوکس (با xdg-open) و مک (با open)
    import subprocess
    try:
        subprocess.Popen(['xdg-open', output_filename])  # لینوکس
    except:
        subprocess.Popen(['open', output_filename])      # مک
else:
    print(f"فایل ذخیره شد: {output_filename} (سیستمعامل پشتیبانی نمی‌شود برای باز کردن خودکار)")

# نمایش پنجره تعاملی (با قابلیت حرکت موس)
plt.show()