# zinro-game

人狼ログ(zinro.net 形式)から「議論のそれっぽさ」を学び、将来 AI 参加者に組み込むための土台。

## 方針

- モデルの重みは学習しない。厳選したログを読み、知識ファイルに書き出して、あとでプロンプトに載せる。
- 学習結果は `knowledge/` のファイル。ログを足すたびに更新する。
- 口調(方言や口癖)は真似しない。標準語・です/ます調で、会話の型・論理の運び・語彙を学ぶ。

## 構成

| パス | 内容 | git |
|---|---|---|
| `logs/raw/<id>.txt` | 貼り付けた生ログ | 管理外 |
| `logs/normalized/<id>.json` | 時系列に直し、名前を A, B, C に置き換えたもの | 管理外 |
| `logs/private/<id>.players.json` | 匿名名と実名の対応 | 管理外 |
| `zinro_learn/` | 取り込み(`parse.py`)と統計(`analyze.py`) | 管理 |
| `knowledge/discussion_style.md` | 議論の型・長さ・語彙と、プロンプト用の要約 | 管理 |
| `knowledge/playbook.md` | 立ち回りの観察 | 管理 |
| `knowledge/examples.jsonl` | 局面ごとの発言例(標準語に言い換えたもの) | 管理 |

生ログと中間ファイルには他のプレイヤーの発言が含まれるので、git には載せない。`knowledge/` には、匿名化して言い換えたものだけを置く。

## 使い方

```
python -m zinro_learn ingest logs/raw/<id>.txt --players "実名1=A,実名2=B,実名3=C" --alias 通称=実名1 --discussion-seconds 300
python -m zinro_learn stats logs/normalized/<id>.json
python -m unittest
```

- ログは新しい発言が上のままで貼ってよい(並びは自動で判定する)。ゲーム開始から勝利の通知まで、「鯖→」の個別通知も含める。
- `--discussion-seconds` は1日あたりの議論時間(延長前の秒数)。指定すると字/分を出せる。延長は、ログの通知から数える。
- 本文中の通称(例: ハンドル名の略称)は `--alias 通称=実名` で匿名化の対象に加える。

## 次にほしいログ

- 役職なしで、制限時間に対する話量が多く、読み違いの少ないもの(型の抽出に向く)
- 役職あり・多人数・複数日のもの(CO、結果報告、護衛の言い回し)
- 人狼が勝ったもの
