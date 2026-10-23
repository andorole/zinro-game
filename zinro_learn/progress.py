"""進行の比較: 占いロラ・グレランなどの進行ごとに、村の勝率を見積もる(試算)。

盤面(board.py)の世界の重みから、役職の割り当てを無作為に引く。そのうえで、村の進行(吊り方)と、狼の噛み方を決めて、
勝敗が付くまで日と夜を動かし、村が勝つ割合を数える。11A のメモ(`knowledge/prob_11a.md` の 2-3)と同じ型の、読みゼロの進行を比べる。

村の進行(毎日1人を吊る。霊能の結果は、翌朝に霊能が生きていれば出る):
- グレー: 毎日、名乗っていない人(灰)から無作為に吊る。灰がいなければ、占いの名乗りを吊る。
- 占いロラ: 占いの名乗りを、狼の見込みが高い順に吊る。ただし、いちばん狼の見込みが低い人(本物と見る人)は残す。そのあと灰。
- 黒スト: 占いの名乗りを同じ順に吊り、霊能の結果が黒(人狼)になったら、灰に切り替える。白が続くうちは、占いを吊る。
  最後の1人は、ほかの名乗りの全員が白と分かった(その人は人狼と決まる)ときだけ吊る。霊能の結果が出ないときは、最後の1人を残す。
- ロラ完遂: 占いの名乗りを、本物と見る人も含めて、すべて吊る。そのあと灰。
どの進行も、結果で黒を出された人(黒先)を、いちばん先に吊る(先黒吊り。標準)。black_first が偽なら、占い吊り優先: 占いを吊る進行は、
占いの名乗りを先に吊り、黒先は占いを吊り終えてから吊る(依頼者の言う「進行提示」の、黒吊りと占いロラの違い)。

狼の噛み方(毎晩1人):
- 灰: 灰(名乗っていない人)から無作為に噛む。11A のメモの基本の前提。依頼者によると、実際は灰は噛まれない(次の名乗り)。
- 名乗り: 狼でない占い・霊能の名乗りを先に噛む(狼は、本物と狂人を見分けられないので、区別しない)。いなければ灰。
  依頼者の話「狼が噛むのは、占いか霊能。どちらかで固定されているとは、占いか霊能の各候補以外は噛まれない、という意味」と同じ形。標準。
  ただし、名乗りを1人噛んだあとは、LEAVE_CLAIMANT の割合で、残りの名乗りを噛まずに灰を噛む(依頼者: 夜2は占いか霊能のどちらかを噛むが、
  夜3に噛まなかった方を噛むとは限らない。どちらかが噛めた場合は、どちらかを残す方が寧ろ多い。仮)。夜1は初日犠牲者(ダミー)を噛む日(依頼者の数え方)。
- どの噛み方でも、名乗った狩人は、HUNTER_BITE の割合で、先に噛みに来る(依頼者: もちろん噛みに行く)。

狩人の護衛(毎晩1人。狼がその人を噛もうとしたら、噛みは失敗する。狩人が生きているあいだだけ):
- なし: 護衛を入れない。
- 霊能: 霊能を護衛しつづける(霊護衛固定)。
- 黒出し: 結果で黒を出した占いの名乗りを護衛しつづける(黒出し占い護衛固定)。
- 環境: 初手で黒が出ていれば、黒を出した占いを護衛する。なければ、真目の占いか霊能(依頼者。霊能を先にする。真目の占いは、狼の見込みが
  いちばん低い名乗り)。守る相手が死んでいたら、次の候補を守る。
- どちらか(either): 真目の占いか霊能のどちらかを、毎晩無作為に護衛する(依頼者: 護衛するのもどちらかでいい)。

占いの夜の結果(2日目以降。seer_results が真のとき):
- 占いの名乗りで生きている人は、毎晩1人を占い、翌朝、生きていれば結果を出す(夜に噛まれた占いは、結果を出せない)。相手は、灰から無作為。
- 本物は正しい色を出す。偽の人狼は、仲間に白を出し(身内切りは、戦術として強くないので、しない)、人狼でない人には、黒を出す
  重み FAKE_BLACK_LATER(白を出す場合を 1)で出す。偽の狂人は、相手が何であっても、同じ重みで黒を出す。
  依頼者の話「偽の二手目は、だいたい白」に合わせて、FAKE_BLACK_LATER は、初手の FAKE_BLACK_FIRST より小さい(仮)。
- 偽の人狼は、初手や次手で、仲間を囲う(仲間に白を出す)のが基本(依頼者の話)。次手(夜1の結果)では、灰の仲間の人狼がいれば、
  ENCLOSE_NEXT の割合で、その仲間に白を出す(仮)。初手の囲いは、盤面の重みには入れていない。
- 村は、「本物と見る占い」(狼の見込みがいちばん低い名乗り)の結果だけを信じる。黒は黒先として吊り、白を貰った人は、灰の無作為の吊りから外す。
  ほかの占いの結果は使わない。本物と見る占いが、実は偽なら、村はその嘘の結果に従う。

猫又(cat。依頼者の説明):
- 吊られたら、生存者(自分以外)からランダムに1人を道連れにする。人狼を連れていく(人狼道連れ)こともあれば、村を連れていく(村道連れ)こともある。
  だから村は、本物の猫又を吊りたくない。
- 噛まれたら、人狼のうちランダムに1人を道連れにする(人狼online仕様)。よみ鯖仕様は「噛んだ人狼」。噛む人が毎晩ランダムなら、同じ。
- off: 猫又の力を数えない(最初の試算)。hidden: 猫又は名乗らず、灰にいる(吊りと噛みの道連れが起きる)。
  open: 猫又が名乗って、村は吊らず、狼は噛まない(ほかに候補があるあいだ)。ただし、人狼2人で夜に6人のときは、
  OPEN_CAT_BITE の割合で、猫又を噛む(噛めば一気に最終日に行ける。依頼者の話。人狼が1人(LW)のときは、絶対に噛めない)。
  ランダムな道連れと、猫の対抗(人狼や狂人の偽の猫)が出ることがあるので、最近はあまり噛まない、とのこと(仮に 2割)。
  counter: 猫又が名乗り、COUNTER_CAT の割合で、対抗の猫(偽の猫)が出る。対抗は、名乗っていない人狼(COUNTER_CAT_WOLF の割合)か狂人。
  いまの環境では、猫COに対抗猫が出たら猫吊りが基本(依頼者。占いへの対抗黒と同じ型で、環境上確率が高い盤面を想定した吊り)。
  猫が2人名乗っていると、村は猫を吊る: 黒を出された方(黒先)。なければ、先に出た方(FAKE_CAT_FIRST の割合で、先に出たのが偽)。
  吊った猫が本物なら、道連れが起きる(依頼者: 道連れが起きたらほぼ負け)。道連れが起きなければ、偽を吊れたと分かるので、
  残る猫は本物として吊らない(放置)。本物が先に死んで偽が残ったら、その偽を、黒先のあとに吊る。
  gidra: 猫又は隠れていて、昼1に出るのは、黒を刺されたとき(必ず出る)と、吊りを指定されたとき(単体で名乗る=ギドラ。狩人は出ない)だけ
  (依頼者)。黒を刺された猫は、進行が先黒吊りなら必ず出る(伏せたまま吊られることはない)。名乗っても、黒先として吊られる(貫通される)。人狼側は猫を
  確定させたくないので、対抗猫がほぼ出る(COUNTER_CAT_BLACK)。占いロラ進行になったときは、猫が伏せることがあると聞いたが、まだ入れていない
  (いまの環境では、先黒吊りになる可能性が高い)。black_first が偽(占い吊り優先)のときは、黒を刺された猫が CAT_HIDE_SEERS_FIRST の割合で伏せる(仮)。
  伏せた猫は、黒先として吊られる番になったら、そこで名乗る。指定されて出た猫の対抗猫は、COUNTER_CAT で、あとから出る。
  指定されて出た猫に対抗猫が出なければ、村は吊り先を選び直す(猫は確定して放置)。出れば猫吊りで、先に出た本物を吊る形になる。
  偽の猫が、真猫より先に自分から出ることもある(FAKE_CAT_PROACTIVE の割合で、試合の初めから出ている)。そのときは、真猫が対抗として露出し、
  先に出た偽の猫を吊る形になる。先に出たのが偽の割合は、この2つの流れの比で決まる(依頼者の「6割くらい」に近づくように置いた)。
  この動きは、依頼者の言う炙り(偽の猫として扱われると分かっていながら猫COをして、対抗を出す。指定されたときなどの足掻き)に近いが、
  指定された人外が出る、という結びつきは入れていない。対抗伏せ貫通(猫COを偽と割り切って、対抗を出さずに吊る)は、いまはやっていないので、
  対抗が出ない猫は吊らない(依頼者)。

白ランオン(盤面 board.random_white。依頼者: 10A狩・11A は、人狼online の、基本的に初日に白が出る環境でやる):
- 本物の占い師の初日の結果は、人狼でない人への無作為な白だけ。だから、初日に黒を出した占いは、その場で偽と分かる(村は先に吊る。霊能の報告を待たない)。
  環境の護衛は、その偽を守らない。初日に貰った白は、本物と見る占いのものだけ信じて、灰の無作為の吊りから外す(ランオフの12A猫でも同じ)。

狩人の狩CO(ギドラ。hunter。依頼者の説明):
- off: 狩人は名乗らない(指定されたら、そのまま吊られる)。
- gidra: 吊りを指定された本物の狩人は、狩COをして吊りを避ける。その割合は、10A狩・11A では 1(依頼者: 当然狩COする。ギドラはない。盤面の hunter_co)。
  12A猫では GIDRA_HUNTER(依頼者: 本指定のタイミングで、狩もギドラCOをする。ただし「狩人も指定されたらギドラの場合あり」で、いつもではない。割合は仮)。
  名乗らなかった狩人は、そのまま吊られる。
  そのほかに、狩人は、指定される前にも出る。依頼者の答え: 出る場面は「指定されたらか、グレーが狭まったら詰む時か、黒を出された時。多分この位」。
  - 黒を出された時: 黒を出した占い(まだ偽と分かっていない)がいれば、朝のうちに名乗る(HUNTER_BLACK_CO)。名乗った狩人は、黒先でも吊られない
    (狩貫通は初手にはしない)。偽の狩人が出ていない単独のCOなら、黒は嘘と分かり、黒を出した占いは偽(reads のとき)。
  - グレーが狭まったら詰む時: 自分が灰から抜けると、灰を端から吊れば最悪の並びでも村が勝つ(灰詰めが成り立つ)とき、名乗る(HUNTER_NARROW_CO)。
    「詰む」の読み(灰詰めが成り立つ)は、私の読みで、確認したい。
  - 護衛が成功した(GJ)あとの昼にも露出することがある(HUNTER_GJ_CO。依頼者が前に言った「GJがあった時も露出する事ある」。ただし、最新の答えは
    「基本的には指示されたら」なので、割合は小さい。仮)。
  - 自発(hunter_day): 指定されなくても、昼 N の朝に出る形。標準では使わない。出るタイミングの比較のためにある(依頼者: 出るタイミングで、どこが有効で、
    どこがギドラの方が良くて、どこでは指定されない限り潜伏をするべきかを知りたい)。
  - 場面は hunter_scenes で選べる(指定・黒・詰み・GJ。既定は全部)。指定を外すと、指定されても出ない(吊られる)。
  狩人が出た朝が、GJの朝(前の夜にGJがあった)なら、狩人は護衛先を明かす: 護衛先は、狼が噛みに来た人なので人狼でなく、村は無作為の吊りから外す。
  狩COした狩人(偽の狩人COがない gidra のとき)は、盤面では狩人に決まった人として数える。
  村は、名乗った人を除いて、吊り先を選び直す。名乗った狩人は、ほかに候補があるあいだ吊られない(狩COを偽と割り切って吊る「狩貫通」は、
  初手にはしない、と聞いた。後の日の狩貫通は、いまは入れていない)。名乗っている狩人(人狼でない)は、狼が HUNTER_BITE の割合で噛みに来る(依頼者: もちろん噛みに行く)。
  2人の狩人が名乗ったら、偽目の方を吊る(依頼者: これも大体は発言から。HUNTER_PAIR_READ の割合で偽を吊り、残りは本物を吊ってしまう)。
  即吊りでなく、一旦放置することもある(HUNTER_PAIR_WAIT の割合で、その日は2人とも吊らない)。
- fake: gidra に加えて、黒なしで昼1に指定された人狼・狂人が、FAKE_HUNTER_FIRST の割合で、偽の狩人COで吊りを避ける(依頼者: 初手の回避は
  狩が良いことがある。狩貫通は初手にはしない)。本物の狩人は、HUNTER_COUNTER の割合で、対抗として出る(依頼者: 本物の狩人も対抗COする)。対抗が出れば、指定された(先に出た)
  偽を吊る。出なければ、偽の狩人は吊られずに残り、村は吊り先を選び直す。人外が偽の狩人を名乗るのは、昼1の最初の指定だけ(後の日は入れていない)。

同数のときの票(PP・RPP。依頼者の説明。rpp が真のとき):
- 人外側(人狼と狂人)の人数が、村(人外側でない人)の人数以上になると、人外側が同じ村人1人に票を入れる。人数が上回れば、必ず通る(PP)。
  同数なら、村が人外側の1人にまとまっても同数で、抽選になる(RPP。「同数なら抽選」の部屋の決まり)。村は、人外側の1人(だれが狂人かは
  分からないので、無作為。村が黒と信じている人が人外側にいれば、その人)にまとまる、と置く。半々で、人外側が選んだ村人が吊られるか、
  村が選んだ人外側の1人が吊られる。
  人狼3・狂人1・村4(昼2。真猫を吊って道連れが村に当たった形)では、村の勝ちは 1/32(約 3%)になる(依頼者: ほぼ負け)。
- 人外側に狂人がいないと、人数が同数以上の時点で人狼の勝ちなので、この操作は起きない。

標準(`python -m zinro_learn progress` と、知識メモの表): 護衛 env、猫又 gidra、狩人 gidra、同数の票あり。関数の既定は、護衛なし・猫又 hidden・狩人 off・同数の票あり
(試験と、11A のメモとの比較のため。呼ぶ側が選ぶ)。

入れていないもの(大きなもの): 2-2 での猫の出方(霊能2人の盤面が未対応)、黒なしで指定された人外の偽の狩人COと炙りのうち、炙り
(偽の狩人COは hunter が fake で選べる。依頼者: 狩貫通は初手にはしないので、偽の狩人COは初手の回避に通りやすい)、狩人が最初から狩COする形、3日目の猫CO、票が割れること、発言からの村の読み
(霊能の報告からの読みは reads で入れた)。
狂人は、人間として数える。人狼が人間と同数以上になれば、人狼の勝ち。人狼が全滅すれば、村の勝ち。
"""
from __future__ import annotations

