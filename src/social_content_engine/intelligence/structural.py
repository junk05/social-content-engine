"""Deterministic, genre-independent structural component extraction for M4."""

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from social_content_engine.data.repository import Repository

TAXONOMY_VERSION = "M4_STRUCTURAL_TAXONOMY_V1"
EXTRACTOR_VERSION = "m4-structural-extractor-v4"
FEATURE_CONTRACT_VERSION = "M4_STRUCTURAL_FEATURE_V1"
_DATE_METADATA = re.compile(r"^\d{4}[/-]\d{1,2}[/-]\d{1,2}$")
_RELATIVE_TIME_METADATA = re.compile(
    r"^(?:\d+\s*(?:分|時間|日|週|ヶ月|か月|月|年|m|min|h|d|w|mo|y)|昨日|一昨日)$",
    re.IGNORECASE,
)

_RULES: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("QUESTION", re.compile(r"[?？]|(?:なぜ|どうして|どんな|何)")),
    ("NEGATION", re.compile(r"(?:ない|ません|ぬ|無(?:し|い)|NG|やめ)")),
    ("NUMBER", re.compile(r"[0-9０-９]+|[一二三四五六七八九十]+")),
    ("LIST_PREVIEW", re.compile(
        r"(?:[0-9０-９]+|[一二三四五六七八九十]+)\s*(?:つ|個|選|項目|理由|ポイント|ステップ)"
    )),
    ("TARGET_READER", re.compile(r"(?:女性|男性|人|方)(?:へ|は|の|に)?")),
    ("DIRECT_ADDRESS", re.compile(r"(?:あなた|皆さん|みんな|君|きみ)")),
    ("EXPERIENCE_STATEMENT", re.compile(r"(?:私|僕|俺|体験|経験|相談)")),
    ("TIME_OR_AGE_REFERENCE", re.compile(
        r"(?:\d+\s*(?:歳|才|年|ヶ月|か月|日)|今日|今(?:日|回)|過去|年後)"
    )),
    ("COMPARISON", re.compile(r"(?:より|ほど|一番|最も|比べ)")),
    ("CONTRAST", re.compile(r"(?:でも|しかし|一方|逆に|むしろ)")),
    ("CONDITION", re.compile(r"(?:なら|たら|場合|とき|すると)")),
    ("PROBLEM_STATEMENT", re.compile(r"(?:悩|不安|失敗|後悔|困|苦)")),
    ("RESULT_STATEMENT", re.compile(r"(?:結果|できる|変わ|なれる|叶)")),
    ("REASON_PREVIEW", re.compile(r"(?:なぜ|理由|なぜなら|だから)")),
    ("CONCLUSION_PREVIEW", re.compile(r"(?:結論|答え|つまり)")),
    ("SECRET_REVEAL", re.compile(r"(?:実は|秘密|本音|真実)")),
    ("INCOMPLETE_INFORMATION", re.compile(r"(?:続き|\.\.\.|…|：|:)")),
    ("CONCRETE_SCENE", re.compile(r"(?:朝|夜|駅|会社|家|部屋|カフェ|電話|LINE)")),
    ("EMOTIONAL_EXPRESSION", re.compile(r"(?:嬉しい|悲しい|つらい|楽しい|怖い|悔しい|大丈夫)")),
    ("ADVICE_OR_COMMAND", re.compile(r"(?:べき|ください|しよう|しなさい|やめて)")),
    ("QUOTE", re.compile(r"[「『][^」』]{1,80}[」』]")),
    ("TRANSITION", re.compile(r"(?:まず|次に|そして|最後に|一方で)")),
    ("CTA", re.compile(r"(?:教えて|コメント|保存|フォロー|シェア|返信)")),
)


