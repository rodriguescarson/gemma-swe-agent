Hidden wall time per submission (UTC). total = submit -> COMPLETE (queue Q + vLLM start S + tasks A + validation V). Brackets from: submit_at.sh 600-s polls (eval/submit_log.txt, eval/arm_sub*_chain.out), the session monitor (10-min polls, 654244a3 transcript), result commits, eval/analysis/out/kaggle_submissions_*.json.
sub14 v12 5min/40/180         submit 10-11 09:41:39  noticed 10-12 19:07:09 (log: Queue time 33.4 h)            total <=33.4 h   0.15
sub15b v12-b1024 5/40/180     submit 10-13 19:44:09  complete (10-14 17:43, 17:53:03]                          total 21.98-22.15 h  0.10
sub16 v0-think 5/40/180       submit 10-14 17:53:03  complete (10-15 13:01, 13:11:11]                          total 19.1-19.3 h   0.10
sub17 v13 5/40/60             submit 10-15 13:11:12  PENDING seen 10-15 20:01, COMPLETE seen 10-16 05:46:15     total 6.8-16.6 h    0.13
sub18 pub024 8/28/240 80turns submit 10-16 19:08:08  complete (10-17 08:39:46, 08:49:46]  RUNTIME error         total 13.5-13.7 h   (Q ~1.5-1.7 h if killed at 12 h)
sub19 pub024 8/28/240         submit 10-17 08:49:48  PENDING 10-17 17:06:11, COMPLETE 10-18 10:40:25 RUNTIME   total 8.3-25.8 h
sub20 v12b 5/40/180           submit 10-18 16:54:04  complete (10-19 08:37:59, 08:47:59]                       total 15.73-15.90 h 0.17
sub21 v12 5/40/180            submit 10-19 08:50:21  complete (10-20 06:13:59, 06:23:59]                       total 21.40-21.56 h 0.13
sub22 v15b 5/40/60            submit 10-20 07:11:22  complete (10-21 00:57:48, 01:07:48]                       total 17.77-17.94 h 0.10
sub23 v12b6 6/40/180          submit 10-21 06:47:34  complete (10-21 22:02:04, 22:12:04]                       total 15.24-15.41 h 0.15
sub24 v12b_e4b                submit 10-23 20:04:45  COMPLETE seen 10-24 11:43:33                               total <=15.7 h      0.06
sub26 v12b_edit6              submit 10-26 13:09:51  complete (10-27 12:25:43, 12:35:44]                       total 23.26-23.43 h 0.13
sub25 v12b_e4b_card           submit 10-27 12:37:55  result commit 10-28 15:14                                  total <=26.6 h      0.08
sub27 v12b_ctx                submit 10-28 22:47:11  result commit 10-30 08:18                                  total <=33.5 h      0.13
Never submitted: pub024_6m (box gate FAIL 25/74, mean 313 s; eval/arm_sub20_chain.out:"sub20 NOT submitted").