import random
from bisect import bisect
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from itertools import accumulate

from .board import FAKE_BLACK_LATER, Board, World, enumerate_worlds, marginals, narrowing_wins, pattern_label

ENCLOSE_NEXT = 0.5               # 仮。偽の人狼が、次手(夜1の結果)で、灰の仲間に白を出す(囲う)割合
OPEN_CAT_BITE = 0.2              # 仮。名乗っている猫又を、人狼2人・夜に6人のときに、狼が噛む割合(依頼者: たまに噛む。最近はあまり噛まない)
COUNTER_CAT = 0.7                # 依頼者の話(その割合でよい。対抗猫はまあまあ出る)。猫又が名乗ったあと、対抗の猫(偽の猫)が出る割合
COUNTER_CAT_WOLF = 0.7           # 依頼者の話(その割合でよい)。対抗の猫が人狼の割合(残りは狂人。人狼 : 狂人 = 7 : 3)
FAKE_CAT_FIRST = 0.6             # 仮。counter で、猫が2人名乗ったとき、先に出た方が偽の割合。依頼者: 黒がなければ、どちらかといえば先に出た方を吊る
FAKE_CAT_PROACTIVE = 0.15        # 仮。gidra で、偽の猫が、真猫より先に自分から出ている割合(依頼者の「先に出たのが偽は6割くらい」に近づくように置いた。占いロラで 0.66。炙りに近い動きだが、指定との結びつきは入れていない)
COUNTER_CAT_BLACK = 0.9           # 仮。黒を刺された猫が名乗ると、人狼側は猫を確定させたくないので、対抗猫がほぼ出る(依頼者: 対抗が出て、真猫が貫通されるのが基本)
CAT_HIDE_SEERS_FIRST = 0.5        # 仮。占い吊り優先の進行(黒先を吊らない)のとき、黒を刺された猫が伏せる割合(依頼者: 伏せる可能性がある。噛まれないので、出てもよいとも思う)
GIDRA_CAT = 1.0                  # 依頼者の話(指定されてのギドラは推奨。指示役が単体で出してほしいと言えば、単体で出る)。指定された猫が名乗る割合
GIDRA_HUNTER = 0.7               # 仮。12A猫で、指定された狩人が名乗る割合(依頼者: 本指定のタイミングで、狩もギドラCOをする。ただし「狩人も指定されたらギドラの場合あり」で、いつもではない)。
                                 # 10A狩・11A は、盤面 board.hunter_co(1。依頼者: 当然狩COする。ギドラはない)が優先
