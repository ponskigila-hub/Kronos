# Catatan perubahan — Kronos stock research

Tanggal: 15 Oktober 2026

## Yang berubah

| Area | Perubahan |
|---|---|
| Menu aplikasi | Menambahkan tab **Valuation** tepat di sebelah **Backtest** pada navigasi. |
| Valuation | Menambahkan `assistant/valuation.py`, route Flask, halaman dan job background. Pengguna memasukkan satu ticker serta 3–8 peer pilihannya; hasil menampilkan rasio fundamental, metode yang lolos pemeriksaan data, rentang implied peer-multiple persentil 25/median/75, perbedaan terhadap harga provider, timestamp, dan peringatan untuk sektor/industri peer yang berbeda. |
| Metode valuasi | Forward P/E, Price/Sales, Price/Book, EV/EBITDA jika input denominator positif dan data cukup. Summary midpoint median hanya ditampilkan bila minimal dua metode tersedia. Output sengaja disebut **relative discount/premium vs selected peers**, bukan fair value atau sinyal beli/jual. |
| Data | Menggunakan `yfinance` yang sudah menjadi dependency project, dan melakukan lookup berurutan di background job. Data Yahoo adalah sumber sekunder; retrieval time dan quote timestamp (bila ada) ditampilkan. Footer sekarang menjelaskan bahwa query ticker/berita publik dikirim ke provider. |
| Backtest | Penjelasan UI menyebut backtest sebagai replay historis walk-forward, menjelaskan endpoint/origin, baseline model, perbedaan dari forward demo fake-cash, batas p-value, dan kebutuhan periode holdout baru bila hasil digunakan untuk tuning. |
| Ranking forecast | Memakai endpoint **return RMSE** untuk ranking model agar perbandingan tidak semata-mata dipengaruhi skala nominal harga; price RMSE tetap dilaporkan sebagai metrik diagnostik. Hasil juga mencatat jumlah endpoint origin yang benar-benar ada. |
| Benchmark trading | Menambahkan matched always-long baseline pada origin dan interval yang sama, dengan entry next-open, exit endpoint-close, modal dan asumsi biaya yang sama. Full runner memasukkan kedua baris strategi pada `portfolio_metrics_by_horizon.csv`. |
| Transparansi biaya | Biaya simulasi saat ini diasumsikan 0,05% tiap sisi (0,10% round trip), tanpa spread/slippage/market impact. Belum memasukkan short-borrow, dividend, dan overlapping positions. |
| Dokumentasi | Memperbarui `WEBAPP_README.md`, `BACKTEST_README.md`; menambah `VALUATION_README.md`. |

## Cara pakai

Pasang dependency di komputer project, lalu jalankan:

```bash
python -m pip install -r requirements.txt
python webapp/app.py
```

Buka `http://127.0.0.1:5050`, pilih **Valuation**, masukkan ticker target dan sedikitnya tiga peer yang benar-benar sebanding. Lookup dan backtest berjalan di thread server; Anda boleh berpindah tab Chrome, tetapi app Python harus tetap hidup. Job in-memory hilang jika server restart.

## Cara membaca hasil

Halaman Valuation membandingkan multiple peer, bukan melakukan DCF intrinsik. Pertumbuhan, kualitas earnings, rasio utang, capex, accounting basis, geografi, dan business model dapat menjelaskan perbedaan multiple. Peer yang dipilih pengguna tetap perlu diperiksa manual; jumlah peer yang cukup tidak menjamin peers-nya tepat.

Backtest walk-forward mengevaluasi titik endpoint h=5/14/30 trading bars dengan origin yang dijarakkan sekitar 30 trading bars, membandingkan forecast Kronos dengan Naive (last close) serta linear regression. DM adalah tes forecast-loss berpasangan, bukan tes profit strategi. Di bawah 20 paired origins p-value tidak dikeluarkan; koreksi Holm di runner penuh hanya mencakup horizon yang dilaporkan per ticker, bukan semua percobaan, ticker atau parameter yang mungkin dicoba. Jika hasil dipakai untuk memilih parameter, uji final harus dilakukan pada data periode berikutnya yang tidak disentuh.

## Verifikasi

- Python compile: lulus (`compileall` untuk modules dan tests).
- Regression tests backtest, valuation, dan background jobs: **18 passed**.
- Jinja syntax untuk base, backtest, valuation: lulus.
- Tidak dilakukan request market data live untuk test unit; formula valuation memakai fixture sintetis offline.
- Smoke test server Flask penuh tidak dapat dijalankan di sandbox karena beberapa dependency project (termasuk `yfinance` dan PyTorch) tidak terpasang di sana. Dependency tersebut tercantum di `requirements.txt`; test UI/runtime akhir perlu dilakukan setelah install pada komputer project.

## Keterbatasan yang belum diimplementasikan

Valuation belum memakai laporan SEC/regulator yang diverifikasi, point-in-time fundamentals, DCF skenario bear/base/bull, WACC/terminal-value sensitivity, atau auto-selected industry peers. Karena itu ia tidak boleh dipakai sebagai penilaian intrinsik presisi. Backtest masih memakai historical Yahoo OHLC tanpa dividend total-return adjustment; costs dan fills tetap penyederhanaan. Hasil historis tidak membuktikan edge atau profit masa depan.
