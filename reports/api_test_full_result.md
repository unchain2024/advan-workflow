# API E2E テスト結果

- 対象年月: 2026年2月
- 件数: 73

## Phase 1: /api/process-pdf レスポンス vs ground truth

- ✅ PASS: **65/73** (89.0%)
- ❌ FAIL: 1
- 💥 ERROR: 7

## Phase 2: /api/save-billing → DB保存

- 保存成功: 66/73
- 保存失敗: 0

## API レスポンスで FAIL/ERROR となったファイル

### `0202ミスターハリウッド_岡部.pdf` — ERROR

```
HTTP 500: {"detail":{"error":"Unable to get page count.\nSyntax Error: Document stream is empty\n","traceback":"Traceback (most recent call last):\n  File \"/home/ebi/projects/unchain/advan-workflow/venv/lib/python3.14/site-packages/pdf2image/pdf2image.py\", line 602, in pdfinfo_from_path\n    raise ValueErro
```

### `0205高荘・佐藤1枚.pdf` — ERROR

```
HTTP 500: {"detail":{"error":"Unable to get page count.\nSyntax Error: Document stream is empty\n","traceback":"Traceback (most recent call last):\n  File \"/home/ebi/projects/unchain/advan-workflow/venv/lib/python3.14/site-packages/pdf2image/pdf2image.py\", line 602, in pdfinfo_from_path\n    raise ValueErro
```

### `0210バロックmoussy_星野_Part1.pdf` — ERROR

```
HTTP 500: {"detail":{"error":"Unable to get page count.\nSyntax Error: Document stream is empty\n","traceback":"Traceback (most recent call last):\n  File \"/home/ebi/projects/unchain/advan-workflow/venv/lib/python3.14/site-packages/pdf2image/pdf2image.py\", line 602, in pdfinfo_from_path\n    raise ValueErro
```

### `0210バロックmoussyazul_星野_Part1.pdf` — FAIL
- 件数: 抽出 2 / 真 2 (diff   0)
- 数量: 抽出 1498 / 真 1498 (diff   0)
- 金額: 抽出 ¥0 / 真 ¥2,516,640 (diff ¥-2,516,640)

### `0210バロックsly_一和多.pdf` — ERROR

```
HTTP 500: {"detail":{"error":"Unable to get page count.\nSyntax Error: Document stream is empty\n","traceback":"Traceback (most recent call last):\n  File \"/home/ebi/projects/unchain/advan-workflow/venv/lib/python3.14/site-packages/pdf2image/pdf2image.py\", line 602, in pdfinfo_from_path\n    raise ValueErro
```

### `0216アンフィル・佐藤1枚.pdf` — ERROR

```
HTTP 500: {"detail":{"error":"Unable to get page count.\nSyntax Error: Document stream is empty\n","traceback":"Traceback (most recent call last):\n  File \"/home/ebi/projects/unchain/advan-workflow/venv/lib/python3.14/site-packages/pdf2image/pdf2image.py\", line 602, in pdfinfo_from_path\n    raise ValueErro
```

### `0224バロック返品_一和多.pdf` — ERROR

```
HTTP 500: {"detail":{"error":"Unable to get page count.\nSyntax Error: Document stream is empty\n","traceback":"Traceback (most recent call last):\n  File \"/home/ebi/projects/unchain/advan-workflow/venv/lib/python3.14/site-packages/pdf2image/pdf2image.py\", line 602, in pdfinfo_from_path\n    raise ValueErro
```

### `0225バロックstyle_一和多.pdf` — ERROR

```
HTTP 500: {"detail":{"error":"Unable to get page count.\nSyntax Error: Document stream is empty\n","traceback":"Traceback (most recent call last):\n  File \"/home/ebi/projects/unchain/advan-workflow/venv/lib/python3.14/site-packages/pdf2image/pdf2image.py\", line 602, in pdfinfo_from_path\n    raise ValueErro
```

## Phase 3: DB ↔ ground truth 整合性 (2026年2月)