FAKE_HUNTER_FIRST = 0.5          # 仮。fake で、黒なしで昼1に指定された人狼・狂人が、偽の狩人COで吊りを避ける割合(依頼者: 初手の回避は狩が良いことがある。狩貫通は初手にはしない。かなり悩ましい)
HUNTER_COUNTER = 1.0             # 依頼者の話(本物の狩人も対抗COする)。偽の狩人が出たとき、本物の狩人が対抗として出る割合
HUNTER_BITE = 1.0                # 依頼者の話(もちろん噛みに行く)。名乗っている狩人(人狼でない)を、狼が噛みに来る割合
HUNTER_BLACK_CO = 1.0            # 仮。黒を出された本物の狩人が、朝のうちに狩COする割合(依頼者: 狩人が出るのは、指定されたら・グレーが狭まって詰む時・黒を出された時。多分この位)
HUNTER_NARROW_CO = 1.0           # 仮。自分が灰から抜けると灰詰めが成り立つ(グレーが狭まって詰む)とき、本物の狩人が狩COする割合(「詰む」の読みは確認したい)
HUNTER_GJ_CO = 0.1               # 仮。護衛が成功した(GJ)あとの昼に、本物の狩人が狩COして露出する割合(依頼者: GJがあった時も露出する事ある。ただし最新の答えは「基本的には指示されたら」)
LEAVE_CLAIMANT = 0.6             # 仮。名乗りを1人噛んだあと、残りの名乗りを噛まずに灰を噛む割合(依頼者: 夜3に噛まなかった方を噛むとは限らない。どちらかを残す方が寧ろ多い)
HUNTER_PAIR_WAIT = 0.3           # 仮。狩人が2人名乗ったとき、その日は吊らずに放置する割合(依頼者: 即吊りでなく、一旦放置する進行を取る場合もある)
HUNTER_PAIR_READ = 0.7           # 仮。狩人が2人名乗ったとき、偽の方を吊る割合(依頼者: 偽目を吊る。これも大体は発言から。残りは、本物を吊ってしまう)
HUNTERS = ("off", "gidra", "fake")
HUNTER_SCENES = ("指定", "黒", "詰み", "GJ")             # 狩人が狩COする場面(hunter_scenes の選択肢。既定は全部)。指定=吊りを指定された、黒=黒を出された、詰み=自分が灰から抜けると灰詰めが成り立つ、GJ=護衛が成功したあと
HUNTER_NAME = {"off": "狩人は名乗らない", "gidra": "狩人は指定されたら(12A猫は場合あり)・黒を出されたら・グレーが狭まって詰むときに名乗る",
               "fake": "狩人は上のとおり名乗り、人外も昼1の指定で偽の狩人を名乗る"}
CATS = ("off", "hidden", "open", "counter", "gidra")
CAT_NAME = {"off": "猫又の力なし", "hidden": "猫又は隠れている", "open": "猫又は名乗っている", "counter": "猫又は名乗り、対抗猫が出る",
            "gidra": "猫又は隠れていて、黒を刺されたら・指定されたら名乗る"}
POLICIES = ("grey", "roll_keep", "roll_stop", "roll")
POSTERIOR = "posterior"                                  # 尤度吊り: 毎日、公開された情報に合う世界を数え直して、人狼の見込みがいちばん高い人を吊る(盤面だけの読み)
ALL_POLICIES = (*POLICIES, POSTERIOR)
POLICY_NAME = {"grey": "グレー", "roll_keep": "占いロラ", "roll_stop": "黒スト", "roll": "ロラ完遂", POSTERIOR: "尤度吊り"}
BITES = ("grey", "claim")                                # 灰を噛む=11A のメモの前提(実際と違う)、名乗りを噛む=占い・霊能の名乗りを無作為に噛む(依頼者: 占いか霊能の各候補以外は噛まれない。標準)
BITE_NAME = {"grey": "灰を噛む", "claim": "名乗りを噛む"}
GUARDS = (None, "medium", "blacksayer", "env", "either")
GUARD_NAME = {None: "護衛なし", "medium": "霊護衛固定", "blacksayer": "黒出し占い護衛固定", "env": "環境の護衛", "either": "占いか霊能のどちらかを護衛(無作為)"}


@dataclass
class Prepared:
    board: Board
    worlds: list[World]
    cumulative: list[float]
    free: list[str]                      # 灰(役職を個別に決めていない人)
    wolf_prob: dict[str, float]          # 人ごとの、人狼である見込み(世界の重みによる)
    seers: list[str]
    medium: str | None
    labels: list[str]                    # 世界ごとの、占いの名乗りの種類の組み合わせ(例: 真狼狂)


