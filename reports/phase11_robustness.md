# Phase 11 — robustness (validation and pre-validation walk-forward folds)

Dataset `dataset-v1-features-v2-labels-v1-u100-s5`. Inputs: Phase 9 walk-forward out-of-fold predictions (no retraining).
Validation 2024-11-05..2025-06-13; pre-validation = folds
F1–F4 inside the training period. Test period not used. Bucket boundaries use training-period
information only; sectors are inferred from daily-return correlation with NIFTY sector indices
(no offline sector master). Cost rows are per-call expectancy, not portfolio P&L (Phase 12).

## lightgbm (tuned) — `y_1m_5bp`

Validation overall: 1,116,225 rows, accuracy 50.1%, balanced accuracy 45.2%, MCC 0.194 (momentum 0.089), UP/DOWN calls 53.4% of rows with sign accuracy 51.5%. Skill split: move-vs-no-move MCC 0.274; direction right on 55.8% of rows that moved and were called.

### Market trend (NIFTY vs 50-day average, previous day)

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| down | 666,225 | 47.8% | 56.1% | 44.6% | 0.183 | 0.084 | 51.2% | 0.226 |
| up | 450,000 | 53.4% | 61.0% | 45.9% | 0.206 | 0.093 | 52.0% | 0.224 |

### Market volatility (NIFTY 20-day, terciles from training dates)

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| high | 457,500 | 52.7% | 60.7% | 45.5% | 0.201 | 0.093 | 51.6% | 0.211 |
| low | 43,800 | 51.6% | 60.1% | 44.9% | 0.190 | 0.086 | 51.6% | 0.229 |
| mid | 614,925 | 48.0% | 55.9% | 44.8% | 0.186 | 0.084 | 51.4% | 0.222 |

### Stock volatility (vol_20, terciles from pre-validation rows)

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| high | 414,401 | 34.6% | 42.5% | 38.4% | 0.080 | 0.035 | 51.1% | 0.113 |
| low | 313,237 | 72.4% | 75.0% | 37.2% | 0.108 | 0.049 | 52.6% | 0.114 |
| mid | 388,587 | 48.5% | 61.0% | 41.6% | 0.125 | 0.030 | 52.2% | 0.147 |

### Time of day (IST)

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| 09:15-09:45 | 88,794 | 37.3% | 36.3% | 35.6% | 0.038 | 0.033 | 50.0% | 0.079 |
| 09:45-11:15 | 267,582 | 41.2% | 51.2% | 42.2% | 0.141 | 0.056 | 50.9% | 0.187 |
| 11:15-14:00 | 491,667 | 55.2% | 63.9% | 44.2% | 0.179 | 0.071 | 52.3% | 0.218 |
| 14:00-14:45 | 134,091 | 55.9% | 65.0% | 44.8% | 0.188 | 0.071 | 52.6% | 0.218 |
| 14:45-15:30 | 134,091 | 51.4% | 62.1% | 44.4% | 0.183 | 0.077 | 51.7% | 0.202 |

### Inferred sector

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| AUTO | 100,467 | 53.4% | 62.4% | 44.4% | 0.190 | 0.093 | 51.0% | 0.213 |
| CONSR DURBL | 66,978 | 46.3% | 55.0% | 44.3% | 0.175 | 0.078 | 52.7% | 0.218 |
| ENERGY | 78,141 | 49.3% | 56.8% | 46.1% | 0.208 | 0.108 | 50.3% | 0.248 |
| FINSRV25 50 | 66,978 | 47.8% | 55.5% | 44.5% | 0.181 | 0.077 | 48.4% | 0.193 |
| FMCG | 78,066 | 56.5% | 64.7% | 45.1% | 0.203 | 0.096 | 52.0% | 0.216 |
| HEALTHCARE | 11,163 | 59.3% | 66.6% | 43.1% | 0.182 | 0.083 | 53.4% | 0.195 |
| INFRA | 133,956 | 50.0% | 58.2% | 44.8% | 0.189 | 0.087 | 51.7% | 0.223 |
| IT | 122,793 | 50.2% | 58.5% | 44.7% | 0.188 | 0.080 | 51.0% | 0.213 |
| MEDIA | 78,141 | 43.6% | 50.0% | 44.4% | 0.170 | 0.062 | 53.5% | 0.210 |
| METAL | 122,793 | 46.4% | 54.5% | 44.3% | 0.174 | 0.071 | 52.6% | 0.218 |
| OIL AND GAS | 33,489 | 47.1% | 57.2% | 43.3% | 0.163 | 0.086 | 50.3% | 0.205 |
| PHARMA | 44,652 | 56.0% | 64.2% | 44.5% | 0.195 | 0.096 | 52.8% | 0.201 |
| PSU BANK | 100,467 | 48.8% | 55.9% | 46.2% | 0.202 | 0.085 | 51.0% | 0.230 |
| PVT BANK | 66,978 | 57.3% | 64.9% | 44.6% | 0.202 | 0.102 | 50.1% | 0.193 |
| REALTY | 11,163 | 45.0% | 52.6% | 43.4% | 0.161 | 0.069 | 52.3% | 0.181 |