def _canonical_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _first_content_line(text: str) -> Tuple[int, str]:
    offset = 0
    for raw in text.splitlines(keepends=True) or [text]:
        line = raw.strip()
        if line and not (_DATE_METADATA.fullmatch(line) or _RELATIVE_TIME_METADATA.fullmatch(line)):
            start = offset + raw.find(line)
            sentence = re.match(r"^.*?[。！？!?]|^.+$", line)
            selected = sentence.group(0).strip() if sentence else line
            return start, selected
        offset += len(raw)
    return 0, ""


def _metadata_ranges(text: str) -> List[Tuple[int, int]]:
    ranges: List[Tuple[int, int]] = []
    offset = 0
    for raw in text.splitlines(keepends=True) or [text]:
        value = raw.strip()
        if value and (_DATE_METADATA.fullmatch(value) or _RELATIVE_TIME_METADATA.fullmatch(value)):
            start = offset + raw.find(value)
            ranges.append((start, start + len(value)))
        offset += len(raw)
    return ranges


def _ref(text: str, start: int, end: int, scope: str) -> Dict[str, Any]:
    return {
        "start": start,
        "end": end,
        "scope": scope,
        "text_sha256": hashlib.sha256(text[start:end].encode("utf-8")).hexdigest(),
    }


def extract_structural_feature(text: str, *, observed_self_reply: bool = False) -> Dict[str, Any]:
    """Return ordered structural components without retaining source wording."""
    line_start, line = _first_content_line(text)
    metadata_ranges = _metadata_ranges(text)
    components: List[Dict[str, Any]] = []
    if line:
        components.append({"component_id": "ASSERTION", **_ref(
            text, line_start, line_start + len(line), "FIRST_LINE"
        )})
    for component_id, pattern in _RULES:
        for match in pattern.finditer(text):
            if any(start <= match.start() and match.end() <= end for start, end in metadata_ranges):
                continue
            scope = "FIRST_LINE" if line_start <= match.start() < line_start + len(line) else "BODY"
            components.append({"component_id": component_id, **_ref(
                text, match.start(), match.end(), scope
            )})
    components.sort(
        key=lambda item: (int(item["start"]), int(item["end"]), str(item["component_id"]))
    )
    first_line = [
        item["component_id"] for item in components if item["scope"] == "FIRST_LINE"
    ]
    post_sequence = [item["component_id"] for item in components]
    return {
        "schema_version": 1,
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "first_line_availability": "OBSERVED" if line else "UNAVAILABLE",
        "components": components,
        "first_line_component_sequence": first_line,
        "post_component_sequence": post_sequence,
        "thread_structure": {
            "observed_self_reply_transition": observed_self_reply,
            "relationship_evidence_mode": "OBSERVED" if observed_self_reply else "UNKNOWN",
        },
    }


def derive_structural_features(repository: Repository, structural_feature_run_id: int) -> int:
    """Derive immutable structural evidence for every pinned snapshot member."""
    run = repository.connection.execute(
        "SELECT * FROM structural_feature_runs WHERE id = ?", (structural_feature_run_id,)
    ).fetchone()
    if run is None:
        raise KeyError("structural feature run not found")
    rows = repository.connection.execute(
        """SELECT dataset_members.normalized_post_version_id,
                  normalized_post_versions.canonical_payload_json,
                  normalized_post_versions.payload_sha256,
                  EXISTS(
                    SELECT 1 FROM browser_normalized_bridges
                    JOIN browser_thread_sequence_observations
                      ON browser_thread_sequence_observations.root_browser_post_identity_id =
                         browser_normalized_bridges.browser_post_identity_id
                    WHERE browser_normalized_bridges.normalized_post_version_id =
                          dataset_members.normalized_post_version_id
                      AND browser_thread_sequence_observations.same_author_as_root = 1
                      AND browser_thread_sequence_observations.sequence_position > 0
                      AND browser_thread_sequence_observations.relationship_evidence =
                          'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'
                  ) AS observed_self_reply
           FROM dataset_members
           JOIN normalized_post_versions
             ON normalized_post_versions.id = dataset_members.normalized_post_version_id
           WHERE dataset_members.dataset_snapshot_id = ?
           ORDER BY dataset_members.ordinal""",
        (run["dataset_snapshot_id"],),
    ).fetchall()
    for row in rows:
        payload = json.loads(str(row["canonical_payload_json"]))
        text = payload.get("text") if isinstance(payload, dict) else ""
        feature = extract_structural_feature(
            text if isinstance(text, str) else "",
            observed_self_reply=bool(row["observed_self_reply"]),
        )
        input_document = {
            "normalized_payload_sha256": str(row["payload_sha256"]),
            "extractor_version": str(run["extractor_version"]),
            "taxonomy_version": str(run["taxonomy_version"]),
        }
        repository.persist_structural_feature_instance(
            structural_feature_run_id=structural_feature_run_id,
            normalized_post_version_id=int(row["normalized_post_version_id"]),
            feature=feature,
            input_sha256=hashlib.sha256(_canonical_json(input_document).encode("utf-8")).hexdigest(),
        )
    return len(rows)


