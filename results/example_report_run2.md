# Log analysis report - run 2

- Batch: 2 (sample_batch_2.csv), 4911 records, format csv
- Detector: `pca_reconstruction`; params: `{"contamination": 0.05, "train_fraction": 0.6, "normal_only": false, "gap_seconds": 120, "min_incident_events": 3}`
- Scored: 4911; trained on: 2946; anomalies flagged: 319

## Evaluation
Protocol: chronological split: first 60% fit, rest evaluated.

| precision | recall | F1 | ROC-AUC | PR-AUC | n evaluated | n positive |
|---|---|---|---|---|---|---|
| 0.621 | 0.629 | 0.625 | 0.974 | 0.758 | 1965 | 167 |

## Incidents (heuristic root-cause hints)
- **Group 1 / rank 1** `auth` 2024-03-01T08:08:23.597000+00:00 -> 2024-03-01T08:11:11.796000+00:00 (4 events, unclassified): Isolated anomaly cluster in 'auth' (category hint: unclassified). Dominant pattern: "password reset requested for <ID>". No correlated anomalies in other services.
- **Group 2 / rank 1** `inventory` 2024-03-01T08:14:12.836000+00:00 -> 2024-03-01T08:22:15.694000+00:00 (24 events, resource/memory): Candidate origin: 'inventory' showed the earliest anomalous activity (category hint: resource/memory); dominant pattern "gc pause <NUM>ms heap usage <NUM>%". Later anomalies in: auth, gateway. Heuristic ordering only - verify before acting.
- **Group 2 / rank 2** `auth` 2024-03-01T08:17:03.847000+00:00 -> 2024-03-01T08:18:23.968000+00:00 (3 events, unclassified): Possible downstream effect: 'auth' began 171s after 'inventory' (category hint: unclassified); dominant pattern "password reset requested for <ID>".
- **Group 2 / rank 3** `gateway` 2024-03-01T08:20:00.908000+00:00 -> 2024-03-01T08:22:50.671000+00:00 (8 events, network/timeout): Possible downstream effect: 'gateway' began 348s after 'inventory' (category hint: network/timeout); dominant pattern "upstream inventory connection refused".
- **Group 3 / rank 1** `auth` 2024-03-01T08:30:38.394000+00:00 -> 2024-03-01T08:32:11.415000+00:00 (3 events, unclassified): Isolated anomaly cluster in 'auth' (category hint: unclassified). Dominant pattern: "validation failed for field email on registration of <ID>". No correlated anomalies in other services.
- **Group 4 / rank 1** `db` 2024-03-01T08:37:26.472000+00:00 -> 2024-03-01T08:41:53.692000+00:00 (9 events, database): Candidate origin: 'db' showed the earliest anomalous activity (category hint: database); dominant pattern "slow query detected took <NUM>ms". Later anomalies in: gateway, payment. Heuristic ordering only - verify before acting.
- **Group 4 / rank 2** `payment` 2024-03-01T08:38:05.720000+00:00 -> 2024-03-01T08:42:45.868000+00:00 (18 events, database): Possible downstream effect: 'payment' began 39s after 'db' (category hint: database); dominant pattern "timeout calling db after <NUM>ms payment aborted".
- **Group 4 / rank 3** `gateway` 2024-03-01T08:39:08.673000+00:00 -> 2024-03-01T08:41:19.460000+00:00 (9 events, upstream/dependency): Possible downstream effect: 'gateway' began 102s after 'db' (category hint: upstream/dependency); dominant pattern "upstream payment returned <NUM> service unavailable".
- **Group 5 / rank 1** `auth` 2024-03-01T08:51:39.555000+00:00 -> 2024-03-01T08:55:04.801000+00:00 (3 events, unclassified): Isolated anomaly cluster in 'auth' (category hint: unclassified). Dominant pattern: "password reset requested for <ID>". No correlated anomalies in other services.
- **Group 6 / rank 1** `auth` 2024-03-01T09:00:17.045000+00:00 -> 2024-03-01T09:01:16.900000+00:00 (3 events, unclassified): Candidate origin: 'auth' showed the earliest anomalous activity (category hint: unclassified); dominant pattern "password reset requested for <ID>". Later anomalies in: payment. Heuristic ordering only - verify before acting.
- **Group 6 / rank 2** `payment` 2024-03-01T09:01:47.419000+00:00 -> 2024-03-01T09:02:10.707000+00:00 (3 events, unclassified): Possible downstream effect: 'payment' began 90s after 'auth' (category hint: unclassified); dominant pattern "card declined for payment <UUID> reason=insufficient_funds".
- **Group 7 / rank 1** `payment` 2024-03-01T09:04:53.820000+00:00 -> 2024-03-01T09:07:02.368000+00:00 (4 events, unclassified): Isolated anomaly cluster in 'payment' (category hint: unclassified). Dominant pattern: "card declined for payment <UUID> reason=insufficient_funds". No correlated anomalies in other services.
- **Group 8 / rank 1** `auth` 2024-03-01T09:09:47.320000+00:00 -> 2024-03-01T09:11:07.598000+00:00 (6 events, auth/security): Isolated anomaly cluster in 'auth' (category hint: auth/security). Dominant pattern: "account admin locked after repeated failed login attempts". No correlated anomalies in other services.
- **Group 9 / rank 1** `inventory` 2024-03-01T09:41:49.469000+00:00 -> 2024-03-01T09:43:59.983000+00:00 (3 events, database): Isolated anomaly cluster in 'inventory' (category hint: database). Dominant pattern: "cache miss for <ID> reloading from db". No correlated anomalies in other services.
- **Group 10 / rank 1** `payment` 2024-03-01T09:54:20.500000+00:00 -> 2024-03-01T10:00:21.129000+00:00 (19 events, database): Candidate origin: 'payment' showed the earliest anomalous activity (category hint: database); dominant pattern "timeout calling db after <NUM>ms payment aborted". Later anomalies in: db, gateway. Heuristic ordering only - verify before acting.
- **Group 10 / rank 2** `db` 2024-03-01T09:55:36.386000+00:00 -> 2024-03-01T09:59:53.830000+00:00 (9 events, database): Possible downstream effect: 'db' began 76s after 'payment' (category hint: database); dominant pattern "slow query detected took <NUM>ms".
- **Group 10 / rank 3** `gateway` 2024-03-01T09:56:44.682000+00:00 -> 2024-03-01T10:00:39.156000+00:00 (19 events, upstream/dependency): Possible downstream effect: 'gateway' began 144s after 'payment' (category hint: upstream/dependency); dominant pattern "upstream payment returned <NUM> service unavailable".
- **Group 11 / rank 1** `payment` 2024-03-01T10:08:29.886000+00:00 -> 2024-03-01T10:13:55.351000+00:00 (12 events, database): Candidate origin: 'payment' showed the earliest anomalous activity (category hint: database); dominant pattern "timeout calling db after <NUM>ms payment aborted". Later anomalies in: db. Heuristic ordering only - verify before acting.
- **Group 11 / rank 2** `db` 2024-03-01T10:09:17.704000+00:00 -> 2024-03-01T10:12:46.613000+00:00 (24 events, resource/disk): Possible downstream effect: 'db' began 48s after 'payment' (category hint: resource/disk); dominant pattern "write failed no space left on device /var/lib/db".
- **Group 12 / rank 1** `auth` 2024-03-01T10:21:39.331000+00:00 -> 2024-03-01T10:24:12.710000+00:00 (4 events, unclassified): Candidate origin: 'auth' showed the earliest anomalous activity (category hint: unclassified); dominant pattern "validation failed for field email on registration of <ID>". Later anomalies in: gateway, inventory. Heuristic ordering only - verify before acting.
- **Group 12 / rank 2** `inventory` 2024-03-01T10:21:53.992000+00:00 -> 2024-03-01T10:28:00.401000+00:00 (21 events, resource/memory): Possible downstream effect: 'inventory' began 15s after 'auth' (category hint: resource/memory); dominant pattern "gc pause <NUM>ms heap usage <NUM>%".
- **Group 12 / rank 3** `gateway` 2024-03-01T10:26:19.972000+00:00 -> 2024-03-01T10:27:21.553000+00:00 (7 events, network/timeout): Possible downstream effect: 'gateway' began 281s after 'auth' (category hint: network/timeout); dominant pattern "upstream inventory connection refused".
- **Group 13 / rank 1** `payment` 2024-03-01T10:30:51.903000+00:00 -> 2024-03-01T10:33:43.081000+00:00 (4 events, unclassified): Candidate origin: 'payment' showed the earliest anomalous activity (category hint: unclassified); dominant pattern "card declined for payment <UUID> reason=insufficient_funds". Later anomalies in: auth, gateway. Heuristic ordering only - verify before acting.
- **Group 13 / rank 2** `auth` 2024-03-01T10:34:54.805000+00:00 -> 2024-03-01T10:39:52.078000+00:00 (7 events, auth/security): Possible downstream effect: 'auth' began 243s after 'payment' (category hint: auth/security); dominant pattern "account admin locked after repeated failed login attempts".
- **Group 13 / rank 3** `gateway` 2024-03-01T10:38:59.619000+00:00 -> 2024-03-01T10:41:08.768000+00:00 (3 events, unclassified): Possible downstream effect: 'gateway' began 488s after 'payment' (category hint: unclassified); dominant pattern "retrying request <UUID> attempt <NUM> of <NUM> succeeded".
- **Group 14 / rank 1** `auth` 2024-03-01T10:56:22.440000+00:00 -> 2024-03-01T10:57:59.428000+00:00 (3 events, unclassified): Isolated anomaly cluster in 'auth' (category hint: unclassified). Dominant pattern: "password reset requested for <ID>". No correlated anomalies in other services.

