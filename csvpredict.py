import pandas as pd
import matplotlib.pyplot as plt

from model import Kronos, KronosTokenizer, KronosPredictor

print("🚀 Starting Kronos prediction...")

# =====================================================
# LOAD MODEL
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
# LOAD CSV
# =====================================================

print("📊 Loading CSV data...")

df = pd.read_csv("./own_data/CIFR-history.csv")

print("\nOriginal columns:")
print(df.columns.tolist())

# Rename columns to Kronos format
df = df.rename(columns={
    "Date": "timestamps",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume"
})

# Create amount column
df["amount"] = df["volume"]

# =====================================================
# CLEAN DATA
# =====================================================

# Convert date
df["timestamps"] = pd.to_datetime(df["timestamps"])

# Remove commas from numeric columns
numeric_cols = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount"
]

for col in numeric_cols:
    df[col] = (
        df[col]
        .astype(str)
        .str.replace(",", "", regex=False)
    )

    df[col] = pd.to_numeric(
        df[col],
        errors="coerce"
    )

# Remove rows with missing values
df = df.dropna(
    subset=[
        "timestamps",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount"
    ]
)

# Sort oldest -> newest
df = df.sort_values("timestamps")

df = df.reset_index(drop=True)

print("\nDataset Info")
print("Rows:", len(df))

print("\nData Types:")
print(df.dtypes)

print("\nFirst Rows:")
print(df.head())

print("\nLast Rows:")
print(df.tail())

# =====================================================
# PREDICTION SETTINGS
# =====================================================

lookback = min(512, len(df))

pred_len = 30

print("\nPrediction Settings")
print("Lookback:", lookback)
print("Predict Days:", pred_len)

# =====================================================
# PREPARE INPUT
# =====================================================

x_df = df.iloc[-lookback:][
    [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount"
    ]
].copy()

x_timestamp = df.iloc[-lookback:][
    "timestamps"
].copy()

# =====================================================
# FUTURE DATES
# =====================================================

last_date = df["timestamps"].max()

future_dates = pd.date_range(
    start=last_date + pd.offsets.BDay(1),
    periods=pred_len,
    freq="B"
)

y_timestamp = pd.Series(future_dates)

print("\nFuture prediction range:")
print(future_dates[0])
print("to")
print(future_dates[-1])

# =====================================================
# RUN PREDICTION
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
# ATTACH FUTURE DATES
# =====================================================

pred_df = pred_df.iloc[:pred_len].copy()

pred_df["timestamps"] = future_dates[:len(pred_df)]

# =====================================================
# DISPLAY RESULTS
# =====================================================

print("\n✅ Prediction Complete!")

print(
    pred_df[
        [
            "timestamps",
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]
    ]
)

# Save CSV
pred_df.to_csv(
    "future_predictions.csv",
    index=False
)

print("\n💾 Saved future_predictions.csv")

# =====================================================
# PLOT
# =====================================================

plt.figure(figsize=(15, 7))

plt.plot(
    x_timestamp,
    x_df["close"],
    label="Historical",
    linewidth=1.5
)

plt.plot(
    pred_df["timestamps"],
    pred_df["close"],
    "--",
    linewidth=2,
    label="Predicted"
)

plt.axvline(
    x=x_timestamp.iloc[-1],
    linestyle=":",
    linewidth=1
)

plt.xlabel("Date")
plt.ylabel("Close Price")
plt.title("Kronos Forecast - Next 30 Trading Days")
plt.legend()
plt.grid(True)

plt.xticks(rotation=45)

plt.tight_layout()

plt.savefig(
    "kronos_prediction.png",
    dpi=150
)

print("\n📊 Saved kronos_prediction.png")

plt.show()