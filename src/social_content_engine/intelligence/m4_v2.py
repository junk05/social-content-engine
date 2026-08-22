"""Deterministic, text-free M4 V2 rhetorical mechanism derivation."""

import hashlib
import json
import re
from typing import Any, Dict, List, Tuple

from social_content_engine.data.repository import Repository

DERIVATION_VERSION = "m4-intelligence-v2.4"
FEATURE_CONTRACT_VERSION = "M4_INTELLIGENCE_FEATURE_V2"
SHORT_FORM_MAX_CHARS = 100
_NUMBER_LIST = re.compile(
    r"(?<![0-9０-９])(?:[0-9０-９]+|[一二三四五六七八九十]+)\s*(?:つ|個|選|項目|理由|ポイント|ステップ)"
)
_BROWSER_DATE_METADATA = re.compile(r"^\d{4}[/-]\d{1,2}[/-]\d{1,2}$")


def _canonical_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _ref(text: str, start: int, end: int) -> Dict[str, Any]:
    return {
        "start": start,
        "end": end,
        "text_sha256": hashlib.sha256(text[start:end].encode("utf-8")).hexdigest(),
    }


def _matches(text: str, patterns: Tuple[str, ...], offset: int = 0) -> List[Dict[str, Any]]:
    evidence = []
    for pattern in patterns:
        start = text.find(pattern)
        if start >= 0:
            evidence.append(_ref(text, offset + start, offset + start + len(pattern)))
    return evidence


def _labels_with_evidence(
    text: str, rules: Tuple[Tuple[str, Tuple[str, ...]], ...], offset: int = 0
) -> Tuple[List[str], Dict[str, List[Dict[str, Any]]]]:
    labels: List[str] = []
    evidence: Dict[str, List[Dict[str, Any]]] = {}
    for label, patterns in rules:
        refs = _matches(text, patterns, offset)
        if refs:
            labels.append(label)
            evidence[label] = refs
    return sorted(labels), evidence


def _number_list_evidence(text: str, offset: int = 0) -> List[Dict[str, Any]]:
    return [
        _ref(text, offset + match.start(), offset + match.end())
        for match in _NUMBER_LIST.finditer(text)
    ]


def _first_line(text: str) -> Tuple[int, str]:
    """Select visible content, skipping only an exact browser date metadata line."""
    for _offset, raw in enumerate(text.splitlines() or [text]):
        value = raw.strip()
        if value and not _BROWSER_DATE_METADATA.fullmatch(value):
            start = text.find(value)
            return start, value
    return 0, ""


def classify_thread_form(
    text: str, internal_open_loop_mechanisms: List[str], *, observed_self_reply: bool
) -> Dict[str, Any]:
    """Classify a post form without treating short text as missing evidence."""
    if observed_self_reply:
        form = "PARENT_TO_SELF_REPLY"
    elif len(text) > SHORT_FORM_MAX_CHARS:
        form = "LONG_FORM"
    elif internal_open_loop_mechanisms:
        form = "OPEN_LOOP_SHORT"
    else:
        form = "STANDALONE_SHORT"
    return {
        "form": form,
        "short_form_max_chars": SHORT_FORM_MAX_CHARS,
        "observed_self_reply_transition": observed_self_reply,
        "relationship_evidence_mode": "OBSERVED" if observed_self_reply else "UNKNOWN",
    }