## Top findings
- [WARN] `db` 2024-03-01T10:11:11.358000+00:00 score=1.00: checkpoint failed i/o error on volume  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:on, tfidf:failed, tfidf:checkpoint_
- [WARN] `db` 2024-03-01T10:11:44.356000+00:00 score=1.00: checkpoint failed i/o error on volume  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:on, tfidf:failed, tfidf:checkpoint_
- [WARN] `db` 2024-03-01T10:09:34.291000+00:00 score=1.00: checkpoint failed i/o error on volume  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:on, tfidf:failed, tfidf:checkpoint_
- [WARN] `db` 2024-03-01T10:10:04.633000+00:00 score=1.00: checkpoint failed i/o error on volume  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:on, tfidf:failed, tfidf:checkpoint_
- [WARN] `db` 2024-03-01T10:10:59.196000+00:00 score=1.00: checkpoint failed i/o error on volume  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:on, tfidf:failed, tfidf:checkpoint_
- [WARN] `db` 2024-03-01T10:10:20.247000+00:00 score=1.00: checkpoint failed i/o error on volume  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:on, tfidf:failed, tfidf:checkpoint_
- [ERROR] `db` 2024-03-01T10:11:09.623000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:10:06.063000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:10:20.927000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:10:40.527000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:12:42.038000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:12:46.613000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:12:36.096000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:12:43.711000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:12:18.351000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:12:23.047000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:12:06.952000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:09:17.704000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:09:29.455000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:09:42.587000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:09:39.100000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `db` 2024-03-01T10:09:58.283000+00:00 score=1.00: write failed no space left on device /var/lib/db  
  _pca_reconstruction score 1.00; message pattern never seen in reference data; top evidence: tfidf:space, tfidf:on, tfidf:db_
- [ERROR] `inventory` 2024-03-01T08:21:32.921000+00:00 score=1.00: service restarting after fatal error  
  _pca_reconstruction score 1.00; pattern seen 1x in 2946 reference records; top evidence: tfidf:after, tfidf:service, tfidf:cache_
- [ERROR] `inventory` 2024-03-01T10:26:58.992000+00:00 score=1.00: service restarting after fatal error  
  _pca_reconstruction score 1.00; pattern seen 1x in 2946 reference records; top evidence: tfidf:after, tfidf:service, tfidf:cache_
- [ERROR] `gateway` 2024-03-01T08:20:48.268000+00:00 score=1.00: upstream inventory connection refused  
  _pca_reconstruction score 1.00; pattern seen 6x in 2946 reference records; top evidence: tfidf:connection refused, tfidf:inventory connection, tfidf:inventory_

## History comparison
- Prior runs of this detector: 1
- New anomalous patterns vs history: 0; recurring: 16