### Walk-forward fold

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| F1 | 0 | – | – | – | – | – | – | 0.241 |
| F2 | 0 | – | – | – | – | – | – | 0.235 |
| F3 | 0 | – | – | – | – | – | – | 0.210 |
| F4 | 0 | – | – | – | – | – | – | 0.205 |
| F5 | 1,116,225 | 50.1% | 58.1% | 45.2% | 0.194 | 0.089 | 51.5% | – |

### Month (validation)

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| 2024-11 | 126,300 | 47.7% | 56.2% | 44.3% | 0.179 | 0.083 | 51.5% | – |
| 2024-12 | 157,500 | 54.9% | 62.5% | 45.1% | 0.199 | 0.087 | 51.9% | – |
| 2025-01 | 172,425 | 45.3% | 54.7% | 43.4% | 0.163 | 0.075 | 50.7% | – |
| 2025-02 | 142,500 | 46.4% | 53.8% | 45.0% | 0.184 | 0.083 | 52.0% | – |
| 2025-03 | 142,500 | 50.5% | 58.3% | 45.3% | 0.196 | 0.092 | 51.2% | – |
| 2025-04 | 142,500 | 47.6% | 55.1% | 45.2% | 0.192 | 0.083 | 51.4% | – |
| 2025-05 | 157,500 | 52.8% | 60.9% | 45.6% | 0.201 | 0.091 | 52.1% | – |
| 2025-06 | 75,000 | 59.8% | 66.9% | 45.1% | 0.212 | 0.107 | 51.2% | – |

### Symbols (pre-validation)

100 symbols. MCC mean 0.199, median 0.195, 10th percentile 0.176, min 0.155, max 0.335. MCC > 0 for 100.0% of symbols; beats momentum on 100.0%.
Worst: RBLBANK 0.155, BHEL 0.165, NATIONALUM 0.166, BANKBARODA 0.168, AUBANK 0.170. Best: YESBANK 0.335, ADANIPOWER 0.260, IDFCFIRSTB 0.251, ADANIGREEN 0.248, PAYTM 0.247.

### Symbols (validation)

100 symbols. MCC mean 0.175, median 0.177, 10th percentile 0.150, min 0.102, max 0.271. MCC > 0 for 100.0% of symbols; beats momentum on 100.0%.
Worst: PAYTM 0.102, BHEL 0.122, NATIONALUM 0.128, RBLBANK 0.130, ETERNAL 0.132. Best: YESBANK 0.271, ADANIPOWER 0.219, MARUTI 0.205, ASIANPAINT 0.204, BALRAMCHIN 0.200.

### Cost sensitivity (validation, per UP/DOWN call over the label horizon)

| Min P(direction) | Calls | Share of rows | Hit rate | Gross bp | Net @2bp | Net @5bp | Net @10bp | Net @20bp | Break-even bp |
|---|---|---|---|---|---|---|---|---|---|
| 0.00 | 595,947 | 53.4% | 51.5% | 0.77 | -1.23 | -4.23 | -9.23 | -19.23 | 0.77 |
| 0.40 | 420,628 | 37.7% | 52.3% | 0.93 | -1.07 | -4.07 | -9.07 | -19.07 | 0.93 |
| 0.45 | 200,217 | 17.9% | 53.1% | 1.23 | -0.77 | -3.77 | -8.77 | -18.77 | 1.23 |
| 0.50 | 55,969 | 5.0% | 54.8% | 1.92 | -0.08 | -3.08 | -8.08 | -18.08 | 1.92 |

## lightgbm (tuned) — `y_5m_10bp`

Validation overall: 1,101,326 rows, accuracy 48.0%, balanced accuracy 43.1%, MCC 0.168 (momentum 0.087), UP/DOWN calls 53.8% of rows with sign accuracy 50.7%. Skill split: move-vs-no-move MCC 0.262; direction right on 52.2% of rows that moved and were called.

### Market trend (NIFTY vs 50-day average, previous day)

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| down | 657,326 | 45.7% | 53.1% | 42.4% | 0.156 | 0.082 | 50.4% | 0.201 |
| up | 444,000 | 51.3% | 58.1% | 43.8% | 0.182 | 0.091 | 51.3% | 0.205 |

