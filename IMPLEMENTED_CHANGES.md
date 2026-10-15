# Catatan perubahan — review & backtest

## Perubahan

- Walk-forward sekarang mengukur **endpoint tetap** (`t+h`), satu observasi per origin/horizon, tidak menganggap semua titik lintasan forecast sebagai sampel independen.
- Menambahkan actual/predicted return, serta `return_mae`, `return_rmse`, dan `return_bias`.
- Uji Diebold–Mariano menyelaraskan prediksi per origin; menolak memberi p-value jika origin berpasangan kurang dari 20; dapat menggunakan return error.
- Pembanding signifikansi ditetapkan sebelum tes sebagai **Naive (last close)**, bukan benchmark yang dipilih berdasarkan hasil pada sampel tes. Runner penuh menambahkan koreksi Holm di antara horizon.
- Simulasi sinyal memakai forecast vs close origin, entry di open bar berikutnya, exit di endpoint close, dan biaya dua sisi.
- Annualisasi rasio risiko mengikuti jarak antar forecast origin (`step_size`), bukan horizon yang dilaporkan.
- Untuk CPU-only, default PyTorch dibatasi empat thread (bisa diganti lewat `KRONOS_CPU_THREADS`). Default backtest web dinaikkan ke 30 windows (bisa diubah pada formulir; server membatasi 5–60).
- Proses backtest berjalan sebagai job background pada server; berpindah tab Chrome tidak membatalkan kalkulasi. Server Python harus tetap hidup. Jika server dimatikan/restart saat pekerjaan berlangsung, job in-memory akan berhenti.

## Jalankan

```bash
python -m pip install -r requirements.txt
python webapp/app.py
```

Lalu buka `http://127.0.0.1:5050`. Jangan tutup terminal/proses Python saat backtest sedang berjalan. Browser boleh berpindah ke tab lain; polling status mungkin baru diperbarui setelah kembali ke tab.

## Verifikasi

- `python -m compileall -q backtesting assistant webapp tests/test_backtesting_validation.py`
- `python -m pytest -q tests/test_backtesting_validation.py tests/test_jobs.py` — **12 passed**.

Smoke test import Flask tidak dapat dilakukan tuntas di sandbox review ini karena beberapa dependency proyek (mis. `yfinance` dan PyTorch) tidak terpasang. Jalankan `pip install -r requirements.txt` di komputer project terlebih dahulu.

## Batas yang masih tersisa

- Simulasi tetap sederhana: belum ada spread, slippage, market impact, short borrow/dividend, intratrade mark-to-market, atau overlap posisi.
- Uji DM hanya membandingkan kualitas forecast, bukan menguji positifnya return bersih strategi. Bahkan p-value yang lolos bukan jaminan profitabilitas.
- Tuning model/threshold masih perlu dipisahkan dari periode final test yang tak disentuh; fitur teknikal/fundamental belum ditambahkan karena sebaiknya baru diuji setelah pipeline evaluasi stabil.