def prepare(board: Board) -> Prepared:
    mediums = board.claimants("霊能者")
    if len(mediums) > 1:
        raise ValueError("霊能の名乗りが2人以上の盤面は、まだ扱わない")
    worlds = enumerate_worlds(board)
    if not worlds:
        raise ValueError("この盤面に合う世界がない")
    keys = set(board.key_players())
    free = [p for p in board.players if p not in keys]
    marg = marginals(board, worlds)
    return Prepared(
        board=board,
        worlds=worlds,
        cumulative=list(accumulate(w.weight for w in worlds)),
        free=free,
        wolf_prob={p: marg[p].get("人狼", 0.0) for p in board.players},
        seers=board.claimants("占い師"),
        medium=mediums[0] if mediums else None,
        labels=[pattern_label(board, w.assign).split("-")[0] for w in worlds],
    )


def sample_world(prep: Prepared, rng: random.Random) -> tuple[dict[str, str], str]:
    """世界の重みに比例して1つ引き、灰に残りの役職を無作為に配る。(全員の役職, 占いの名乗りの種類の組み合わせ)"""
    i = bisect(prep.cumulative, rng.random() * prep.cumulative[-1])
    world = prep.worlds[min(i, len(prep.worlds) - 1)]
    roles = dict(world.assign)
    rest = [role for role, n in world.left.items() for _ in range(n)]
    rng.shuffle(rest)
    roles.update(zip(prep.free, rest))
    return roles, prep.labels[min(i, len(prep.worlds) - 1)]


def night_result(seer_role: str, target_role: str, rng: random.Random) -> str:
    """占いの名乗りが、夜に出す結果の色。本物は正しい色。偽の人狼は仲間に白、人狼でない人には黒を一定の重みで。偽の狂人は相手によらない。"""
    if seer_role == "占い師":
        return "黒" if target_role == "人狼" else "白"
    if seer_role == "人狼" and target_role == "人狼":
        return "白"
    black = FAKE_BLACK_LATER / (1 + FAKE_BLACK_LATER)        # 黒:白 = FAKE_BLACK_LATER : 1 の割合
    return "黒" if rng.random() < black else "白"


def pick_fake_cat(roles: dict[str, str], alive: set[str], claimants: set[str], rng: random.Random) -> str | None:
    """偽の猫になる人: 占いを名乗っていない人狼(COUNTER_CAT_WOLF の割合)か狂人。いなければ None。"""
    free = [p for p in sorted(alive) if p not in claimants]
    wolves = [p for p in free if roles[p] == "人狼"]
    mads = [p for p in free if roles[p] == "狂人"]
    pool = (wolves if rng.random() < COUNTER_CAT_WOLF else mads) or wolves or mads
    return rng.choice(pool) if pool else None


def counter_cat(roles: dict[str, str], alive: set[str], claimants: set[str], rng: random.Random) -> tuple[str | None, bool]:
    """名乗った猫又に対抗して出る偽の猫と、その人が先に出たか。(名乗りでない人狼か狂人から。出ないときは (None, False))"""
    if rng.random() >= COUNTER_CAT:
        return None, False
    fake = pick_fake_cat(roles, alive, claimants, rng)
    if fake is None:
        return None, False
    return fake, rng.random() < FAKE_CAT_FIRST