### Market volatility (NIFTY 20-day, terciles from training dates)

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| high | 451,400 | 50.8% | 58.0% | 43.8% | 0.181 | 0.091 | 51.4% | 0.200 |
| low | 43,200 | 50.1% | 56.4% | 43.1% | 0.169 | 0.076 | 51.9% | 0.204 |
| mid | 606,726 | 45.7% | 52.9% | 42.4% | 0.156 | 0.082 | 50.3% | 0.201 |

### Stock volatility (vol_20, terciles from pre-validation rows)

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| high | 409,757 | 33.4% | 39.7% | 36.1% | 0.047 | 0.028 | 50.6% | 0.089 |
| low | 307,784 | 69.6% | 71.7% | 35.5% | 0.077 | 0.048 | 51.3% | 0.068 |
| mid | 383,785 | 46.1% | 58.2% | 38.9% | 0.095 | 0.028 | 50.9% | 0.109 |

### Time of day (IST)

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| 09:15-09:45 | 88,794 | 37.0% | 36.8% | 34.5% | 0.020 | 0.025 | 50.2% | 0.065 |
| 09:45-11:15 | 267,582 | 39.2% | 47.5% | 40.2% | 0.114 | 0.044 | 50.7% | 0.163 |
| 11:15-14:00 | 491,667 | 53.2% | 61.2% | 41.6% | 0.152 | 0.073 | 51.1% | 0.192 |
| 14:00-14:45 | 134,091 | 54.5% | 62.8% | 41.7% | 0.157 | 0.080 | 50.2% | 0.192 |
| 14:45-15:30 | 119,192 | 46.8% | 58.6% | 41.4% | 0.143 | 0.070 | 50.9% | 0.159 |

### Inferred sector

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| AUTO | 99,126 | 50.0% | 58.3% | 42.3% | 0.160 | 0.082 | 50.4% | 0.190 |
| CONSR DURBL | 66,084 | 44.2% | 52.0% | 42.2% | 0.149 | 0.074 | 51.0% | 0.195 |
| ENERGY | 77,098 | 47.3% | 52.7% | 44.2% | 0.183 | 0.094 | 50.6% | 0.234 |
| FINSRV25 50 | 66,084 | 46.9% | 54.9% | 42.1% | 0.152 | 0.075 | 49.8% | 0.173 |
| FMCG | 77,024 | 54.3% | 61.9% | 43.4% | 0.182 | 0.098 | 51.4% | 0.201 |
| HEALTHCARE | 11,014 | 57.9% | 65.2% | 42.2% | 0.171 | 0.089 | 52.1% | 0.183 |
| INFRA | 132,168 | 48.0% | 54.8% | 43.0% | 0.168 | 0.086 | 50.4% | 0.205 |
| IT | 121,154 | 48.6% | 56.2% | 42.9% | 0.169 | 0.093 | 50.2% | 0.191 |
| MEDIA | 77,098 | 42.0% | 47.3% | 42.2% | 0.144 | 0.069 | 52.0% | 0.207 |
| METAL | 121,154 | 44.4% | 51.0% | 42.3% | 0.149 | 0.070 | 51.3% | 0.193 |
| OIL AND GAS | 33,042 | 44.7% | 52.8% | 41.5% | 0.139 | 0.077 | 49.6% | 0.204 |
| PHARMA | 44,056 | 53.3% | 61.5% | 42.4% | 0.166 | 0.095 | 51.1% | 0.182 |
| PSU BANK | 99,126 | 46.0% | 53.1% | 42.4% | 0.155 | 0.075 | 50.4% | 0.200 |
| PVT BANK | 66,084 | 55.4% | 62.7% | 43.0% | 0.183 | 0.098 | 50.4% | 0.179 |
| REALTY | 11,014 | 42.4% | 49.1% | 40.8% | 0.127 | 0.064 | 51.5% | 0.166 |

### Walk-forward fold

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| F1 | 0 | – | – | – | – | – | – | 0.209 |
| F2 | 0 | – | – | – | – | – | – | 0.208 |
| F3 | 0 | – | – | – | – | – | – | 0.190 |
| F4 | 0 | – | – | – | – | – | – | 0.191 |
| F5 | 1,101,326 | 48.0% | 55.1% | 43.1% | 0.168 | 0.087 | 50.7% | – |

### Month (validation)

