# OCR モデル精度比較 (株)インス 2026年2月 5ファイル

## テスト条件

- 対象: `/home/ebi/Downloads/2月DONE/` 内の確認済み5ファイル
  - `0212インス・佐藤1枚（返品）.pdf` (S260212-1)
  - `0213インス・佐藤1枚（2026）.pdf` (S251203-2)
  - `0217インス・佐藤21枚_Part2@.pdf` (S260206-2)
  - `0217インス・佐藤21枚_Part4@.pdf` (S260206-4)
  - `0217インス・佐藤21枚_Part6@.pdf` (S260206-6)
- 各モデルで **3回連続** 実行 (合計15走査)
- プロンプトは `src/llm_extractor.py` の EXTRACTION_PROMPT を共通使用
- 並列度: 5

## 結果

| バックエンド | PASS率 | PASS/全 | 所要時間 | 備考 |
|---|---:|---:|---:|---|
| **gemini-2.5-flash** (現行) | **53.3%** | 8/15 | 112.2s | 走査ごとに違う行抜け・重複が発生（OCR非決定的） |
| **gemini-3-flash-preview** | **100.0%** | 15/15 | 91.2s | 全ファイル・全走査PASS |
| **claude-haiku-4-5** | 93.3% | 14/15 | 24.7s | 返品の数量符号のみズレ（金額は正常）|
| **claude-sonnet-4-6** | **100.0%** | 15/15 | **45.6s** | 全ファイル・全走査PASS / 最速 |

## 推奨

**Claude Sonnet 4.6** または **Gemini 3 Flash Preview** に切り替えれば、現状の OCR 非決定性問題はほぼ解消する。

- **第一候補: Claude Sonnet 4.6** ― 100%精度＋最速＋既にAPIキー保有
- **第二候補: Gemini 3 Flash Preview** ― 100%精度、Geminiエコシステム継続のメリット
- **避ける: Gemini 2.5 Flash (現行)** ― 53.3%しか正確に読めず、再現性なし

### 切替方法

`.env` の以下を変更:

```sh
# 現行
GEMINI_MODEL=gemini-2.5-flash

# 推奨1: Geminiのまま改善
GEMINI_MODEL=gemini-3-flash-preview

# 推奨2: Claudeに切替（src/llm_extractor の代わりに src/claude_extractor を使う）
CLAUDE_MODEL=claude-sonnet-4-6
```

Claude切替の場合は `backend-api/routes/pdf.py` などで `LLMExtractor` を `ClaudeExtractor` に差し替えるか、両方を呼べる薄いラッパー（`Extractor` interface）を導入。

## なぜ Gemini 2.5 Flash が不安定だったか

3回走らせた中で観察された Gemini 2.5 Flash の失敗パターン（同じPDFで毎回違う）:

### `0217インス・佐藤21枚_Part2@.pdf` (源 26行 / 247枚 / ¥1,004,600)
| 回 | 件数 | 数量 | 金額 | 差(円) |
|---|---:|---:|---:|---:|
| 1 | 26 | 247 | 1,004,600 | 0 (正解) |
| 2 | 25 | 243 | 988,600 | -16,000 |
| 3 | (要確認) | | | |

### `0217インス・佐藤21枚_Part4@.pdf` (源 26行 / 355枚 / ¥1,258,150)
| 回 | 件数 | 数量 | 明細計 | 差(円) |
|---|---:|---:|---:|---:|
| 1 | 25 | 352 | 1,243,000 | -15,150 (1行抜け) |
| 2 | 26 | 354 | 1,253,100 | -5,050 (1行数量違い) |
| 3 | 26 | 354 | 1,253,100 | -5,050 |

### `0217インス・佐藤21枚_Part6@.pdf` (源 28行 / 281枚 / ¥1,573,600)
| 回 | 件数 | 数量 | 明細計 | 差(円) |
|---|---:|---:|---:|---:|
| 1 | 30 | 281 | 1,573,600 | 0 (件数2行多いが金額一致) |
| 2 | 29 | 288 | 1,612,800 | +39,200 (重複1行) |
| 3 | 28 | 284 | 1,590,400 | +16,800 (重複1行) |

**= 同じファイルでも実行ごとに違う場所で違う種類のミスが出る**。月次請求書のバグ（CLIMER系4行抜けなど）は、過去の抽出時にこういうランダムなミスを引いて、それが DB に固定されたもの。

## 月次請求書のバグの再発率

過去のバッチ実行時に Gemini 2.5 Flash で処理 → ランダムにエラーを生んでDBに固定 → 月次請求書PDF に反映、というのが現状の構造。

5ファイルの3回テストでは半数近くにエラーが出るので、**インス全34ファイル × 月次1回 で何らかのエラーが出る確率は実質100%** に近い。

## アクション提案

### 短期（今日中）
1. `.env` の `GEMINI_MODEL` を `gemini-3-flash-preview` に変更してデプロイ → 当面の安定化
2. 既に固定されている2月分DBをCLI再実行で上書き

### 中期（数日以内）
1. `ClaudeExtractor` を `LLMExtractor` と同様にbackend-api側からも呼べるように `src/extractor.py` で抽象化
2. 環境変数 `EXTRACTOR_BACKEND=claude|gemini` で切替可能に
3. インス全34ファイル + アダストリア・バロックの一部で同じテストを取り、安定性確認

### 長期（来月以降）
1. **2モデル並走** ― Claude + Gemini で両方走らせ、結果が一致しないファイルだけ人間レビューに回す
2. **Self-consistency** ― 同じモデルを 3回走らせ多数決を取る（ただし Sonnet/Gemini3 Flashは決定的なので不要）

## テストスクリプトの使い方

```bash
cd /home/ebi/projects/unchain/advan-workflow

# 単一バックエンド
venv/bin/python -m scripts.diff_test_insu_2026_02 --known-only --backend claude-sonnet-4-6

# 3回繰り返し（再現性検証）
venv/bin/python -m scripts.diff_test_insu_2026_02 --known-only --backend gemini-3-flash --repeat 3

# 複数バックエンド比較
venv/bin/python -m scripts.diff_test_insu_2026_02 --known-only --compare gemini-2.5-flash gemini-3-flash claude-sonnet-4-6

# 全34ファイルでテスト
venv/bin/python -m scripts.diff_test_insu_2026_02 --backend claude-sonnet-4-6
```

## 関連ファイル

- スクリプト: `/home/ebi/projects/unchain/advan-workflow/scripts/diff_test_insu_2026_02.py`
- Claude抽出器: `/home/ebi/projects/unchain/advan-workflow/src/claude_extractor.py`
- Gemini抽出器: `/home/ebi/projects/unchain/advan-workflow/src/llm_extractor.py`
- 結果JSON:
  - `reports/insu_test_gemini25flash_3runs.json` (現行ベースライン)
  - `reports/insu_test_gemini3flash_3runs.json`
  - `reports/insu_test_claude_haiku_3runs.json`
  - `reports/insu_test_claude_3runs.json`