| 取引先 | DBファイル数/真 | DB件数/真 | DB数量/真 | DB金額/真 | 一致 |
|---|---:|---:|---:|---:|:---:|
| (株)SIM | 3/3 | 11/11 | 721/721 | ¥4,689,120/¥4,689,120 | ✅ |
| (株)アダストリア | 6/1 | 28/8 | 272/-9 | ¥2,177,000/¥-24,700 | ❌ |
| (株)アダストリア 神戸DC | 0/4 | 0/14 | 0/274 | ¥0/¥2,012,400 | ❌ |
| (株)アンフィル | 4/5 | 60/61 | 760/761 | ¥5,695,940/¥5,710,940 | ❌ |
| (株)インス | 34/34 | 671/671 | 8542/8542 | ¥42,718,900/¥42,718,900 | ✅ |
| (株)キュー アパレル事業部 | 0/1 | 0/3 | 0/15 | ¥0/¥554,000 | ❌ |
| (株)ジュン アダム・エ・ロペ Femme | 0/2 | 0/6 | 0/204 | ¥0/¥1,550,400 | ❌ |
| (株)バロックジャパンリミテッド | 12/15 | 37/45 | 4891/5118 | ¥8,435,555/¥11,503,431 | ❌ |
| (株)ミスターハリウッド | 2/3 | 20/22 | 967/969 | ¥7,562,300/¥7,582,300 | ❌ |
| (株)高荘 | 1/2 | 9/28 | 66/568 | ¥474,540/¥4,146,760 | ❌ |
| BAROQUE JAPAN LIMITED | 1/2 | 6/7 | -7/-8 | ¥-11,840/¥-14,490 | ❌ |
| アダストリア(株) HARE事業部 | 0/1 | 0/6 | 0/7 | ¥0/¥189,300 | ❌ |

DB整合性: **2/12** 取引先で一致

## 全件サマリ