def play(prep: Prepared, roles: dict[str, str], policy: str, bite: str, rng: random.Random, trace: list | None = None,
         guard: str | None = None, seer_results: bool = True, cat: str = "hidden", rpp: bool = True, black_first: bool = True,
         reads: bool = True, hunter: str = "off", observer: Callable | None = None, hunter_scenes: tuple[str, ...] | None = None,
         hunter_day: int = 0) -> bool:
    """1回の試合を動かす。村が勝てば True。trace があれば、(種類, 人, 色) の出来事を足す。
    observer があれば、毎朝、吊りを決めるときに observer(日, 公開された盤面, 合う世界, 人ごとの人狼の見込み, 吊り先) を呼ぶ(昼2・昼3・昼4の盤面を見る)。
    尤度吊り(policy が posterior)は、毎朝この盤面から、人狼の見込みがいちばん高い人を吊る(黒を出された人や偽と分かった占いも、見込みで決まる)。
    black_first が偽なら、占い吊り優先: 占いを吊る進行は、黒を出された人(黒先)より、占いの名乗りを先に吊る(黒先は、占いを吊り終えてから)。
    reads が真なら、村は霊能の報告で占いを読む(偽と分かった占いを先に吊る。結果は信じない。黒を当てた占いを、本物と見る)。
    hunter は、狩人の狩CO(ギドラ)(off=名乗らない、gidra=指定された本物の狩人が名乗る、fake=人外も昼1の指定で偽の狩人を名乗る)。
    hunter_scenes は、本物の狩人が名乗る場面(HUNTER_SCENES のうち。None なら全部)。hunter_day が 1 以上なら、指定されなくても、昼 hunter_day の朝に名乗る(自発)。"""
    if cat not in CATS:
        raise ValueError(f"知らない猫又の扱い: {cat}")
    if hunter not in HUNTERS:
        raise ValueError(f"知らない狩人の扱い: {hunter}")
    scenes = HUNTER_SCENES if hunter_scenes is None else tuple(hunter_scenes)
    for scene in scenes:
        if scene not in HUNTER_SCENES:
            raise ValueError(f"知らない狩人の場面: {scene}")
    if hunter_day < 0:
        raise ValueError("hunter_day は 0 以上")
    board = prep.board
    hunter_co = GIDRA_HUNTER if board.hunter_co is None else board.hunter_co        # 指定された狩人が狩COする割合(10A狩・11A は 1)
    black_sayer = next((r["player"] for r in board.results if r["kind"] == "占い" and r["color"] == "黒"), None)
    if board.random_white:
        black_sayer = None                                # 白ランオン: 初日の黒を出した占いは偽と分かるので、環境の護衛は守らない
    if guard not in GUARDS:
        raise ValueError(f"知らない護衛: {guard}")
    guarded = {None: None, "medium": prep.medium, "blacksayer": black_sayer, "env": None, "either": None}[guard]
    if bite not in BITES:
        raise ValueError(f"知らない噛み方: {bite}")
    claimants = set(prep.seers) | ({prep.medium} if prep.medium else set())
    alive = set(board.players)
    for p in board.dead:                                  # 盤面にすでにある死者
        alive.discard(p)
    real_cat = next((p for p in sorted(alive) if roles[p] == "猫又"), None)
    revealed = cat in ("open", "counter") and real_cat is not None        # 真猫が名乗っているか(gidra は、出る条件を満たすまで隠れている)
    fake_cat, fake_first, fake_out = None, False, False   # 偽の猫、先に出たのが偽か、偽の猫が名乗っているか
    if cat == "counter" and real_cat is not None:
        fake_cat, fake_first = counter_cat(roles, alive, claimants, rng)
        fake_out = fake_cat is not None
    elif cat == "gidra" and real_cat is not None and rng.random() < FAKE_CAT_PROACTIVE:
        fake_cat = pick_fake_cat(roles, alive, claimants, rng)             # 偽の猫が、真猫より先に自分から出ている
        fake_first = fake_out = fake_cat is not None
        if fake_out and trace is not None:
            trace.append(("fakecat", fake_cat, "先に出る"))
    cat_hides = cat == "gidra" and not black_first and real_cat is not None and rng.random() < CAT_HIDE_SEERS_FIRST       # 占い吊り優先のとき、黒を刺された猫が伏せるか
    real_hunter = next((p for p in sorted(alive) if roles[p] == "狩人"), None)
    hunter_out: list[str] = []                            # 狩人を名乗っている人(名乗った順。本物と、人外の偽)
    blacks = sorted({r["target"] for r in board.results if r["color"] == "黒" and r["target"] in alive}, key=lambda p: -prep.wolf_prob[p])
    public = [(r["player"], r["target"], r["color"]) for r in board.results if r["kind"] == "占い" and r["player"] in prep.seers]   # 公開された占いの結果
    black_src: dict[str, str] = {}                        # 黒を出された人 → 黒を出した占い(偽と分かったら、その黒は信じない)
    for sr, t, c in public:
        if c == "黒":
            black_src.setdefault(t, sr)
    safe_src: dict[str, str] = {}
    refuted: set[str] = set()                             # 霊能の報告と食い違う結果を出して、偽と分かった占い
    order = sorted(prep.seers, key=lambda p: (-prep.wolf_prob[p], rng.random()))
    kept = order[-1] if order else None                   # 本物と見る占い(狼の見込みがいちばん低い名乗り)
    colors: dict[str, str] = {}                           # 霊能が報告した、吊られた人の色(公開)
    unreported: list[str] = []
    divined: dict[str, set[str]] = {s: {r["target"] for r in board.results if r["kind"] == "占い" and r["player"] == s} for s in prep.seers}      # 初日の結果で占った相手は、占い直さない
    night = 0
    gj_last = False                                       # 前の夜に、護衛が成功した(GJ)
    gj_morning = False                                    # 今朝が、GJの朝(前の夜に護衛が成功した)。狩人が出れば、護衛先を明かす
    gj_target = None                                      # そのときの護衛先
    claim_bitten = False                                  # 名乗り(占い・霊能の候補)が、夜の襲撃で死んだことがある
    gj_public: list[str] = []                             # 狩人が露出して、GJの護衛先が公開された人
    exec_order: list[str] = []                            # 吊られた人(公開)
    bitten_order: list[str] = []                          # 夜の襲撃で死んだ人(公開)
    other_dead: list[str] = []                            # 道連れで死んだ人(公開)
    night_public: list[dict] = []                         # 夜に出て、公開された占いの結果
    reports: list[tuple[str, str, str]] = []              # 夜に出た結果(占い, 相手, 色)。翌朝、占いが生きていれば出る
    safe: set[str] = set()                                # 本物と見る占いに白を出された人
    if board.random_white:
        refuted = {sr for sr, t, c in public if c == "黒"}          # 白ランオン: 本物の初日の結果は白だけ。黒を出した占いは、その場で偽と分かる
        blacks = [b for b in blacks if black_src.get(b) not in refuted]
    for sr, t, c in public:
        if c == "白":                                      # 初日に貰った白(白ランオンでは、どの占いも出す)
            safe_src.setdefault(t, sr)
            if sr == kept and sr not in refuted:
                safe.add(t)

    def public_board() -> Board:
        """いまの公開された情報の盤面(名乗り・結果・霊能の報告・吊り・夜の死亡)。実際の役職は使わない。"""
        results = [dict(r) for r in board.results] + [dict(r) for r in night_public]
        if prep.medium is not None:
            results += [{"kind": "霊能", "player": prep.medium, "target": t, "color": colors[t], "first": False} for t in exec_order if t in colors]
        return Board(players=list(board.players), roles=dict(board.roles), claims=list(board.claims), results=results,
                     executed=[*board.executed, *exec_order], bitten=[*board.bitten, *bitten_order], other_dead=[*board.other_dead, *other_dead],
                     wolf_co=list(board.wolf_co), ongoing=True, rco=board.rco, random_white=board.random_white,
                     fake_black_first=board.fake_black_first, fake_black_later=FAKE_BLACK_LATER, hunter_co=board.hunter_co,
                     pinned=({real_hunter: "狩人"} if hunter == "gidra" and real_hunter in hunter_out else {}), gj=list(gj_public), dummy=board.dummy)

    def look() -> tuple[Board, list[World], dict[str, float]]:
        """公開された盤面と、合う世界と、生きている人ごとの人狼の見込み(重みの割合)。合う世界がなければ、見込みは空。"""
        pb = public_board()
        ws = enumerate_worlds(pb)
        if not ws:
            return pb, ws, {}
        marg = marginals(pb, ws)
        return pb, ws, {p: marg[p].get("人狼", 0.0) for p in pb.alive}

    def counts() -> tuple[int, int]:
        wolves = sum(1 for p in alive if roles[p] == "人狼")
        return wolves, len(alive) - wolves

    def hunter_comes_out(why: str) -> None:
        """本物の狩人が名乗る。GJの朝なら、護衛先を明かす: 狼が噛みに来た人なので人狼でない(村は、無作為の吊りから外す)。"""
        hunter_out.append(real_hunter)
        if trace is not None:
            trace.append(("hunter", real_hunter, why))
        if gj_morning and gj_target is not None and gj_target not in gj_public:
            gj_public.append(gj_target)
            safe.add(gj_target)

    def cats() -> tuple[bool, str | None, set[str]]:
        """(猫が2人名乗っていて決着前か, 偽と分かった猫, 名乗っている猫)。猫又の道連れが起きれば、どちらが本物か分かる。"""
        if cat == "off" or cat == "hidden" or real_cat is None:
            return False, None, set()
        real_out = revealed and real_cat in alive
        fake_alive = fake_out and fake_cat is not None and fake_cat in alive
        exposed = ({real_cat} if real_out else set()) | ({fake_cat} if fake_alive and real_out else set())
        return real_out and fake_alive, (fake_cat if fake_alive and real_cat not in alive else None), exposed

    def reveal(reason: str) -> None:
        """真猫が名乗る。偽の猫がまだ出ていなければ、COUNTER_CAT の割合で、あとから対抗の猫が出る。"""
        nonlocal revealed, fake_cat, fake_first, fake_out
        revealed = True
        if trace is not None:
            trace.append(("cat", real_cat, reason))
        if not fake_out and rng.random() < (COUNTER_CAT_BLACK if reason == "黒" else COUNTER_CAT):
            fake = pick_fake_cat(roles, alive, claimants, rng)
            if fake is not None:
                fake_cat, fake_first, fake_out = fake, False, True
                if trace is not None:
                    trace.append(("fakecat", fake, "あとから出る"))

    def hang(target: str) -> None:
        alive.discard(target)
        unreported.append(target)
        exec_order.append(target)
        if trace is not None:
            trace.append(("hang", target, "人狼" if roles[target] == "人狼" else "人間"))
        if cat != "off" and roles[target] == "猫又" and alive:
            taken = rng.choice(sorted(alive))                             # 吊られた猫又は、生存者からランダムに1人を道連れにする
            alive.discard(taken)
            other_dead.append(taken)
            if trace is not None:
                trace.append(("takealong", taken, "人狼" if roles[taken] == "人狼" else "人間"))

    while True:
        wolves, humans = counts()
        if wolves == 0:
            return True
        if wolves >= humans:
            return False
        if prep.medium in alive and roles[prep.medium] == "霊能者":     # 朝: 霊能が生きていれば、前の吊りの色を報告する(偽の霊能=霊が欠けたときの名乗りの報告は、使えない)
            for t in unreported:
                colors[t] = "黒" if roles[t] == "人狼" else "白"
                if trace is not None:
                    trace.append(("report", t, colors[t]))
        unreported.clear()
        for seer, t, c in reports:                        # 朝: 夜に出た占いの結果。噛まれた占いは出せない
            if seer not in alive:
                continue
            if trace is not None:
                trace.append(("result", seer, t + c))
            public.append((seer, t, c))
            night_public.append({"kind": "占い", "player": seer, "target": t, "color": c, "first": False})
            if seer == kept:                              # 村は、本物と見る占いの結果だけを信じる
                if c == "黒" and t in alive and t not in blacks:
                    blacks.append(t)
                    black_src[t] = seer
                elif c == "白":
                    safe.add(t)
                    safe_src[t] = seer
        reports = []
        gj_morning, gj_last = gj_last, False
        if hunter != "off" and "黒" in scenes and real_hunter in alive and real_hunter not in hunter_out:
            givers = sorted({sr for sr, t, c in public if t == real_hunter and c == "黒" and sr not in refuted})
            if givers and rng.random() < HUNTER_BLACK_CO:
                hunter_comes_out("黒")                                # 黒を出された狩人は、朝のうちに出る(依頼者)
                if reads and len([q for q in hunter_out if q in alive]) == 1:
                    refuted.update(givers)                            # 狩人の単独CO: 黒は嘘と分かる。黒を出した占いは偽
        if reads:
            for sr, t, c in public:
                if sr not in refuted and colors.get(t, c) != c:
                    refuted.add(sr)                       # 霊能の報告と食い違う結果を出した占いは、偽と分かる
                    if trace is not None:
                        trace.append(("refuted", sr, t + c))
            if refuted:
                blacks = [b for b in blacks if black_src.get(b) not in refuted]       # 偽と分かった占いの黒・白は、信じない
                safe = {q for q in safe if safe_src.get(q) not in refuted}
            confirmed = [sr for sr, t, c in public if c == "黒" and colors.get(t) == "黒" and sr not in refuted and sr in alive]
            if kept in refuted or (confirmed and kept not in confirmed):
                choices = confirmed or [q for q in reversed(order) if q in alive and q not in refuted]    # 黒を当てた占いを、本物と見る
                kept = choices[0] if choices else None
        alive_blacks = [p for p in blacks if p in alive and p not in hunter_out]       # 名乗った狩人は、黒先でも吊らない(狩貫通は初手にはしない)
        if cat == "gidra" and real_cat in alive and not revealed:
            if fake_out and fake_cat in alive:
                reveal("対抗")                            # 偽の猫が出ているので、真猫は対抗として露出する(依頼者: 対抗が居たら基本的に露出)
            elif real_cat in alive_blacks and not cat_hides:
                reveal("黒")                              # 黒を刺された猫は、先黒吊りなら必ず出る(依頼者)。占い吊り優先のときは、伏せることがある
        pending, known_fake, exposed = cats()
        if hunter != "off" and real_hunter in alive and real_hunter not in hunter_out:
            why = None
            held_now = (set() if pending else exposed) | set(hunter_out)               # 猫が2人名乗っていれば、どちらかを吊るので、灰から抜けた人に数えない
            greys_now = [q for q in alive if q not in alive_blacks and q not in safe and q not in held_now]       # 灰詰めの数え方(盤面の報告と同じ): 名乗った占い・霊能も、白黒が確定していなければ、灰に数える
            if "詰み" in scenes and real_hunter in greys_now:
                wolves_left = counts()[0]

                def wins_with(greys: int) -> bool:                 # 確定した黒を先に吊り、灰を端から吊ると、最悪の並びでも村が勝つか
                    return narrowing_wins(len(alive), wolves_left, len(alive_blacks), greys)

                if not wins_with(len(greys_now)) and wins_with(len(greys_now) - 1) and rng.random() < HUNTER_NARROW_CO:
                    why = "詰み"                                   # グレーが狭まったら詰む時: 自分が灰から抜けると、灰詰めが成り立つので、出る(依頼者)
            if why is None and "GJ" in scenes and gj_morning and rng.random() < HUNTER_GJ_CO:
                why = "GJ"                                         # 護衛が成功したあとの昼に、露出する(依頼者)
            if why is None and hunter_day and night + 1 >= hunter_day:
                why = "自発"                                       # 指定されなくても、この日の朝に出る(出るタイミングの比較)
            if why:
                hunter_comes_out(why)
        looked = look() if (policy == POSTERIOR or observer is not None) else None
        wolf_p = looked[2] if looked else {}
        if policy == POSTERIOR and wolf_p:
            seers_up = [p for p in order if p in alive]
            if seers_up:
                kept = min(seers_up, key=lambda p: (wolf_p.get(p, 1.0), p))         # 真目の占い(環境の護衛が守る)は、見込みでいちばん人狼らしくない名乗り

        def grey_pool() -> list[str]:
            held = exposed | set(hunter_out)                               # 名乗っている猫又・狩人は、ほかに候補があるあいだ吊らない
            everyone = [p for p in alive if p not in claimants and p not in held] or [p for p in alive if p not in claimants]
            return [p for p in everyone if p not in safe] or everyone      # 白を貰った灰は、無作為の吊りから外す

        alive_seers = [p for p in order if p in alive]
        hanged_seer_colors = [colors.get(p) for p in order if p not in alive]

        def by_policy(greys: list[str]) -> tuple[str | None, bool]:
            """(吊り先, 占いの名乗りを吊るか)。"""
            if policy == "grey":
                return (rng.choice(sorted(greys)) if greys else None), False
            if policy == "roll":
                if alive_seers:
                    return alive_seers[0], True
                return (rng.choice(sorted(greys)) if greys else None), False
            if policy == "roll_keep":
                rolling = [p for p in alive_seers if p != kept]                 # 本物と見る人は残す
                if rolling:
                    return rolling[0], True
                return (rng.choice(sorted(greys)) if greys else None), False
            if policy == "roll_stop":
                others = [p for p in alive_seers if p != kept]
                last_is_wolf = sum(1 for c in hanged_seer_colors if c == "白") == len(order) - 1 and kept in alive_seers
                if "黒" in hanged_seer_colors or not (others or last_is_wolf):
                    if greys:
                        return rng.choice(sorted(greys)), False
                    return (alive_seers[0], True) if alive_seers else (None, False)
                if others:
                    return others[0], True
                return kept, True                                               # ほかの名乗りが全員白なら、最後の1人は人狼と決まる
            if policy == POSTERIOR:
                pool = [p for p in sorted(alive) if p not in exposed and p not in hunter_out] or sorted(alive)       # 名乗っている猫又・狩人は、ほかに候補があるあいだ吊らない
                if not wolf_p:
                    return (rng.choice(sorted(greys)) if greys else None), False                                  # 合う世界がなければ、灰から無作為
                best = max(wolf_p.get(p, 0.0) for p in pool)
                pick = rng.choice([p for p in pool if wolf_p.get(p, 0.0) >= best - 1e-9])                          # 見込みがいちばん高い人(同じなら無作為)
                if trace is not None:
                    trace.append(("pick", pick, f"{wolf_p.get(pick, 0.0) * 100:.0f}%"))
                return pick, pick in claimants
            raise ValueError(f"知らない進行: {policy}")

        def fallback() -> str:
            rest = sorted(alive_seers) or sorted(alive)                         # 候補が尽きたとき: 占い、霊能、残る誰か
            return rng.choice(rest)

        def pair_target(a: str, b: str) -> str | None:
            """狩人が2人名乗っている: 偽目の方を吊る(依頼者: 大体は発言から)。即吊りでなく、一旦放置することもある(None は、今日は吊らない)。"""
            if rng.random() < HUNTER_PAIR_WAIT:
                return None
            real_one, fake_one = (a, b) if roles[a] == "狩人" else (b, a)
            return fake_one if rng.random() < HUNTER_PAIR_READ else real_one

        hunters_up = [p for p in hunter_out if p in alive]
        pair_pick = pair_target(hunters_up[0], hunters_up[1]) if len(hunters_up) >= 2 else None

        target = None
        from_policy = False
        fakes_alive = [p for p in order if p in refuted and p in alive]
        side = sorted(p for p in alive if roles[p] in ("人狼", "狂人"))                 # 人外側(人狼と狂人)
        villagers = sorted(p for p in alive if roles[p] not in ("人狼", "狂人"))
        if rpp and villagers and any(roles[p] == "狂人" for p in side) and len(side) >= len(villagers):
            # PP・RPP: 人外側が同じ村人に票を入れる。上回れば通る。同数なら、村が人外側の1人にまとまっても同数で、抽選
            pick = rng.choice(villagers)
            if len(side) > len(villagers):
                target = pick
                if trace is not None:
                    trace.append(("pp", pick, ""))
            else:
                against = next((p for p in alive_blacks if p in side), None) or rng.choice(side)     # 村は、黒と信じる人が人外側にいればその人
                target = pick if rng.random() < 0.5 else against
                if trace is not None:
                    trace.append(("rpp", pick, against))
        elif fakes_alive and policy != POSTERIOR:
            target = fakes_alive[0]                       # 偽と分かった占い
        elif alive_blacks and black_first and policy != POSTERIOR:
            target = alive_blacks[0]                      # 黒先
        elif known_fake is not None:
            target = known_fake                           # 本物の猫が先に死んで、偽と分かった猫
        elif pending:
            target = fake_cat if fake_first else real_cat # 猫が2人名乗っている: 黒がなければ、先に出た方を吊る(吊った猫の道連れで、本物か分かる)
        elif pair_pick is not None:
            target = pair_pick                            # 狩人が2人名乗っている: 偽目の方を吊る
        else:
            target, from_seer = by_policy(grey_pool())
            if policy == POSTERIOR:
                if target is None:
                    target = fallback()
                from_policy = target not in claimants and target not in alive_blacks          # 見込みで選んだ灰は、指定と同じ(ギドラが出る)。占いの名乗りと黒先は、出ない
            elif alive_blacks and not black_first and not from_seer:
                target = alive_blacks[0]                  # 占い吊り優先: 占いを吊り終えたら、黒先
            else:
                if target is None:
                    target = fallback()
                from_policy = True
        if cat == "gidra" and not from_policy and target == real_cat and not revealed and target in alive_blacks:
            reveal("黒")                                  # 黒先として吊られる猫は、名乗る(必ず出る)。伏せていても、ここで出る
        for _attempt in range(4 if hunter != "off" else 1):       # 名乗って避けた人がいれば、村は吊り先を選び直す(選び直した先も指定なので、また名乗ることがある)
            if not from_policy:
                break
            spared = False
            if cat == "gidra" and target == real_cat and not revealed and rng.random() < GIDRA_CAT:
                # 吊りを指定された猫は、単体で名乗って(ギドラ)、吊りを避ける。対抗猫が出れば猫吊り、出なければ吊り先を選び直す
                reveal("指定")
                pending, known_fake, exposed = cats()
                if pending:
                    target = fake_cat if fake_first else real_cat
                    break
                spared = True
            elif hunter != "off" and "指定" in scenes and target == real_hunter and target not in hunter_out and rng.random() < hunter_co:
                # 吊りを指定された狩人は、ギドラCOをして吊りを避ける(本指定のタイミングで、狩もギドラCOをする)
                earlier = [p for p in hunter_out if p in alive]
                hunter_comes_out("指定")
                if earlier:                                           # 狩人が2人名乗った(偽が先に出ていた): 偽目の方を吊る。一旦放置もある
                    picked = pair_target(earlier[0], target)
                    if picked is not None:
                        target = picked
                        break
                spared = True
            elif (hunter == "fake" and night == 0 and roles[target] in ("人狼", "狂人") and target not in claimants
                  and not hunter_out and rng.random() < FAKE_HUNTER_FIRST):
                # 黒なしで昼1に指定された人狼・狂人は、偽の狩人COで吊りを避ける(狩貫通は初手にはしない)。狩人の名乗りが出たあとは、重ねて名乗らない
                hunter_out.append(target)
                if trace is not None:
                    trace.append(("fakehunter", target, "指定"))
                if real_hunter in alive and rng.random() < HUNTER_COUNTER:
                    hunter_out.append(real_hunter)                    # 本物の狩人が対抗として出る: 偽目の方を吊る。一旦放置もある
                    if trace is not None:
                        trace.append(("hunter", real_hunter, "対抗"))
                    picked = pair_target(target, real_hunter)
                    if picked is not None:
                        target = picked
                        break
                spared = True
            if not spared:
                break
            target, _ = by_policy(grey_pool())
            if target is None:
                target = fallback()
        if observer is not None and looked is not None:
            observer(night + 1, looked[0], looked[1], looked[2], target)
        hang(target)
        wolves, humans = counts()
        if wolves == 0:
            return True
        if wolves >= humans:
            return False
        # 夜: 狼が1人噛む
        _, _, exposed = cats()                            # 名乗っている猫又は、ほかに候補があるあいだ噛まない
        nonwolf = sorted(p for p in alive if roles[p] != "人狼")
        open_nonwolf = [p for p in nonwolf if p not in exposed] or nonwolf
        leave = bite == "claim" and claim_bitten and any(p in claimants for p in open_nonwolf) and rng.random() < LEAVE_CLAIMANT       # 名乗りを1人噛んだあとは、残りの名乗りを残すことが多い(依頼者)
        if bite == "claim" and not leave:
            pool = [p for p in open_nonwolf if p in claimants] or [p for p in open_nonwolf if p not in claimants] or open_nonwolf
        else:
            pool = [p for p in open_nonwolf if p not in claimants] or open_nonwolf
        wolves_now = sum(1 for p in alive if roles[p] == "人狼")
        if exposed & set(nonwolf) and wolves_now == 2 and len(alive) == 6 and rng.random() < OPEN_CAT_BITE:
            pool = sorted(exposed & set(nonwolf))                          # 人狼2人・夜に6人: 猫又を噛めば、一気に最終日に行ける
        if hunter != "off":
            out_nonwolf = sorted(p for p in hunter_out if p in alive and roles[p] != "人狼")      # 狼は、本物の狩人と狂人の偽を見分けられない
            if out_nonwolf and rng.random() < HUNTER_BITE:
                pool = out_nonwolf                                         # 名乗っている狩人を、護衛の前に噛みに来る
        victim = rng.choice(pool)
        if guard == "env":                                # 環境の護衛: 黒を出した占い、なければ霊能、なければ真目の占い(生きている人)
            guarded = next((p for p in (black_sayer, prep.medium, kept) if p is not None and p in alive), None)
        elif guard == "either":                            # 占いか霊能のどちらか(依頼者: 護衛するのもどちらかでいい)。占いは、真目の占い
            options = [p for p in (kept, prep.medium) if p is not None and p in alive]
            guarded = rng.choice(options) if options else None
        if guarded is not None and victim == guarded and any(roles[p] == "狩人" for p in alive):
            gj_last = True
            gj_target = victim
            if trace is not None:
                trace.append(("guard", victim, ""))               # 護衛が成功して、だれも死なない
        else:
            alive.discard(victim)
            bitten_order.append(victim)
            claim_bitten = claim_bitten or victim in claimants
            if trace is not None:
                trace.append(("bite", victim, ""))
            if cat != "off" and roles[victim] == "猫又":
                mates = sorted(p for p in alive if roles[p] == "人狼")
                if mates:
                    taken = rng.choice(mates)                             # 噛まれた猫又は、人狼のうちランダムに1人を道連れにする
                    alive.discard(taken)
                    other_dead.append(taken)
                    if trace is not None:
                        trace.append(("takealong", taken, "人狼"))
        night += 1
        if seer_results:                                          # 夜に、生きている占いの名乗りが占う
            for seer in prep.seers:
                if seer not in alive:
                    continue
                options = [p for p in sorted(alive) if p != seer and p not in divined[seer]]
                options = [p for p in options if p not in claimants] or options
                mates = [p for p in options if roles[p] == "人狼"]
                if night == 1 and roles[seer] == "人狼" and mates and rng.random() < ENCLOSE_NEXT:
                    t = rng.choice(mates)                          # 次手で、灰の仲間を囲う
                    divined[seer].add(t)
                    reports.append((seer, t, "白"))
                elif options:
                    t = rng.choice(options)
                    divined[seer].add(t)
                    reports.append((seer, t, night_result(roles[seer], roles[t], rng)))