def build_v2_feature(
    text: str, parent_ending: Dict[str, Any], *, observed_self_reply: bool = False
) -> Dict[str, Any]:
    """Classify normalized text without retaining it in the output feature."""
    line_start, line = _first_line(text)
    line_available = bool(line)
    rhetorical_rules = (
        ("CONTRARIAN_CLAIM", ("逆", "むしろ", "しかし", "でも", "実は違う")),
        ("EXPECTATION_REVERSAL", ("と思った", "のに", "実は")),
        ("WARNING", ("注意", "危険", "やめ", "NG", "失敗")),
        ("CONFESSION", ("私は", "正直", "本音")),
        ("REVELATION", ("実は", "知らなかった", "真実")),
    )
    audience_rules = (
        ("READER_TARGETING", ("あなた", "女性", "男性", "人へ", "方へ")),
        ("IDENTITY_CALLOUT", ("こんな人", "こんな方", "タイプ", "人は")),
        ("EMOTIONAL_VALIDATION", ("つらい", "苦しい", "大丈夫", "わかる", "悩")),
        ("PAIN_PROBLEM_ACTIVATION", ("悩", "不安", "怖", "後悔", "失敗", "苦")),
        ("DESIRED_FUTURE_ACTIVATION", ("幸せ", "叶", "なりたい", "変わ", "手に入")),
        ("AUTHORITY_EXPERIENCE", ("経験", "相談", "年", "学ん", "見てき")),
        ("TABOO_SECRET", ("秘密", "誰にも", "言えない", "本音")),
    )
    continuation_rules = (
        ("CURIOSITY_GAP", ("なぜ", "理由", "実は", "知らない")),
        ("INCOMPLETE_INFORMATION", ("続き", "結論", "ポイント", "理由")),
        ("IMPLIED_BENEFIT", ("できる", "変わる", "叶う", "手に入")),
        ("IMPLIED_THREAT", ("危険", "失敗", "後悔", "やめ")),
        ("URGENCY", ("今すぐ", "今日", "すぐ", "もう")),
        ("SURPRISE", ("実は", "まさか", "意外", "逆")),
    )
    rhetorical, rhetorical_evidence = _labels_with_evidence(line, rhetorical_rules, line_start)
    number_list = _number_list_evidence(line, line_start)
    if number_list:
        rhetorical.append("NUMBER_LIST")
        rhetorical_evidence["NUMBER_LIST"] = number_list
    if line.endswith(("?", "？")):
        rhetorical.append("QUESTION")
        rhetorical_evidence["QUESTION"] = [
            _ref(text, line_start + len(line) - 1, line_start + len(line))
        ]
    if line_available and not rhetorical:
        rhetorical.append("ASSERTION")
        rhetorical_evidence["ASSERTION"] = [_ref(text, line_start, line_start + len(line))]
    audience, audience_evidence = _labels_with_evidence(line, audience_rules, line_start)
    continuation, continuation_evidence = _labels_with_evidence(
        line, continuation_rules, line_start
    )
    if line.endswith(("…", "...", "：", ":")):
        continuation.append("INCOMPLETE_INFORMATION")
        continuation_evidence["INCOMPLETE_INFORMATION"] = [
            _ref(text, line_start + len(line) - 1, line_start + len(line))
        ]
    certainty = "UNKNOWN"
    if _matches(line, ("必ず", "絶対", "間違いない")):
        certainty = "CERTAIN"
    elif _matches(line, ("かも", "と思う", "ことがある", "ような")):
        certainty = "QUALIFIED"
    elif line.endswith(("?", "？", "…", "...")):
        certainty = "AMBIGUOUS"
    body_rules = (
        ("SETUP", ("私は", "ある日", "最初", "以前")),
        ("TENSION", ("悩", "不安", "怖", "後悔", "苦")),
        ("REVERSAL", ("でも", "しかし", "逆", "むしろ")),
        ("EXPLANATION", ("なぜなら", "だから", "なので", "理由")),
        ("ESCALATION", ("もっと", "さらに", "どんどん", "一番")),
        ("VALIDATION", ("大丈夫", "普通", "わかる", "間違って")),
        ("PAYOFF", ("幸せ", "叶", "できる", "変わ")),
        ("TRANSITION", ("まず", "次に", "そして", "今から")),
    )
    body, body_evidence = _labels_with_evidence(text, body_rules)
    if not body:
        body = ["UNKNOWN"]
    actions: List[str] = []
    action_evidence: Dict[str, List[Dict[str, Any]]] = {}
    if "QUESTION" in rhetorical or "CURIOSITY_GAP" in continuation:
        actions.append("CONTINUE_READING")
        action_evidence["CONTINUE_READING"] = (
            rhetorical_evidence.get("QUESTION", []) + continuation_evidence.get("CURIOSITY_GAP", [])
        )
    if "QUESTION" in rhetorical:
        actions.append("REPLY_OR_COMMENT")
        action_evidence["REPLY_OR_COMMENT"] = rhetorical_evidence["QUESTION"]
    if "READER_TARGETING" in audience and "QUESTION" in rhetorical:
        actions.append("SELF_DISCLOSURE_REPLY")
        action_evidence["SELF_DISCLOSURE_REPLY"] = audience_evidence["READER_TARGETING"]
    if "IMPLIED_BENEFIT" in continuation:
        actions.append("SAVE")
        action_evidence["SAVE"] = continuation_evidence["IMPLIED_BENEFIT"]
    actions = sorted(set(actions)) or ["UNKNOWN"]
    internal_open_loop = sorted(
        set(label for label in continuation if label in {"CURIOSITY_GAP", "INCOMPLETE_INFORMATION"})
    )
    thread_form = classify_thread_form(
        text, internal_open_loop, observed_self_reply=observed_self_reply
    )
    return {
        "schema_version": 2,
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "first_line": {
            "availability": "OBSERVED" if line_available else "EMPTY",
            "rhetorical_mechanisms": sorted(set(rhetorical)),
            "audience_tension_mechanisms": audience,
            "continuation_mechanisms": sorted(set(continuation)) or ["NONE"],
            "certainty_level": certainty,
            "evidence_refs": {
                "rhetorical": rhetorical_evidence,
                "audience_tension": audience_evidence,
                "continuation": continuation_evidence,
            },
        },
        "body": {"roles": body, "evidence_refs": body_evidence},
        "ending": {
            "parent_availability": parent_ending["availability"],
            "parent_cliffhanger_technique": parent_ending["cliffhanger_technique"],
            "internal_open_loop_mechanisms": internal_open_loop or ["NONE"],
            "internal_open_loop_evidence": {
                label: continuation_evidence[label] for label in internal_open_loop
            },
        },
        "actions": {
            "hypotheses": actions,
            "evidence_mode": "PSYCHOLOGY_HYPOTHESIS",
            "evidence_refs": action_evidence,
        },
        "thread_form": thread_form,
    }


