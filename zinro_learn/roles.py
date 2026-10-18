"""役職まわりの通知・行動・死亡を、イベント列(取り込み後のログ)から読み取る。

ログのファイル(logs/normalized/)には手を入れず、読むたびにイベントから組み立てる。
- 通知(鯖→): 占い結果(「Aさんは人狼です／人狼ではありません」)、霊能結果(「処刑されたAさんは…」)、
  噛みの通知(鯖→人狼「Aさんを噛みます」)。匿名化後の本文は「《A》さん…」になるので、《》は外して読む。
- 夜の行動(「X→GM: 実行@X→Y」): 意味は、実行する人の役職で決まる(占い師=占い、狩人=護衛、人狼=噛み)。
  人狼の噛みは「人狼→GM」の行で出て、実行した人狼は actor に入る。初日夜は自動のランダムの行も同じ形で出る
  (ダミーの行も同じ)ので、初日夜の行が選んだものかランダムかは、ログからは決められない。
- 死亡: 夜に死んだか(襲撃)、投票で死んだか(処刑)。日ごとの生存者も、ここから出す。
- 人狼の夜チャット(kind が wolfchat): 発言ではない。夜ごと・話者ごとに件数と字数を数える。
"""
from __future__ import annotations

import re

from .parse import DUMMY

LABEL = re.compile(r"^《(?P<name>.+)》$")
RESULT_TAIL = r"さんは(?P<result>人狼です|人狼ではありません)$"
DIVINATION = re.compile(rf"^(?P<target>.+?){RESULT_TAIL}")
MEDIUM = re.compile(rf"^処刑された(?P<target>.+?){RESULT_TAIL}")
BITE = re.compile(r"^(?P<target>.+?)さんを噛みます$")

ACT_OF_ROLE = {"占い師": "占い", "狩人": "護衛", "人狼": "噛み"}
CAUSE_OF_PHASE = {"night": "襲撃", "vote": "処刑"}


def plain(name: str) -> str:
    """匿名化後の本文に出る《A》を A に戻す。《》のない名前(ダミーなど)はそのまま。"""
    m = LABEL.match(name)
    return m["name"] if m else name


def notices(game: dict) -> list[dict]:
    """鯖の個別通知のうち、占い結果・霊能結果・噛みの通知。

    kind は 占い／霊能／噛み。to は通知を受ける人(噛みは「人狼」)。wolf は、結果が人狼なら True(噛みは None)。
    """
    found = []
    for e in game["events"]:
        if e["kind"] != "private":
            continue
        text = e["text"]
        if m := MEDIUM.match(text):
            kind, target, wolf = "霊能", m["target"], m["result"] == "人狼です"
        elif m := DIVINATION.match(text):
            kind, target, wolf = "占い", m["target"], m["result"] == "人狼です"
        elif m := BITE.match(text):
            kind, target, wolf = "噛み", m["target"], None
        else:
            continue
        found.append({
            "seq": e["seq"], "phase": e["phase"], "day": e["day"],
            "kind": kind, "to": e["to"], "target": plain(target), "wolf": wolf,
        })
    return found


def night_actions(game: dict) -> list[dict]:
    """夜の行動(「実行@」の行)。act は 占い／護衛／噛み／ダミー／その他(猫又や村人などの行)。

    role は実行した人の役職(噛みは、実行した人狼の役職)。ダミー(初日犠牲者)の行は、役職が村人でも ダミー にする。
    """
    actions = []
    for e in game["events"]:
        if e["kind"] != "command" or e.get("action") != "実行":
            continue
        info = game["players"].get(e["actor"], {})
        role = info.get("role", "?")
        if info.get("dummy") or e["actor"] == DUMMY:
            act = "ダミー"
        else:
            act = ACT_OF_ROLE.get(role, "その他")
        actions.append({
            "seq": e["seq"], "phase": e["phase"], "day": e["day"],
            "actor": e["actor"], "role": role, "act": act, "target": e["target"],
        })
    return actions


def deaths(game: dict) -> list[dict]:
    """死亡の通知(「Aさんが死亡しました」)の順。cause は、夜なら 襲撃、投票なら 処刑。

    day は「迎えた朝の数」。夜0(初日夜)の死亡は 0、昼1の投票の処刑は 1、その夜の襲撃も 1。
    """
    return [
        {
            "seq": e["seq"], "name": e["death"], "phase": e["phase"], "day": e["day"],
            "cause": CAUSE_OF_PHASE.get(e["phase"], "その他"),
        }
        for e in game["events"]
        if "death" in e
    ]