def win_rate(board: Board, policy: str, bite: str = "grey", n: int = 20000, seed: int = 1, prep: Prepared | None = None,
             guard: str | None = None, seer_results: bool = True, cat: str = "hidden", rpp: bool = True,
             where: Callable[[dict[str, str]], bool] | None = None, black_first: bool = True, reads: bool = True,
             hunter: str = "off", hunter_scenes: tuple[str, ...] | None = None, hunter_day: int = 0) -> dict:
    """進行 policy・噛み方 bite で n 回動かした、村の勝率。構成(占いの名乗りの種類の組み合わせ)別の割合も返す。
    where があれば、役職の割り当てがその条件を満たす世界だけを数える(例: 黒を出された人が猫又の世界)。"""
    prep = prep or prepare(board)
    world_rng, play_rng = random.Random(seed), random.Random(seed + 1)   # 世界の引きは、進行によらず同じ列にする(比べやすい)
    wins, total = 0, defaultdict(int)
    by_win: dict[str, int] = defaultdict(int)
    done = 0
    for _ in range(n * (200 if where else 1)):
        roles, label = sample_world(prep, world_rng)
        if where is not None and not where(roles):
            continue
        total[label] += 1
        if play(prep, roles, policy, bite, play_rng, guard=guard, seer_results=seer_results, cat=cat, rpp=rpp, black_first=black_first, reads=reads,
                hunter=hunter, hunter_scenes=hunter_scenes, hunter_day=hunter_day):
            wins += 1
            by_win[label] += 1
        done += 1
        if done == n:
            break
    if done == 0:
        raise ValueError("条件に合う世界が引けなかった")
    rate = wins / done
    return {
        "rate": rate,
        "stderr": (rate * (1 - rate) / done) ** 0.5,
        "n": done,
        "by_label": {k: {"share": total[k] / done, "rate": by_win[k] / total[k]} for k in sorted(total, key=lambda k: -total[k])},
    }