def derive_m4_v2_instances(repository: Repository, m4_intelligence_run_id: int) -> int:
    """Replay M4 V2 over pinned normalized text without persisting source text."""
    run = repository.connection.execute(
        "SELECT * FROM m4_intelligence_runs WHERE id = ?", (m4_intelligence_run_id,)
    ).fetchone()
    if run is None:
        raise KeyError("M4 intelligence run not found")
    config = json.loads(str(run["config_json"]))
    required = {
        "analyzer_version", "taxonomy_version", "prompt_version", "model_provider",
        "model_name", "model_parameters", "first_line_extractor_version",
        "parent_ending_extractor_version",
    }
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError("M4 V2 intelligence config is incomplete")
    parameters = _canonical_json(config["model_parameters"])
    rows = repository.connection.execute(
        """SELECT analysis_runs.id AS analysis_run_id, analysis_runs.input_sha256,
                  dataset_members.normalized_post_version_id,
                  normalized_post_versions.canonical_payload_json,
                  first_line_features.id AS first_line_feature_id,
                  first_line_features.input_sha256 AS first_line_input_sha256,
                  first_line_features.feature_sha256 AS first_line_feature_sha256,
                  parent_ending_features.id AS parent_ending_feature_id,
                  parent_ending_features.feature_json AS parent_ending_json,
                  parent_ending_features.input_sha256 AS parent_ending_input_sha256,
                  parent_ending_features.feature_sha256 AS parent_ending_feature_sha256,
                  EXISTS(
                    SELECT 1 FROM browser_normalized_bridges
                    JOIN browser_thread_sequence_observations
                      ON browser_thread_sequence_observations.root_browser_post_identity_id =
                         browser_normalized_bridges.browser_post_identity_id
                    WHERE browser_normalized_bridges.normalized_post_version_id =
                          dataset_members.normalized_post_version_id
                      AND browser_thread_sequence_observations.same_author_as_root = 1
                      AND browser_thread_sequence_observations.sequence_position > 0
                  ) AS observed_self_reply
           FROM dataset_members
           JOIN normalized_post_versions
             ON normalized_post_versions.id = dataset_members.normalized_post_version_id
           JOIN analysis_runs
             ON analysis_runs.normalized_post_version_id =
                dataset_members.normalized_post_version_id
           JOIN first_line_features ON first_line_features.analysis_run_row_id = analysis_runs.id
           JOIN parent_ending_features
             ON parent_ending_features.child_analysis_run_row_id = analysis_runs.id
           WHERE dataset_members.dataset_snapshot_id = ? AND analysis_runs.status = 'SUCCEEDED'
             AND analysis_runs.analyzer_version = ? AND analysis_runs.taxonomy_version = ?
             AND analysis_runs.prompt_version = ? AND analysis_runs.model_provider = ?
             AND analysis_runs.model_name = ? AND analysis_runs.model_parameters_json = ?
             AND first_line_features.extractor_version = ?
             AND parent_ending_features.extractor_version = ?
           ORDER BY dataset_members.ordinal, analysis_runs.id""",
        (run["dataset_snapshot_id"], config["analyzer_version"], config["taxonomy_version"],
         config["prompt_version"], config["model_provider"], config["model_name"], parameters,
         config["first_line_extractor_version"], config["parent_ending_extractor_version"]),
    ).fetchall()
    selected: Dict[int, Any] = {}
    for row in rows:
        selected.setdefault(int(row["normalized_post_version_id"]), row)
    for row in selected.values():
        payload = json.loads(str(row["canonical_payload_json"]))
        text = payload.get("text")
        if not isinstance(text, str):
            text = ""
        ending = json.loads(str(row["parent_ending_json"]))
        feature = build_v2_feature(
            text, ending, observed_self_reply=bool(row["observed_self_reply"])
        )
        input_document = {
            "analysis_input_sha256": row["input_sha256"],
            "first_line_input_sha256": row["first_line_input_sha256"],
            "first_line_feature_sha256": row["first_line_feature_sha256"],
            "parent_ending_input_sha256": row["parent_ending_input_sha256"],
            "parent_ending_feature_sha256": row["parent_ending_feature_sha256"],
            "derivation_version": DERIVATION_VERSION,
        }
        repository.persist_m4_intelligence_instance(
            m4_intelligence_run_id=m4_intelligence_run_id,
            normalized_post_version_id=int(row["normalized_post_version_id"]),
            analysis_run_row_id=int(row["analysis_run_id"]),
            first_line_feature_id=int(row["first_line_feature_id"]),
            parent_ending_feature_id=int(row["parent_ending_feature_id"]),
            feature=feature,
            input_sha256=hashlib.sha256(_canonical_json(input_document).encode("utf-8")).hexdigest(),
        )
    return len(selected)
