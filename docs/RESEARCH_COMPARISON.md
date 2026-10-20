# Base paper vs. this implementation

> **Honesty statement.** This project is *inspired by* the base paper. It does not reproduce the paper's
> implementation, uses none of its data or code, and makes **no claim of outperforming it**. No comparable
> experiment (same dataset, same split, same metrics) has been run, so no such claim can be made.
> None of the "extensions" below is presented as an original research contribution: each is a standard,
> widely used technique applied in an engineering context.

## 1. The base paper - what is and is not verified

Reference: "Anomaly Detection in Logs Using Deep Learning", IEEE Xplore document 10767232
(https://ieeexplore.ieee.org/document/10767232/).

**Access limitation.** While building this project the IEEE page returned no readable text (JavaScript-rendered)
and the build sandbox had no network access, so the full text could **not** be read. Everything below is
labelled by how well it is supported.

| Item | Status | Source of the statement |
|---|---|---|
| Topic: log anomaly detection with deep learning; keywords anomaly detection, classification, unsupervised learning, deep learning | Partially verified | Index terms/abstract fragment in a ResearchGate listing of "Anomaly Detection in Logs using Deep Learning" (Ayesha et al., IEEE Access 2024, DOI 10.1109/ACCESS.2024.3506332) |
| Proposes a **hybrid** technique combining unsupervised and supervised learning; mentions integrating **autoencoders and self-organising maps (SOMs)** | Partially verified (search-result text fragments only) | Same listing |
| That DOI/listing is the same work as IEEE document 10767232 | **Unconfirmed** (very likely, but the identifier mapping was not checked) | - |
| Datasets used, preprocessing, architecture details, hyper-parameters | **Not verified** | Must be read from the PDF |
| Reported metrics and numeric results | **Not verified - intentionally not quoted** | Must be read from the PDF |
| Limitations stated by the authors | **Not verified** | Must be read from the PDF |

**To complete this section:** read the PDF and fill the "Not verified" rows above with page-level references.
Until then, do not cite any paper-specific number or limitation from this repository.

### General limitations of the deep-learning log-anomaly-detection approach class (not paper-specific)
Independent literature reports, e.g. Le & Zhang, "Log-based Anomaly Detection with Deep Learning: How Far Are We?"
(arXiv:2202.04301), analyse five deep-learning models on four public datasets and conclude the problem is not
solved, examining sensitivity to training-data selection, data grouping, class distribution, noise and early
detection. These are cited as *context for evaluation design*, not as findings about the base paper.

## 2. What this project implements (verified by running the code)

| Area | Implementation | Relation to the paper |
|---|---|---|
| Ingestion | CSV + plain-text parsing, level/service/timestamp normalisation, template masking | Engineering; not from paper |
| Features | TF-IDF (1-2 grams) over masked templates + structured features (level, shape, template rarity, per-service rate) | Classical features; no deep embeddings |
| Detector A | Isolation Forest (unsupervised) | Not in paper (as far as verified) |
| Detector B | **PCA reconstruction error** - a *linear* autoencoder analogue (unsupervised) | Conceptually adjacent to autoencoders; **not** an autoencoder, **not** the paper's model |
| Detector C | Logistic regression (supervised) | Supervised counterpart; **not** a replication of the hybrid pipeline |
| Baseline | Flag every ERROR/FATAL | Sanity floor |
| Explainability | Exact decompositions (PCA residual, logistic terms), z-score heuristic (Isolation Forest), template rarity, nearest-normal example | Engineering extension |
| Incident grouping | Service x time-gap episodes, cross-service merging, rule-based category hints, earliest-activity ordering | Heuristic; not causal inference |
| Persistence/history | SQLite; run-to-run comparison of anomaly rate, new/recurring patterns, recurring incident signatures | Engineering |
| Interfaces | FastAPI REST + Streamlit dashboard | Engineering |

**Not implemented** (so not claimed): autoencoders/SOMs (neural), sequence models (LSTM/Transformer), log-parser
benchmarks (Drain etc.), session/window-based sequence features, semantic embeddings, online/incremental learning.

## 3. Evaluation protocol (as implemented)
* **Labelled data:** only synthetic logs from `logintel/synthetic.py` (seeded, reproducible) - there is no real-world
  or public benchmark data in this repository.
* **Split:** chronological. The first 60% of a batch fits features + detector; metrics use only the remaining 40%
  (never rows used for fitting). Alternatively, fit on a separate reference batch and evaluate on the whole target batch.
* **Novel-failure probe:** the generator places one scenario (`disk_full`) only in the test half, so we can measure
  recall on a failure type the models never saw.
* **Metrics:** precision, recall, F1 at the detector's operating threshold; ROC-AUC and PR-AUC on raw scores; confusion matrix.
  Undefined metrics are `null`, never imputed.
* **Unsupervised thresholding:** top `contamination` fraction of the training-score distribution (default 5%).
  Synthetic anomaly rate is ~5%, so this setting is favourable by construction.
* **Variants:** unsupervised detectors are run both on unlabelled (contaminated) training data and "normal-only".
* **Repetition:** 5 seeds; mean +/- std reported (`results/experiment_results.md`).

### Observed results (synthetic data, seeds 1-5)
See the README for the table. Key caveats: the synthetic templates are cleanly separable and the training half
contains the same scenarios as most of the test half, so the supervised model's near-perfect score is expected and
**is not evidence of real-world performance**. Isolation Forest with normal-only training scored *below chance*
(ROC-AUC 0.25); a plausible (untested here) explanation is that it cannot split on text features that are constant in
the normal-only training data, making novel tokens invisible. Treat as an observed limitation, not a validated diagnosis.

## 4. Remaining limitations
1. Paper details unverified (Section 1); no like-for-like comparison with the paper is possible yet.
2. No evaluation on real or public datasets (e.g. HDFS/BGL from Loghub); synthetic results do not transfer.
3. Independent log lines are scored; no sequence/session context.
4. Dense feature matrices -> practical limit ~100k records per batch.
5. Root-cause output is heuristic (earliest flagged event + keyword categories). On synthetic data the cascade origin
   was not always ranked first (e.g. a downstream `payment` cluster can start before the first *flagged* `db` event).
6. Isolation Forest explanations are a z-score heuristic, not the forest's own attribution.
7. No authentication/authorisation on the API; no PII redaction of stored log messages.
8. Thresholds (`contamination`) are user-set, not calibrated.

## 5. Proposed future work (NOT implemented)
Neural autoencoder / SOM hybrid (to approximate the paper's family once its details are verified); Drain-style parsing;
session-window sequence models; evaluation on public datasets with the protocol in Section 3; calibrated thresholds;
PII masking; auth on the API; trace-ID-based correlation for stronger root-cause evidence.
