# Labels

`future_return(h) = close[t+h] / close[t] - 1` for h in {1, 5, 15, 30, 60} minutes, where t+h is the
bar stamped exactly h minutes later on the same trade_date. Missing bar or past session end -> null.
Labels never span overnight.

Direction with threshold θ (0.05%, 0.10%, 0.20%, 0.30%, 0.50%): UP if > θ, DOWN if < -θ, else NEUTRAL.
Column name `y_{h}m_{θ in bp}bp`. Also `fprice_h` (future price) for regression.
`label_end_ts_h = ts + h + 1 min` is when the label becomes known; purging uses it.
θ is chosen on validation/walk-forward data only.
