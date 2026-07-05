import pandas as pd
import matplotlib.pyplot as plt
import yfinance as yf

from model import Kronos, KronosTokenizer, KronosPredictor

print("🚀 Starting Kronos prediction...")

# =====================================================
# Load Kronos
# =====================================================

print("📥 Loading model...")
tokenizer = KronosTokenizer.from_pretrained(
    "NeoQuasar/Kronos-Tokenizer-base"
)

model = Kronos.from_pretrained(
    "NeoQuasar/Kronos-small"
)

print("✅ Model loaded!")

predictor = KronosPredictor(
    model,
    tokenizer,
    max_context=512
)

# =====================================================
# Download Data
# =====================================================

print("📊 Downloading data...")

df = yf.download(
    "AAPL",
    start="2020-01-01",
    end="2026-01-01",
    interval="1d",
    auto_adjust=False,
    progress=True
)

# Fix MultiIndex from newer yfinance versions
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

# Rename columns to Kronos format
df = df.rename(columns={
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume"
})

# Kronos expects amount column
df["amount"] = df["volume"]

# Move date index into a column
df = df.reset_index()

if "Date" in df.columns:
    df = df.rename(columns={"Date": "timestamps"})

df["timestamps"] = pd.to_datetime(df["timestamps"])

print("\nDataset Info")
print("Rows:", len(df))
print(df.head())

# =====================================================
# Prediction Settings
# =====================================================

lookback = min(400, len(df))
pred_len = 30

print("\nPrediction Settings")
print("Lookback:", lookback)
print("Future Days:", pred_len)

# =====================================================
# Historical Context
# =====================================================

x_df = df.iloc[-lookback:][
    ["open", "high", "low", "close", "volume", "amount"]
].copy()

x_timestamp = df.iloc[-lookback:]["timestamps"].copy()

# =====================================================
# Create Future Dates
# =====================================================

last_date = df["timestamps"].max()

future_dates = pd.date_range(
    start=last_date + pd.offsets.BDay(1),
    periods=pred_len,
    freq="B"
)

# Kronos usually prefers Series
y_timestamp = pd.Series(future_dates)

print("\nFuture Prediction Dates")
print(y_timestamp.head())
print("...")
print(y_timestamp.tail())

print("\nDebug")
print("Historical Rows:", len(x_df))
print("Historical Timestamps:", len(x_timestamp))
print("Future Timestamps:", len(y_timestamp))

# =====================================================
# Predict
# =====================================================

print(f"\n🔮 Predicting next {pred_len} trading days...")

pred_df = predictor.predict(
    df=x_df,
    x_timestamp=x_timestamp,
    y_timestamp=y_timestamp,
    pred_len=pred_len,
    T=1.0,
    top_p=0.9,
    sample_count=1,
    verbose=True
)

# =====================================================
# Add Prediction Dates
# =====================================================

pred_df["timestamps"] = future_dates

print("\n✅ Prediction Complete!")

print("\nPredicted Close Prices:")
print(
    pred_df[
        ["timestamps", "close"]
    ].head(30)
)

# =====================================================
# Save Predictions
# =====================================================

pred_df.to_csv(
    "AAPL_future_predictions.csv",
    index=False
)

print("\n💾 Saved predictions:")
print("AAPL_future_predictions.csv")

# =====================================================
# Plot
# =====================================================

plt.figure(figsize=(14, 7))

plt.plot(
    df["timestamps"].iloc[-lookback:],
    df["close"].iloc[-lookback:],
    label="Historical"
)

plt.plot(
    pred_df["timestamps"],
    pred_df["close"],
    "--",
    label="Predicted"
)

plt.title("AAPL Forecast - Next 30 Trading Days")
plt.xlabel("Date")
plt.ylabel("Close Price")
plt.legend()
plt.grid(True)

plt.xticks(rotation=45)

plt.tight_layout()

plt.savefig(
    "kronos_prediction.png",
    dpi=150
)

print("\n📊 Chart saved as:")
print("kronos_prediction.png")

plt.show()