def _candidate_signatures(feature: Dict[str, Any], pattern_kind: str) -> List[Dict[str, Any]]:
    """Produce local atomic and adjacent-component structures, never text signatures."""
    sequence_key = (
        "first_line_component_sequence"
        if pattern_kind == "FIRST_LINE" else "post_component_sequence"
    )
    sequence = [item for item in feature[sequence_key] if item != "ASSERTION"]
    sequence = [item for index, item in enumerate(sequence)
                if index == 0 or item != sequence[index - 1]]
    result: List[Dict[str, Any]] = []
    seen = set()
    for width in (1, 2):
        for start in range(len(sequence) - width + 1):
            candidate = tuple(sequence[start:start + width])
            if candidate and candidate not in seen:
                seen.add(candidate)
                result.append({"component_sequence": list(candidate)})
    if 3 <= len(sequence) <= 12:
        candidate = tuple(sequence)
        if candidate not in seen:
            result.append({"component_sequence": list(candidate)})
    return result


def _thread_node_role(feature: Dict[str, Any], *, is_root: bool) -> str:
    components = {str(item["component_id"]) for item in feature["components"]}
    if is_root:
        return "ROOT_OPEN_LOOP" if "INCOMPLETE_INFORMATION" in components else "ROOT_HOOK"
    if "CTA" in components:
        return "SELF_REPLY_CTA"
    if components.intersection({"RESULT_STATEMENT", "CONCLUSION_PREVIEW"}):
        return "SELF_REPLY_PAYOFF"
    if "REASON_PREVIEW" in components:
        return "SELF_REPLY_EXPLANATION"
    if "CONTRAST" in components:
        return "SELF_REPLY_CONTRAST"
    if "INCOMPLETE_INFORMATION" in components:
        return "SELF_REPLY_OPEN_LOOP"
    return "SELF_REPLY_DEVELOPMENT"


