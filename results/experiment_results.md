# Synthetic-data detector comparison

Seeds: [1, 2, 3, 4, 5]; contamination=0.05; chronological 60/40 split. Mean +/- std over seeds. **Synthetic data only.**

| Detector | precision | recall | f1 | roc_auc | pr_auc | novel_scenario_recall |
|---|---|---|---|---|---|---|
| level_baseline | 0.702 +/- 0.017 | 0.593 +/- 0.000 | 0.643 +/- 0.007 | 0.787 +/- 0.001 | 0.443 +/- 0.010 | 0.812 +/- 0.000 |
| isolation_forest | 0.356 +/- 0.044 | 0.343 +/- 0.047 | 0.348 +/- 0.043 | 0.797 +/- 0.011 | 0.253 +/- 0.020 | 0.244 +/- 0.122 |
| isolation_forest (normal-only) | 0.000 +/- 0.000 | 0.000 +/- 0.000 | 0.000 +/- 0.000 | 0.248 +/- 0.029 | 0.043 +/- 0.002 | 0.000 +/- 0.000 |
| pca_reconstruction | 0.561 +/- 0.049 | 0.629 +/- 0.000 | 0.592 +/- 0.027 | 0.972 +/- 0.004 | 0.704 +/- 0.027 | 1.000 +/- 0.000 |
| pca_reconstruction (normal-only) | 0.568 +/- 0.038 | 1.000 +/- 0.000 | 0.723 +/- 0.031 | 0.998 +/- 0.001 | 0.959 +/- 0.019 | 1.000 +/- 0.000 |
| logistic_regression | 0.951 +/- 0.013 | 0.996 +/- 0.007 | 0.973 +/- 0.009 | 1.000 +/- 0.000 | 0.999 +/- 0.002 | 0.994 +/- 0.013 |