def _games(args) -> dict[str, int]:
    """compare_policies の1組分: 世界 i を引き、同じ世界で、どの進行も動かして、村が勝った数を数える。"""
    board, policies, bite, seed, indices, kw = args
    prep = prepare(board)
    wins = dict.fromkeys(policies, 0)
    for i in indices:
        base = seed * 1_000_003 + i
        roles, _ = sample_world(prep, random.Random(base * 2))
        for policy in policies:
            wins[policy] += play(prep, roles, policy, bite, random.Random(base * 2 + 1), **kw)
    return wins


def compare_policies(board: Board, policies=ALL_POLICIES, bite: str = "grey", n: int = 2000, seed: int = 1, workers: int = 1, **kw) -> dict[str, float]:
    """{進行: 村の勝率}。世界 i を、世界の番号ごとの乱数で引き、どの進行も同じ世界で動かす(尤度吊りは遅いので、workers で並べて動かせる)。
    kw は play に渡す(guard・seer_results・cat・rpp・black_first・reads・hunter・hunter_scenes・hunter_day)。"""
    if workers <= 1:
        wins = _games((board, tuple(policies), bite, seed, range(n), kw))
    else:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor

        parts = [range(k, n, workers * 4) for k in range(workers * 4)]
        wins = dict.fromkeys(policies, 0)
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("fork")) as pool:
            for part in pool.map(_games, [(board, tuple(policies), bite, seed, idx, kw) for idx in parts]):
                for policy, w in part.items():
                    wins[policy] += w
    return {policy: wins[policy] / n for policy in policies}