| Bucket | Val rows | Val acc | Val majority | Val bal acc | Val MCC | Val momentum MCC | Val sign acc (UP/DOWN calls) | Pre-val MCC |
|---|---|---|---|---|---|---|---|---|
| 2024-11 | 124,600 | 45.3% | 53.6% | 41.7% | 0.144 | 0.081 | 50.0% | – |
| 2024-12 | 155,400 | 53.0% | 60.1% | 42.5% | 0.170 | 0.084 | 50.4% | – |
| 2025-01 | 170,126 | 43.0% | 51.5% | 41.3% | 0.136 | 0.076 | 50.0% | – |
| 2025-02 | 140,600 | 44.4% | 51.1% | 42.8% | 0.158 | 0.074 | 50.9% | – |
| 2025-03 | 140,600 | 48.2% | 54.1% | 43.0% | 0.167 | 0.084 | 51.0% | – |
| 2025-04 | 140,600 | 45.3% | 51.9% | 43.0% | 0.163 | 0.088 | 51.1% | – |
| 2025-05 | 155,400 | 50.8% | 58.2% | 44.0% | 0.183 | 0.087 | 51.3% | – |
| 2025-06 | 74,000 | 58.4% | 64.4% | 43.8% | 0.195 | 0.100 | 52.3% | – |

### Symbols (pre-validation)

100 symbols. MCC mean 0.184, median 0.179, 10th percentile 0.159, min 0.130, max 0.296. MCC > 0 for 100.0% of symbols; beats momentum on 100.0%.
Worst: RBLBANK 0.130, BHEL 0.135, CHOLAFIN 0.146, SAMMAANCAP 0.149, NAUKRI 0.152. Best: YESBANK 0.296, ADANIGREEN 0.253, TATAELXSI 0.249, ADANIENSOL 0.242, PAYTM 0.236.

### Symbols (validation)

100 symbols. MCC mean 0.149, median 0.151, 10th percentile 0.117, min 0.078, max 0.194. MCC > 0 for 100.0% of symbols; beats momentum on 100.0%.
Worst: PAYTM 0.078, RBLBANK 0.099, NATIONALUM 0.101, SHRIRAMFIN 0.104, BHEL 0.107. Best: ADANIPOWER 0.194, TCS 0.188, ITC 0.187, ASIANPAINT 0.184, TATAELXSI 0.181.

### Cost sensitivity (validation, per UP/DOWN call over the label horizon)

| Min P(direction) | Calls | Share of rows | Hit rate | Gross bp | Net @2bp | Net @5bp | Net @10bp | Net @20bp | Break-even bp |
|---|---|---|---|---|---|---|---|---|---|
| 0.00 | 592,295 | 53.8% | 50.7% | 0.54 | -1.46 | -4.46 | -9.46 | -19.46 | 0.54 |
| 0.40 | 376,250 | 34.2% | 51.0% | 0.66 | -1.34 | -4.34 | -9.34 | -19.34 | 0.66 |
| 0.45 | 179,638 | 16.3% | 51.4% | 0.99 | -1.01 | -4.01 | -9.01 | -19.01 | 0.99 |
| 0.50 | 55,792 | 5.1% | 51.9% | 1.75 | -0.25 | -3.25 | -8.25 | -18.25 | 1.75 |
## Findings

- **Most of the skill is "will it move", not "which way".** On y_1m_5bp validation:
  - Move-vs-no-move MCC is 0.27.
  - Among rows that moved by more than 5 bp and got an UP/DOWN call, the direction is right 55.8% of
    the time. Over all UP/DOWN calls, sign accuracy is 51.5%.
  - On y_5m_10bp the same figures are 0.26, 52.2% and 50.7%.
- **The edge is broad, not concentrated in a few places.** Every one of the 100 stocks has positive MCC
  and beats momentum, in validation and pre-validation alike. MCC varies only a little across:
  - market trend (validation MCC 0.18–0.21 on 1m);
  - market volatility (0.19–0.20);
  - inferred sectors (0.16–0.21).
- **Weak spots:**
  - The first 30 minutes after the open: MCC 0.04 (1m) and 0.02 (5m), at or below momentum.
  - Within a stock-volatility tercile, MCC drops to 0.05–0.13. Much of the full-sample MCC comes from
    telling quiet stocks and times apart from active ones.
- **The edge has been slowly shrinking over time.** On 1m, fold MCC goes 0.241 (F1, 2023) → 0.235 →
  0.210 → 0.205 → 0.194 (validation, 2024-11..2025-06); 5m shows the same pattern. Validation months
  themselves range from 0.16 to 0.21 with no further decline inside validation. Per-stock MCC mean is
  0.175 on validation vs 0.199 on pre-validation.
- **Costs remove the edge.** For each UP/DOWN call held over the horizon:
  - y_1m_5bp makes 0.8 bp gross on average, or 1.9 bp when P(direction) ≥ 0.50 (5% of rows).
  - y_5m_10bp makes 0.5 bp, or 1.8 bp at the same filter.
  - Break-even is below 2 bp round trip. Realistic NSE intraday costs (brokerage, STT, exchange fees,
    slippage) are well above that, so every tested cost level of 2 bp or more is net negative.
- Success gate: NOT VERIFIED. Test period not used.