def _observed_thread_signature(
    repository: Repository, normalized_post_version_id: int
) -> List[Dict[str, Any]]:
    required_tables = {
        "browser_normalized_bridges",
        "browser_thread_sequence_observations",
        "browser_observations",
    }
    available_tables = {
        str(row[0]) for row in repository.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if not required_tables.issubset(available_tables):
        return []
    root = repository.connection.execute(
        """SELECT browser_post_identity_id
        FROM browser_normalized_bridges
        WHERE normalized_post_version_id = ?""",
        (normalized_post_version_id,),
    ).fetchone()
    if root is None:
        return []
    detail = repository.connection.execute(
        """SELECT MAX(detail_observation_id) AS detail_observation_id
        FROM browser_thread_sequence_observations
        WHERE root_browser_post_identity_id = ?
          AND relationship_evidence = 'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'
          AND sequence_position > 0""",
        (int(root["browser_post_identity_id"]),),
    ).fetchone()
    if detail is None or detail["detail_observation_id"] is None:
        return []
    nodes = repository.connection.execute(
        """SELECT sequence.node_browser_post_identity_id,
                  sequence.sequence_position,
                  observation.canonical_payload_json
        FROM browser_thread_sequence_observations sequence
        JOIN browser_observations observation
          ON observation.id = (
            SELECT MAX(candidate.id) FROM browser_observations candidate
            WHERE candidate.browser_post_identity_id =
                  sequence.node_browser_post_identity_id
              AND candidate.observation_type = 'POST_DETAIL'
          )
        WHERE sequence.detail_observation_id = ?
          AND sequence.relationship_evidence IN (
            'ROOT_DETAIL_PAGE', 'DOM_CONTIGUOUS_ROOT_AUTHOR_CHAIN'
          )
        ORDER BY sequence.sequence_position""",
        (int(detail["detail_observation_id"]),),
    ).fetchall()
    if len(nodes) < 2:
        return []
    roles = []
    for node in nodes:
        payload = json.loads(str(node["canonical_payload_json"]))
        text = payload.get("text") if isinstance(payload, dict) else ""
        feature = extract_structural_feature(text if isinstance(text, str) else "")
        roles.append(_thread_node_role(feature, is_root=int(node["sequence_position"]) == 0))
    return [{"component_sequence": roles}]


def materialize_structural_patterns(repository: Repository, structural_feature_run_id: int) -> int:
    """Promote only repeated, text-free structures with distinct source posts."""
    rows = repository.connection.execute(
        """SELECT structural_feature_instances.id, structural_feature_instances.feature_json,
                  structural_feature_instances.input_sha256,
                  normalized_post_versions.normalized_post_id,
                  structural_feature_instances.normalized_post_version_id
           FROM structural_feature_instances
           JOIN normalized_post_versions
             ON normalized_post_versions.id =
                structural_feature_instances.normalized_post_version_id
           WHERE structural_feature_instances.structural_feature_run_id = ?
           ORDER BY structural_feature_instances.id""",
        (structural_feature_run_id,),
    ).fetchall()
    inserted = 0
    for kind in ("FIRST_LINE", "POST", "THREAD"):
        groups: Dict[str, List[Any]] = defaultdict(list)
        for row in rows:
            feature = json.loads(str(row["feature_json"]))
            signatures = (
                _observed_thread_signature(
                    repository, int(row["normalized_post_version_id"])
                )
                if kind == "THREAD" else _candidate_signatures(feature, kind)
            )
            for signature in signatures:
                groups[_canonical_json(signature)].append(row)
        for signature_json, members in sorted(groups.items()):
            sources = {int(member["normalized_post_id"]) for member in members}
            if len(members) < 2 or len(sources) < 2:
                continue
            signature_sha256 = hashlib.sha256(signature_json.encode("utf-8")).hexdigest()
            input_document = {
                "signature_sha256": signature_sha256,
                "member_input_sha256s": sorted(str(member["input_sha256"]) for member in members),
                "pattern_kind": kind,
            }
            cursor = repository.connection.execute(
                """INSERT INTO structural_patterns
                (structural_feature_run_id, pattern_kind, signature_json, signature_sha256,
                 input_sha256, member_count, distinct_source_count, confidence, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (structural_feature_run_id, kind, signature_json, signature_sha256,
                 hashlib.sha256(_canonical_json(input_document).encode("utf-8")).hexdigest(),
                 len(members), len(sources), "MEDIUM" if len(members) >= 3 else "LOW"),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a structural pattern id")
            pattern_id = int(cursor.lastrowid)
            for ordinal, member in enumerate(sorted(members, key=lambda item: int(item["id"]))):
                repository.connection.execute(
                    """INSERT INTO structural_pattern_members
                    (structural_pattern_id, structural_feature_instance_id, ordinal)
                    VALUES (?, ?, ?)""",
                    (pattern_id, int(member["id"]), ordinal),
                )
            inserted += 1
    repository.connection.commit()
    return inserted