| ファイル | API状態 | DB状態 | 件数(抽/真) | 数量(抽/真) | 金額(抽/真) |
|---|---|---|---:|---:|---:|
| `0201INS・佐藤1枚(1).pdf` | OK | OK | 8/8 | 8/8 | ¥86,000/¥86,000 |
| `0201INS・佐藤1枚.pdf` | OK | OK | 20/20 | 20/20 | ¥127,960/¥127,960 |
| `0201インス・佐藤1枚.pdf` | OK | OK | 20/20 | 20/20 | ¥83,500/¥83,500 |
| `0201インス・佐藤1枚（2026）.pdf` | OK | OK | 4/4 | 4/4 | ¥10,800/¥10,800 |
| `0201インス・佐藤2枚(1)_Part1.pdf` | OK | OK | 24/24 | 24/24 | ¥132,200/¥132,200 |
| `0201インス・佐藤2枚(1)_Part2.pdf` | OK | OK | 8/8 | 8/8 | ¥43,200/¥43,200 |
| `0201インス・佐藤2枚_Part1.pdf` | OK | OK | 26/26 | 26/26 | ¥123,400/¥123,400 |
| `0201インス・佐藤2枚_Part2.pdf` | OK | OK | 5/5 | 5/5 | ¥17,250/¥17,250 |
| `0202ミスターハリウッド_岡部.pdf` | ERROR |  | 0/2 | 0/2 | ¥0/¥20,000 |
| `0202高荘_岡部.pdf` | OK | OK | 9/9 | 66/66 | ¥474,540/¥474,540 |
| `0204インス_岡部.pdf` | OK | OK | 5/5 | 263/263 | ¥1,478,060/¥1,478,060 |
| `0205インス・佐藤2枚_Part1.pdf` | OK | OK | 30/30 | 394/394 | ¥2,983,820/¥2,983,820 |
| `0205インス・佐藤2枚_Part2.pdf` | OK | OK | 14/14 | 289/289 | ¥2,182,980/¥2,182,980 |
| `0205バロックmoussy_星野_Part1.pdf` | OK | OK | 2/2 | 2/2 | ¥4,080/¥4,080 |
| `0205バロックmoussy_星野_Part2.pdf` | OK | OK | 3/3 | 3/3 | ¥6,585/¥6,585 |
| `0205バロックmoussy_星野_Part3.pdf` | OK | OK | 2/2 | 2/2 | ¥4,600/¥4,600 |
| `0205バロックsly_一和多.pdf` | OK | OK | 2/2 | 2/2 | ¥4,900/¥4,900 |
| `0205高荘・佐藤1枚.pdf` | ERROR |  | 0/19 | 0/502 | ¥0/¥3,672,220 |
| `0206アンフィル・佐藤2枚_Part1.pdf` | OK | OK | 18/18 | 304/304 | ¥2,584,000/¥2,584,000 |
| `0206アンフィル・佐藤2枚_Part2.pdf` | OK | OK | 12/12 | 97/97 | ¥659,600/¥659,600 |
| `0209JUN納前_原田.pdf` | OK | OK | 2/2 | 2/2 | ¥15,200/¥15,200 |
| `0209SIM・佐藤1枚.pdf` | OK | OK | 2/2 | -2/-2 | ¥-11,080/¥-11,080 |
| `0210キュー_岡部.pdf` | OK | OK | 3/3 | 15/15 | ¥554,000/¥554,000 |
| `0210バロックmoussy_星野_Part1.pdf` | ERROR |  | 0/3 | 0/3 | ¥0/¥2,286 |
| `0210バロックmoussy_星野_Part2.pdf` | OK | OK | 1/1 | 1/1 | ¥870/¥870 |
| `0210バロックmoussyazul_星野_Part1.pdf` | FAIL | OK | 2/2 | 1498/1498 | ¥0/¥2,516,640 |
| `0210バロックmoussyazul_星野_Part2.pdf` | OK | OK | 9/9 | 782/782 | ¥2,424,200/¥2,424,200 |
| `0210バロックsly_一和多.pdf` | ERROR |  | 0/3 | 0/3 | ¥0/¥7,500 |
| `0212インス・佐藤1枚（返品）.pdf` | OK | OK | 2/2 | -2/-2 | ¥-12,880/¥-12,880 |
| `0213SIM・佐藤1枚.pdf` | OK | OK | 8/8 | 724/724 | ¥4,706,000/¥4,706,000 |
| `0213インス・佐藤1枚（2026）.pdf` | OK | OK | 4/4 | 4/4 | ¥11,920/¥11,920 |
| `0213ミスターハリウッド_岡部.pdf` | OK | OK | 12/12 | 661/661 | ¥5,313,200/¥5,313,200 |
| `0213ミスターハリウッド・佐藤1枚.pdf` | OK | OK | 8/8 | 306/306 | ¥2,249,100/¥2,249,100 |
| `0216アンフィル・佐藤1枚.pdf` | ERROR |  | 0/1 | 0/1 | ¥0/¥15,000 |
| `0216アンフィル・佐藤2枚_Part1.pdf` | OK | OK | 18/18 | 297/297 | ¥1,906,740/¥1,906,740 |
| `0216アンフィル・佐藤2枚_Part2.pdf` | OK | OK | 12/12 | 62/62 | ¥545,600/¥545,600 |
| `0217インス・佐藤21枚_Part1.pdf` | OK | OK | 24/24 | 156/156 | ¥772,200/¥772,200 |
| `0217インス・佐藤21枚_Part10.pdf` | OK | OK | 25/25 | 974/974 | ¥3,085,800/¥3,085,800 |
| `0217インス・佐藤21枚_Part11.pdf` | OK | OK | 28/28 | 180/180 | ¥1,576,800/¥1,576,800 |
| `0217インス・佐藤21枚_Part12.pdf` | OK | OK | 28/28 | 180/180 | ¥1,622,100/¥1,622,100 |
| `0217インス・佐藤21枚_Part13.pdf` | OK | OK | 16/16 | 218/218 | ¥1,515,100/¥1,515,100 |
| `0217インス・佐藤21枚_Part14.pdf` | OK | OK | 16/16 | 160/160 | ¥868,800/¥868,800 |
| `0217インス・佐藤21枚_Part15.pdf` | OK | OK | 16/16 | 24/24 | ¥134,400/¥134,400 |
| `0217インス・佐藤21枚_Part16.pdf` | OK | OK | 16/16 | 100/100 | ¥560,000/¥560,000 |
| `0217インス・佐藤21枚_Part17.pdf` | OK | OK | 23/23 | 216/216 | ¥1,123,200/¥1,123,200 |
| `0217インス・佐藤21枚_Part18.pdf` | OK | OK | 18/18 | 353/353 | ¥1,941,500/¥1,941,500 |
| `0217インス・佐藤21枚_Part19.pdf` | OK | OK | 22/22 | 34/34 | ¥187,000/¥187,000 |
| `0217インス・佐藤21枚_Part20.pdf` | OK | OK | 28/28 | 242/242 | ¥1,336,400/¥1,336,400 |
| `0217インス・佐藤21枚_Part21.pdf` | OK | OK | 24/24 | 911/911 | ¥4,878,000/¥4,878,000 |
| `0217インス・佐藤21枚_Part2@.pdf` | OK | OK | 26/26 | 247/247 | ¥1,004,600/¥1,004,600 |
| `0217インス・佐藤21枚_Part3.pdf` | OK | OK | 28/28 | 612/612 | ¥2,136,000/¥2,136,000 |
| `0217インス・佐藤21枚_Part4@.pdf` | OK | OK | 26/26 | 355/355 | ¥1,258,150/¥1,258,150 |
| `0217インス・佐藤21枚_Part5.pdf` | OK | OK | 24/24 | 250/250 | ¥1,262,500/¥1,262,500 |
| `0217インス・佐藤21枚_Part6@.pdf` | OK | OK | 28/28 | 281/281 | ¥1,573,600/¥1,573,600 |
| `0217インス・佐藤21枚_Part7.pdf` | OK | OK | 28/28 | 936/936 | ¥3,837,600/¥3,837,600 |
| `0217インス・佐藤21枚_Part8.pdf` | OK | OK | 27/27 | 252/252 | ¥1,265,740/¥1,265,740 |
| `0217インス・佐藤21枚_Part9.pdf` | OK | OK | 30/30 | 798/798 | ¥3,511,200/¥3,511,200 |
| `0218アダストリア岡部@6100.pdf` | OK | OK | 4/4 | 97/97 | ¥591,700/¥591,700 |
| `0218アダストリア岡部@8600.pdf` | OK | OK | 6/6 | 107/107 | ¥920,200/¥920,200 |
| `0220アダストリア岡部2@7150.pdf` | OK | OK | 2/2 | 35/35 | ¥250,250/¥250,250 |
| `0220アダストリア岡部@7150.pdf` | OK | OK | 2/2 | 35/35 | ¥250,250/¥250,250 |
| `0220アダストリア返品_岡部原田.pdf` | OK | OK | 8/8 | -9/-9 | ¥-24,700/¥-24,700 |
| `0224バロック返品_一和多.pdf` | ERROR |  | 0/1 | 0/-1 | ¥0/¥-2,650 |
| `0224バロック返品_星野.pdf` | OK | OK | 6/6 | -7/-7 | ¥-11,840/¥-11,840 |
| `0225バロックmoussy_星野_Part1.pdf` | OK | OK | 2/2 | 674/674 | ¥1,374,960/¥1,374,960 |
| `0225バロックmoussy_星野_Part2.pdf` | OK | OK | 3/3 | 648/648 | ¥1,422,360/¥1,422,360 |
| `0225バロックmoussy_星野_Part3.pdf` | OK | OK | 2/2 | 628/628 | ¥1,444,400/¥1,444,400 |
| `0225バロックsly_一和多.pdf` | OK | OK | 3/3 | 305/305 | ¥762,500/¥762,500 |
| `0225バロックsly_一和多2.pdf` | OK | OK | 6/6 | 346/346 | ¥986,100/¥986,100 |
| `0225バロックstyle_一和多.pdf` | ERROR |  | 0/2 | 0/221 | ¥0/¥541,450 |
| `0226SIM佐藤1枚.pdf` | OK | OK | 1/1 | -1/-1 | ¥-5,800/¥-5,800 |
| `0227JUN_原田.pdf` | OK | OK | 4/4 | 202/202 | ¥1,535,200/¥1,535,200 |
| `0227アダストリアHARE_岡部.pdf` | OK | OK | 6/6 | 7/7 | ¥189,300/¥189,300 |