def alive_by_day(game: dict) -> list[dict]:
    """日ごとの、議論が始まる(朝の通知)ときの生存者。day は 1 から。生存者は players の並び順。"""
    died: list[str] = []
    rows = []
    for e in game["events"]:
        if "death" in e:
            died.append(e["death"])
        elif e["kind"] == "system" and "朝になりました" in e["text"]:
            alive = [name for name in game["players"] if name not in died]
            rows.append({"day": e["day"], "alive": alive, "dead": list(died)})
    return rows


def wolves(game: dict) -> list[str]:
    """役職が人狼の人(players の並び順)。"""
    return [name for name, info in game["players"].items() if info["role"] == "人狼"]


def wolf_teams(game: dict) -> list[list[str]]:
    """人狼どうしのまとまり。役職通知の「仲間は【…】です」から、本人と仲間を合わせたものを並べる(仲間のいない1人の人狼は単独)。"""
    teams: list[list[str]] = []
    for name in wolves(game):
        team = sorted({name, *game["players"][name].get("mates", [])})
        if team not in teams:
            teams.append(team)
    return teams


def is_wolfchat(event: dict) -> bool:
    """人狼の夜チャットの行か。wolfchat の種類ができる前に取り込んだログは、同じ行を directed(宛先が人狼)で持つ。"""
    return event["kind"] == "wolfchat" or (event["kind"] == "directed" and event.get("to") == "人狼")


def wolfchat_summary(game: dict) -> dict:
    """人狼の夜チャット(wolfchat)の件数と字数。夜ごと(キーは、その夜の前に迎えた朝の数。初日夜は 0)・話者ごと。

    発言(speech)としては数えない。作戦の中身は、本文(wolfchat のイベント)を読む。
    """
    total = {"messages": 0, "chars": 0, "nights": {}}
    for e in game["events"]:
        if not is_wolfchat(e):
            continue
        size = len(e["text"].replace("\n", ""))
        night = total["nights"].setdefault(e["day"], {"messages": 0, "chars": 0, "speakers": {}})
        who = night["speakers"].setdefault(e["speaker"], {"messages": 0, "chars": 0})
        for row in (total, night, who):
            row["messages"] += 1
            row["chars"] += size
    return total


def format_timeline(game: dict) -> str:
    """役職・夜の行動・通知・死亡・人狼チャットを、夜0・昼1・夜1・昼2…の順に並べた文字列。"""
    lines = [f"game {game['game_id']}: {game.get('winner')} の勝ち / 役職設定 {game.get('setup')}"]
    lines.append("役職: " + " ".join(f"{name}={info['role']}" for name, info in game["players"].items()))
    for team in wolf_teams(game):
        lines.append("人狼のまとまり: " + " ".join(team))
    events = game["events"]
    by_day = {row["day"]: row for row in alive_by_day(game)}
    chat = wolfchat_summary(game)["nights"]
    nights = {e["day"] for e in events if e["phase"] == "night"}
    days = {e["day"] for e in events if e["phase"] in ("day", "vote")}

    def notice_line(n: dict) -> str:
        if n["kind"] == "噛み":
            what = f"{n['target']} を噛む"
        else:
            what = f"{n['target']} は" + ("人狼" if n["wolf"] else "人狼ではない")
        return f"  通知({n['kind']}): {n['to']} に「{what}」"

    for day in sorted(nights | days):
        if day in days:
            alive = by_day.get(day, {}).get("alive", [])
            lines.append(f"昼{day}: 生存 {len(alive)} 人 ({' '.join(alive)})")
            for e in (e for e in events if "votes" in e and e["day"] == day):
                got = {v["player"]: v["received"] for v in e["votes"]}
                lines.append(f"  処刑: {e.get('executed')} ({got.get(e.get('executed'), 0)}票)")
            lines += [notice_line(n) for n in notices(game) if n["day"] == day and n["phase"] in ("day", "vote")]
        if day in nights:
            lines.append(f"夜{day}:")
            for a in (a for a in night_actions(game) if a["day"] == day):
                lines.append(f"  {a['act']}: {a['actor']}({a['role']}) → {a['target']}")
            lines += [notice_line(n) for n in notices(game) if n["day"] == day and n["phase"] == "night"]
            if day in chat:
                c = chat[day]
                speakers = " ".join(f"{who}{s['messages']}件" for who, s in sorted(c["speakers"].items()))
                lines.append(f"  人狼チャット: {c['messages']} 件 / {c['chars']} 字 ({speakers})")
            for d in (d for d in deaths(game) if d["day"] == day and d["phase"] == "night"):
                lines.append(f"  死亡: {d['name']} ({d['cause']})")
    return "\n".join(lines)