def compare(board: Board, n: int = 20000, seed: int = 1, policies=POLICIES, bites=BITES, guard: str | None = None,
            seer_results: bool = True, cat: str = "hidden", rpp: bool = True, black_first: bool = True, reads: bool = True,
            hunter: str = "off", hunter_scenes: tuple[str, ...] | None = None, hunter_day: int = 0) -> dict:
    """進行 × 噛み方の、村の勝率の表。{(bite, policy): win_rate の結果}。同じ世界の引きで比べる(seed を共通にする)。"""
    prep = prepare(board)
    return {(b, p): win_rate(board, p, b, n, seed, prep, guard, seer_results, cat, rpp, black_first=black_first, reads=reads, hunter=hunter,
                             hunter_scenes=hunter_scenes, hunter_day=hunter_day)
            for b in bites for p in policies}


def hit_rates(board: Board) -> dict:
    """昼1の1本目の吊りで、人狼に当たる見込み: 占いの名乗りの人ごと、灰の1人、霊能。世界の重みによる(厳密)。"""
    prep = prepare(board)
    claimants = set(prep.seers) | ({prep.medium} if prep.medium else set())
    greys = [p for p in board.alive if p not in claimants]
    return {
        "占い": {p: prep.wolf_prob[p] for p in prep.seers},
        "灰": sum(prep.wolf_prob[p] for p in greys) / len(greys) if greys else 0.0,
        "霊能": prep.wolf_prob[prep.medium] if prep.medium else 0.0,
        "灰の人数": len(greys),
    }


def compare_text(board: Board, title: str, n: int = 20000, seed: int = 1, guard: str | None = None, seer_results: bool = True,
                 cat: str = "hidden", rpp: bool = True, black_first: bool = True, reads: bool = True, hunter: str = "off", bites=BITES,
                 hunter_scenes: tuple[str, ...] | None = None, hunter_day: int = 0) -> str:
    table = compare(board, n, seed, bites=bites, guard=guard, seer_results=seer_results, cat=cat, rpp=rpp, black_first=black_first, reads=reads, hunter=hunter,
                    hunter_scenes=hunter_scenes, hunter_day=hunter_day)
    first = next(iter(table.values()))
    labels = list(first["by_label"])                      # 構成の割合の大きい順(どの進行でも、世界の引きは同じ)
    lines = [f"{title}(試算 {n} 回。誤差は ±{max(r['stderr'] for r in table.values()) * 100:.1f}% くらい)"]
    lines.append("構成の割合: " + "、".join(f"{k} {first['by_label'][k]['share'] * 100:.0f}%" for k in labels))
    for bite in bites:
        parts = []
        for policy in POLICIES:
            r = table[(bite, policy)]
            detail = " / ".join(f"{k} {r['by_label'][k]['rate'] * 100:.0f}%" for k in labels[:2])
            parts.append(f"{POLICY_NAME[policy]} {r['rate'] * 100:.1f}%({detail})")
        lines.append(f"  {BITE_NAME[bite]}: " + " | ".join(parts))
    return "\n".join(lines)
