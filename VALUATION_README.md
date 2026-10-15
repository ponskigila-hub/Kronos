# Valuation tab — relative peer multiples

## Tujuan dan cara memakai

Buka **Valuation** di sebelah **Backtest**, masukkan satu ticker target dan 3–8 ticker peer yang Anda pilih sendiri, lalu tekan **Compare valuation**. Penarikan data berjalan sebagai server-side background job; pindah tab browser tidak membatalkannya selama proses Python tetap aktif.

Fitur ini adalah alat **relative valuation** sederhana. Ia membandingkan multiple target dengan multiple peer terpilih dan menunjukkan rentang harga yang secara mekanis tersirat dari multiple itu. Hasilnya **bukan intrinsic fair value, DCF, atau rekomendasi transaksi**. App tidak memilih peer otomatis: kesesuaian bisnis, geografi, ukuran, pertumbuhan, margin, leverage, dan siklus industri harus diperiksa pengguna.

## Metode

Untuk setiap metode, minimal tiga peer harus memiliki multiple positif yang dapat digunakan. Rentang peer menggunakan persentil ke-25, median, dan persentil ke-75. Perkiraan per saham berasal dari data target:

| Metode | Per-share input target | Multiple peer |
|---|---|---|
| Forward P/E | Forward EPS positif | Forward P/E |
| Price / Sales | Revenue per share TTM positif | Price / Sales TTM |
| Price / Book | Book value per share positif | Price / Book |
| EV / EBITDA | EBITDA TTM positif, debt, cash, dan shares outstanding tersedia | EV / EBITDA |

Untuk EV/EBITDA: `(peer EV/EBITDA × EBITDA target − net debt target) ÷ shares outstanding target`, dengan net debt = debt − cash. Jika input penting tidak ada, EBITDA/EPS/book value tidak positif, atau jumlah peer valid kurang dari tiga, metode itu tidak ditampilkan.

Ringkasan gabungan hanya muncul jika setidaknya dua metode dapat dihitung. Ringkasan tersebut adalah median midpoint antar-metode, bukan target harga. Label “potential relative discount/premium” memakai selisih ±15% terhadap harga provider saat ini sebagai penanda untuk diteliti lebih lanjut; label ini bukan keputusan investasi.

## Data dan keterbatasan

Tab menggunakan ringkasan perusahaan Yahoo Finance melalui dependency `yfinance` yang sudah dipakai project. Ini data sekunder; quote bisa tertunda, statement date/publication date tidak selalu diverifikasi, nilai dapat kosong atau direvisi, dan output mencatat waktu retrieval serta timestamp quote provider bila ada. Tidak ada point-in-time historical fundamentals, rekonsiliasi laporan regulator, atau verifikasi manual atas setiap field.

Multiples bukan apples-to-apples jika pertumbuhan, margin, leverage, akuntansi, pajak, geografi, atau siklus bisnis berbeda. Multiples negatif/tidak bermakna dikecualikan, bukan dipaksa menjadi angka. P/S pun tidak memasukkan profitabilitas; P/B sering lebih berguna untuk perusahaan keuangan; EV/EBITDA mengabaikan capex dan kebutuhan modal kerja. Gunakan seluruh tabel dan periksa risiko perusahaan, bukan hanya ringkasan.

Jika ingin intrinsic valuation yang lebih lengkap, langkah berikutnya bukan mengubah median peer ini menjadi “fair value”; perlu input laporan resmi, cash-flow forecast per skenario, WACC, terminal assumptions, diluted shares, net debt, dan sensitivitas bear/base/bull dengan tanggal data yang jelas.
