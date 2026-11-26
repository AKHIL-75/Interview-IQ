"""
Semantic Matcher Service — Local Embedding Generation & Mathematical Cosine Similarity.

Computes semantic matching between candidate skills and job requirements using:
1. Canonical skill normalization and extensive alias lookup.
2. Parent/Child domain taxonomies (OOP -> Encapsulation, Polymorphism; DSA -> Arrays, Trees; etc.).
3. Alternative (OR) requirement parsing (e.g. "Java / Python / C++ / JavaScript").
4. Distinct technology discrimination (e.g. Java != JavaScript, C != C++).
5. Evidence levels:
   - EXPLICIT_MATCH (skills_found)
   - COVERED_THROUGH_PARENT (covered_through_parent)
   - COVERED_THROUGH_ALIAS (skills_found)
   - COVERED_SEMANTICALLY (skills_found)
   - NOT_EXPLICITLY_EVIDENCED (not_explicitly_evidenced)
   - TRUE_GAP (gap_skills — ONLY true gaps!)
6. Normalized requirement-group based scoring (avoids unfair duplicate penalties).
"""

from app.services.performance import span
import threading
from typing import TYPE_CHECKING, List, Set, Dict, Tuple, Optional
import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from app.schemas.resume import CandidateProfile
from app.schemas.job import JobProfile
from app.schemas.analysis import (
    MatchAnalysisResponse,
    MatchAnalysisSummary,
    RequirementCheckItem,
    SkillGapItem,
    SkillMatchItem,
)
from app.services.skill_taxonomy import (
    STATUS_EXPLICIT_MATCH,
    STATUS_COVERED_THROUGH_PARENT,
    STATUS_COVERED_THROUGH_ALIAS,
    STATUS_COVERED_SEMANTICALLY,
    STATUS_NOT_EXPLICITLY_EVIDENCED,
    STATUS_TRUE_GAP,
    DISTINCT_TECHNOLOGY_PAIRS,
    SKILL_TAXONOMY,
    normalize_skill_name,
    get_skill_display_name,
    get_parent_skill,
    get_child_skills,
    is_child_of,
    get_skill_domain,
    is_distinct_technology_taxonomic,
    is_or_requirement,
    split_or_requirement,
    detect_or_chains_in_jd,
    scan_text_for_skills,
)


# ---------------------------------------------------------------------------
# Constants & Model Configuration
# ---------------------------------------------------------------------------
MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_SIMILARITY_THRESHOLD = 0.60


# Domain taxonomies / aliases: recognized technical equivalences
KNOWN_EQUIVALENCES = {
    "postgresql": {"relational database", "relational databases", "rdbms", "sql", "postgres"},
    "postgres": {"relational database", "relational databases", "rdbms", "sql", "postgresql"},
    "mysql": {"relational database", "relational databases", "rdbms", "sql"},
    "sqlite": {"relational database", "relational databases", "rdbms", "sql"},
    "oracle": {"relational database", "relational databases", "rdbms", "sql"},
    "rdbms": {"relational database", "relational databases", "sql", "postgresql", "mysql"},
    "relational database": {"rdbms", "sql", "postgresql", "mysql"},
    "relational databases": {"rdbms", "sql", "postgresql", "mysql"},
    "docker": {"containerization", "containers", "container"},
    "containerization": {"docker", "containers"},
    "kubernetes": {"k8s", "container orchestration"},
    "k8s": {"kubernetes", "container orchestration"},
    "js": {"javascript"},
    "ts": {"typescript"},
    "reactjs": {"react"},
    "react.js": {"react"},
    "nodejs": {"node.js", "node"},
    "node.js": {"nodejs", "node"},
}


# ---------------------------------------------------------------------------
# Singleton Model Loader
# ---------------------------------------------------------------------------
_model_instance = None
_model_lock = threading.Lock()


def get_embedding_model() -> "SentenceTransformer":
    """
    Thread-safe singleton getter for the SentenceTransformer model.
    Loads 'all-MiniLM-L6-v2' once and keeps it in process memory.
    """
    global _model_instance
    if _model_instance is None:
        with _model_lock:
            if _model_instance is None:
                with span("semantic.model_initialization"):
                    from sentence_transformers import SentenceTransformer
                    _model_instance = SentenceTransformer(MODEL_NAME)
    return _model_instance


# ---------------------------------------------------------------------------
# Mathematical Utilities
# ---------------------------------------------------------------------------
def compute_cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """
    Calculate mathematical cosine similarity between two 1D vectors:
        cos_sim(A, B) = (A · B) / (||A|| * ||B||)
    """
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


def is_distinct_technology(skill_a: str, skill_b: str) -> bool:
    """
    Check if two skills are known distinct technologies (e.g. Java vs JavaScript, C vs C++).
    Uses the enhanced taxonomic discriminator.
    """
    return is_distinct_technology_taxonomic(skill_a, skill_b)


def check_known_equivalence(skill_a: str, skill_b: str) -> bool:
    """
    Check if two skills are known technical synonyms, canonical aliases, or domain equivalences.
    """
    sa = skill_a.strip().lower()
    sb = skill_b.strip().lower()
    if sa == sb:
        return True

    ca = normalize_skill_name(sa)
    cb = normalize_skill_name(sb)
    if ca == cb:
        return True

    if sa in KNOWN_EQUIVALENCES and sb in KNOWN_EQUIVALENCES[sa]:
        return True
    if sb in KNOWN_EQUIVALENCES and sa in KNOWN_EQUIVALENCES[sb]:
        return True

    # Check compound or slash-delimited skills (e.g. "Relational Database / RDBMS")
    if "/" in sa or "/" in sb:
        parts_a = [p.strip() for p in sa.split("/") if p.strip()] or [sa]
        parts_b = [p.strip() for p in sb.split("/") if p.strip()] or [sb]
        for pa in parts_a:
            for pb in parts_b:
                if check_known_equivalence(pa, pb):
                    return True

    return False


# ---------------------------------------------------------------------------
# Core Matching Engine
# ---------------------------------------------------------------------------
def calculate_match_analysis(
    candidate_profile: CandidateProfile,
    job_profile: JobProfile,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> MatchAnalysisResponse:
    """
    Perform semantic matching between CandidateProfile and JobProfile.
    Implements:
    - Canonical skill normalization and alias mapping.
    - Parent/Child taxonomy reasoning (OOP, DSA, DBMS, Web, Backend, etc.).
    - OR-requirement group satisfaction.
    - Evidence classification (explicit, parent-covered, alias, semantic, not-evidenced, true-gap).
    - Normalized requirement-group scoring (explainable, non-inflated).
    """
    # 1. Collect candidate skills (extracted_skills + key_projects technologies + project description scans)
    cand_skill_set: Set[str] = set()
    raw_texts: List[str] = []

    for s in candidate_profile.extracted_skills:
        clean_s = str(s).strip()
        if clean_s:
            cand_skill_set.add(clean_s)

    for proj in candidate_profile.key_projects:
        for tech in proj.technologies:
            clean_tech = str(tech).strip()
            if clean_tech:
                cand_skill_set.add(clean_tech)
        if proj.description:
            raw_texts.append(proj.description)

    # Scan project texts or raw text for explicit taxonomy skill mentions
    if raw_texts:
        scanned = scan_text_for_skills(" ".join(raw_texts))
        cand_skill_set.update(scanned)

    candidate_skills = list(cand_skill_set)

    # Index candidate skills by canonical ID and lowercase name
    candidate_canonical_map: Dict[str, str] = {}
    candidate_canonical_set: Set[str] = set()
    candidate_lower_set: Set[str] = set()

    for cs in candidate_skills:
        low = cs.lower().strip()
        candidate_lower_set.add(low)
        canon = normalize_skill_name(cs)
        candidate_canonical_set.add(canon)
        candidate_canonical_map[canon] = cs

    # Also build a set of candidate parent domains (e.g. if candidate has OOP, add 'oop' domain)
    candidate_parent_skills: Set[str] = set()
    for cs in candidate_skills:
        canon = normalize_skill_name(cs)
        if canon in SKILL_TAXONOMY and "children" in SKILL_TAXONOMY[canon]:
            candidate_parent_skills.add(canon)

    # 2. Extract and deduplicate JD requirements
    raw_required = [str(s).strip() for s in job_profile.required_skills if str(s).strip()]
    raw_preferred = [str(s).strip() for s in job_profile.good_to_have_skills if str(s).strip()]

    req_seen = set()
    dedup_required = []
    for s in raw_required:
        low = s.lower()
        if low not in req_seen:
            req_seen.add(low)
            dedup_required.append(s)

    pref_seen = set()
    dedup_preferred = []
    for s in raw_preferred:
        low = s.lower()
        if low not in req_seen and low not in pref_seen:
            pref_seen.add(low)
            dedup_preferred.append(s)

    # Detect any OR chains across the skills in the JD
    # (e.g. if the JD lists Java, Python, C++, JavaScript from an OR block)
    all_jd_text = " \n ".join(dedup_required + dedup_preferred)
    detected_or_chains = detect_or_chains_in_jd(all_jd_text)

    # 3. Handle empty edge cases
    if not candidate_skills:
        req_gaps = [
            SkillGapItem(skill=s, category="required", reason="No candidate skills available in resume", status=STATUS_TRUE_GAP)
            for s in dedup_required
        ]
        pref_gaps = [
            SkillGapItem(skill=s, category="preferred", reason="No candidate skills available in resume", status=STATUS_TRUE_GAP)
            for s in dedup_preferred
        ]
        req_checks = [
            RequirementCheckItem(text=s, matched=False, matched_with=None, similarity=0.0, status=STATUS_TRUE_GAP)
            for s in dedup_required
        ]
        return MatchAnalysisResponse(
            success=True,
            match_score=0,
            matched_skills=[],
            skill_gaps=req_gaps,
            preferred_matches=[],
            preferred_gaps=pref_gaps,
            skills_found=[],
            covered_through_parent=[],
            not_explicitly_evidenced=[],
            gap_skills=[g.skill for g in req_gaps + pref_gaps],
            requirements=req_checks,
            requirement_groups=[],
            summary=MatchAnalysisSummary(
                total_required=len(dedup_required),
                matched_required=0,
                total_preferred=len(dedup_preferred),
                matched_preferred=0,
                total_candidate_skills=0,
                required_coverage=0.0,
                preferred_coverage=0.0,
                threshold_used=threshold,
            ),
        )

    all_target_skills = dedup_required + dedup_preferred
    if not all_target_skills:
        return MatchAnalysisResponse(
            success=True,
            match_score=0,
            matched_skills=[],
            skill_gaps=[],
            preferred_matches=[],
            preferred_gaps=[],
            skills_found=[],
            covered_through_parent=[],
            not_explicitly_evidenced=[],
            gap_skills=[],
            requirements=[],
            requirement_groups=[],
            summary=MatchAnalysisSummary(
                total_required=0,
                matched_required=0,
                total_preferred=0,
                matched_preferred=0,
                total_candidate_skills=len(candidate_skills),
                required_coverage=0.0,
                preferred_coverage=0.0,
                threshold_used=threshold,
            ),
        )

    # 4. Generate batch embeddings for candidate and JD skills
    model = get_embedding_model()
    # Match both profiles in one request-local batch. Preserve each original row order.
    skills = list(dict.fromkeys([*candidate_skills, *all_target_skills]))
    positions = {skill: index for index, skill in enumerate(skills)}
    with span("matching.embeddings"):
        vectors = np.asarray(model.encode(skills, convert_to_numpy=True, normalize_embeddings=True))
    cand_embeddings = vectors[[positions[skill] for skill in candidate_skills]]
    target_embeddings = vectors[[positions[skill] for skill in all_target_skills]]

    sim_matrix = np.dot(target_embeddings, cand_embeddings.T)

    matched_skills: List[SkillMatchItem] = []
    skill_gaps: List[SkillGapItem] = []
    preferred_matches: List[SkillMatchItem] = []
    preferred_gaps: List[SkillGapItem] = []
    requirements: List[RequirementCheckItem] = []

    skills_found_names: List[str] = []
    covered_through_parent_names: List[str] = []
    not_explicitly_evidenced_names: List[str] = []
    gap_skills_names: List[str] = []

    # Track requirement groups for normalized scoring
    req_group_scores: List[float] = []
    pref_group_scores: List[float] = []

    # Map of satisfied OR chains
    satisfied_or_chains: List[Set[str]] = []
    for chain in detected_or_chains:
        if chain.intersection(candidate_canonical_set):
            satisfied_or_chains.append(chain)

    def is_in_satisfied_or_chain(skill_str: str) -> bool:
        canon = normalize_skill_name(skill_str)
        for chain in satisfied_or_chains:
            if canon in chain:
                return True
        return False

    # 5. Core Evaluation Helper per Skill
    def evaluate_skill_requirement(
        target_skill: str,
        target_idx: int,
        category: str,
    ) -> Tuple[str, Optional[str], float, Optional[str], Optional[str]]:
        """
        Evaluate a single target skill against candidate competencies.
        Returns:
            (status, matched_with, similarity, parent_skill, evidence_text)
        """
        target_clean = target_skill.strip()
        target_canon = normalize_skill_name(target_clean)

        # -------------------------------------------------------------
        # A. Check if requirement itself is an OR-group (e.g. "Java / Python / C++")
        # -------------------------------------------------------------
        if is_or_requirement(target_clean):
            options = split_or_requirement(target_clean)
            matched_options: List[str] = []
            best_opt_sim = 0.0
            for opt in options:
                opt_canon = normalize_skill_name(opt)
                if opt_canon in candidate_canonical_set:
                    matched_cs = candidate_canonical_map[opt_canon]
                    if matched_cs not in matched_options:
                        matched_options.append(matched_cs)
                    best_opt_sim = 1.0
                elif opt.lower() in candidate_lower_set:
                    for cs in candidate_skills:
                        if cs.lower() == opt.lower() and cs not in matched_options:
                            matched_options.append(cs)
                            best_opt_sim = 1.0
                else:
                    # check semantic / alias match for this option
                    for cs in candidate_skills:
                        if check_known_equivalence(opt, cs) and cs not in matched_options:
                            matched_options.append(cs)
                            best_opt_sim = 1.0
                            break

            if matched_options:
                matched_with_str = ", ".join(matched_options)
                evidence = f"Satisfied via alternative option: {matched_with_str}"
                return (STATUS_EXPLICIT_MATCH, matched_with_str, 1.0, None, evidence)
            else:
                # None of the options were satisfied -> TRUE GAP
                return (STATUS_TRUE_GAP, None, 0.0, None, f"None of the alternative options ({target_clean}) found")

        # -------------------------------------------------------------
        # B. Check if this skill is part of an already-satisfied OR chain in the JD
        # (e.g. target is "C++" but JD had "Java / Python / C++" and candidate has Java)
        # -------------------------------------------------------------
        if is_in_satisfied_or_chain(target_clean):
            # Find which candidate skill satisfied this group
            satisfying_skill = None
            for chain in satisfied_or_chains:
                if target_canon in chain:
                    for cand_canon in chain.intersection(candidate_canonical_set):
                        satisfying_skill = candidate_canonical_map.get(cand_canon, cand_canon)
                        break
            evidence = f"Requirement group satisfied via alternative: {satisfying_skill or 'candidate proficiency'}"
            return (STATUS_EXPLICIT_MATCH, satisfying_skill, 1.0, None, evidence)

        # -------------------------------------------------------------
        # C. Direct Exact or Case-Normalized Match
        # -------------------------------------------------------------
        for cs in candidate_skills:
            if cs.lower().strip() == target_clean.lower():
                return (STATUS_EXPLICIT_MATCH, cs, 1.0, None, f"Explicitly listed in resume: {cs}")

        # -------------------------------------------------------------
        # D. Known Canonical Alias / Synonym Match (e.g. REST API == RESTful APIs)
        # -------------------------------------------------------------
        if target_canon in candidate_canonical_set:
            matched_cs = candidate_canonical_map[target_canon]
            return (STATUS_COVERED_THROUGH_ALIAS, matched_cs, 1.0, None, f"Matched via canonical alias: {matched_cs}")

        for cs in candidate_skills:
            if check_known_equivalence(target_clean, cs):
                return (STATUS_COVERED_THROUGH_ALIAS, cs, 1.0, None, f"Domain equivalence with: {cs}")

        # -------------------------------------------------------------
        # E. Semantic Vector Cosine Similarity Match
        # -------------------------------------------------------------
        best_sim = -1.0
        best_cand_skill = None

        for j, cs in enumerate(candidate_skills):
            if is_distinct_technology(target_clean, cs):
                continue
            sim = float(sim_matrix[target_idx, j])
            if sim > best_sim:
                best_sim = sim
                best_cand_skill = cs

        if best_sim >= threshold and best_cand_skill is not None:
            return (
                STATUS_COVERED_SEMANTICALLY,
                best_cand_skill,
                round(best_sim, 3),
                None,
                f"Semantic match with '{best_cand_skill}' (similarity {best_sim:.2f})",
            )

        # -------------------------------------------------------------
        # F. Parent-Child Taxonomy Reasoning:
        # Does the candidate possess the PARENT concept of this target skill?
        # (e.g. Target is 'Polymorphism', 'Inheritance', 'Encapsulation', 'Abstraction'; candidate has 'OOP')
        # (e.g. Target is 'Joins', 'Normalization'; candidate has 'DBMS' or 'SQL')
        # (e.g. Target is 'Server-side Development'; candidate has 'backend' or 'REST APIs' + Java/Python)
        # -------------------------------------------------------------
        parent_id = get_parent_skill(target_clean)
        if parent_id and parent_id in candidate_canonical_set:
            parent_display = get_skill_display_name(parent_id)
            if parent_id == "dsa":
                evidence = f"Covered under Data Structures & Algorithms domain; specific topic '{target_clean}' not explicitly listed"
                return (STATUS_NOT_EXPLICITLY_EVIDENCED, parent_display, 0.75, parent_display, evidence)
            evidence = f"Covered through parent core competency '{parent_display}' in resume"
            return (STATUS_COVERED_THROUGH_PARENT, parent_display, 0.90, parent_display, evidence)

        # Domain-level parent coverage (e.g. SQL / DBMS covers relational concepts)
        if target_canon in ("joins", "queries", "normalization", "indexing"):
            if "sql" in candidate_canonical_set or "dbms" in candidate_canonical_set:
                parent_display = candidate_canonical_map.get("dbms", candidate_canonical_map.get("sql", "DBMS/SQL"))
                evidence = f"Covered through database proficiency in '{parent_display}'"
                return (STATUS_COVERED_THROUGH_PARENT, parent_display, 0.90, parent_display, evidence)

        # Server-side development covered by backend technologies (REST APIs, Java, Python, SQL)
        if target_canon == "server_side_development":
            if "rest_apis" in candidate_canonical_set or any(lang in candidate_canonical_set for lang in ("java", "python", "go", "csharp", "php")):
                evidence = "Covered through backend programming languages and REST API experience"
                return (STATUS_COVERED_THROUGH_PARENT, "Backend Stack", 0.90, "Backend Development", evidence)

        # -------------------------------------------------------------
        # G. DSA Sub-Concept Reasoning:
        # If candidate has Data Structures & Algorithms (dsa), but this specific
        # data structure / algorithm was not explicitly listed:
        # It is NOT_EXPLICITLY_EVIDENCED — NOT A TRUE GAP!
        # -------------------------------------------------------------
        if is_child_of(target_clean, "dsa") and "dsa" in candidate_canonical_set:
            evidence = f"Covered under Data Structures & Algorithms domain; specific topic '{target_clean}' not explicitly listed"
            return (STATUS_NOT_EXPLICITLY_EVIDENCED, "Data Structures & Algorithms", 0.75, "Data Structures & Algorithms", evidence)

        # -------------------------------------------------------------
        # H. Reverse Parent Check: Target is a parent concept (e.g. OOP, DSA),
        # and candidate has multiple child concepts.
        # -------------------------------------------------------------
        child_skills = get_child_skills(target_clean)
        matched_children = [candidate_canonical_map[c] for c in child_skills if c in candidate_canonical_set]
        if len(matched_children) >= 2:
            matched_str = ", ".join(matched_children[:4])
            evidence = f"Core concept evidenced through specific implementations: {matched_str}"
            return (STATUS_COVERED_THROUGH_PARENT, matched_str, 0.85, None, evidence)

        # -------------------------------------------------------------
        # I. None of the above apply -> TRUE GAP
        # -------------------------------------------------------------
        return (
            STATUS_TRUE_GAP,
            best_cand_skill if best_sim > 0.30 else None,
            round(max(0.0, best_sim), 3) if best_sim > 0.0 else 0.0,
            None,
            f"No matching or parent skill found in resume (similarity {max(0.0, best_sim):.2f})",
        )

    # 6. Evaluate Required Skills
    for i, req_skill in enumerate(dedup_required):
        status, matched_with, sim, parent, evidence = evaluate_skill_requirement(req_skill, i, "required")

        if status in (STATUS_EXPLICIT_MATCH, STATUS_COVERED_THROUGH_ALIAS, STATUS_COVERED_SEMANTICALLY):
            matched_skills.append(
                SkillMatchItem(
                    required_skill=req_skill,
                    candidate_skill=matched_with or req_skill,
                    similarity=sim,
                    category="required",
                    status=status,
                    parent_skill=parent,
                    evidence=evidence,
                )
            )
            skills_found_names.append(req_skill)
            requirements.append(
                RequirementCheckItem(
                    text=req_skill,
                    matched=True,
                    matched_with=matched_with,
                    similarity=sim,
                    status=status,
                )
            )

        elif status == STATUS_COVERED_THROUGH_PARENT:
            matched_skills.append(
                SkillMatchItem(
                    required_skill=req_skill,
                    candidate_skill=matched_with or parent or "Parent Domain",
                    similarity=sim,
                    category="required",
                    status=status,
                    parent_skill=parent,
                    evidence=evidence,
                )
            )
            covered_through_parent_names.append(req_skill)
            requirements.append(
                RequirementCheckItem(
                    text=req_skill,
                    matched=True,
                    matched_with=f"Covered through {parent or matched_with}",
                    similarity=sim,
                    status=status,
                )
            )

        elif status == STATUS_NOT_EXPLICITLY_EVIDENCED:
            not_explicitly_evidenced_names.append(req_skill)
            requirements.append(
                RequirementCheckItem(
                    text=req_skill,
                    matched=True,
                    matched_with=f"Concept covered under {parent or 'core domain'}",
                    similarity=sim,
                    status=status,
                )
            )

        else:
            # STATUS_TRUE_GAP — ONLY these are actual skill gaps
            skill_gaps.append(
                SkillGapItem(
                    skill=req_skill,
                    category="required",
                    reason=evidence,
                    status=STATUS_TRUE_GAP,
                )
            )
            gap_skills_names.append(req_skill)
            requirements.append(
                RequirementCheckItem(
                    text=req_skill,
                    matched=False,
                    matched_with=None,
                    similarity=sim if sim > 0.0 else None,
                    status=STATUS_TRUE_GAP,
                )
            )

    # 7. Evaluate Preferred Skills
    offset = len(dedup_required)
    for k, pref_skill in enumerate(dedup_preferred):
        target_idx = offset + k
        status, matched_with, sim, parent, evidence = evaluate_skill_requirement(pref_skill, target_idx, "preferred")

        if status in (STATUS_EXPLICIT_MATCH, STATUS_COVERED_THROUGH_ALIAS, STATUS_COVERED_SEMANTICALLY):
            preferred_matches.append(
                SkillMatchItem(
                    required_skill=pref_skill,
                    candidate_skill=matched_with or pref_skill,
                    similarity=sim,
                    category="preferred",
                    status=status,
                    parent_skill=parent,
                    evidence=evidence,
                )
            )
            skills_found_names.append(pref_skill)
            requirements.append(
                RequirementCheckItem(
                    text=f"{pref_skill} (Preferred)",
                    matched=True,
                    matched_with=matched_with,
                    similarity=sim,
                    status=status,
                )
            )

        elif status == STATUS_COVERED_THROUGH_PARENT:
            preferred_matches.append(
                SkillMatchItem(
                    required_skill=pref_skill,
                    candidate_skill=matched_with or parent or "Parent Domain",
                    similarity=sim,
                    category="preferred",
                    status=status,
                    parent_skill=parent,
                    evidence=evidence,
                )
            )
            covered_through_parent_names.append(pref_skill)
            requirements.append(
                RequirementCheckItem(
                    text=f"{pref_skill} (Preferred)",
                    matched=True,
                    matched_with=f"Covered through {parent or matched_with}",
                    similarity=sim,
                    status=status,
                )
            )

        elif status == STATUS_NOT_EXPLICITLY_EVIDENCED:
            not_explicitly_evidenced_names.append(pref_skill)
            requirements.append(
                RequirementCheckItem(
                    text=f"{pref_skill} (Preferred)",
                    matched=True,
                    matched_with=f"Concept covered under {parent or 'core domain'}",
                    similarity=sim,
                    status=status,
                )
            )

        else:
            preferred_gaps.append(
                SkillGapItem(
                    skill=pref_skill,
                    category="preferred",
                    reason=evidence,
                    status=STATUS_TRUE_GAP,
                )
            )
            gap_skills_names.append(pref_skill)
            requirements.append(
                RequirementCheckItem(
                    text=f"{pref_skill} (Preferred)",
                    matched=False,
                    matched_with=None,
                    similarity=sim if sim > 0.0 else None,
                    status=STATUS_TRUE_GAP,
                )
            )

    # ---------------------------------------------------------------------------
    # 8. Normalized Requirement-Group Score Computation (Bug 7)
    # Prevents multiple duplicate penalties for single conceptual areas.
    # ---------------------------------------------------------------------------
    def compute_grouped_score(skills_list: List[str], check_dict: Dict[str, RequirementCheckItem]) -> Tuple[float, List[dict]]:
        if not skills_list:
            return 1.0, []

        groups: Dict[str, List[str]] = {}
        processed = set()

        # Step 1: OR groups detected in the JD (e.g. Java / Python / C++ / JavaScript)
        for chain_idx, chain in enumerate(detected_or_chains):
            chain_skills = [s for s in skills_list if normalize_skill_name(s) in chain]
            if len(chain_skills) >= 2:
                group_name = f"OR Group ({', '.join(chain_skills[:3])})"
                groups[group_name] = chain_skills
                for s in chain_skills:
                    processed.add(s.lower())

        for s in skills_list:
            if s.lower() in processed:
                continue
            if is_or_requirement(s):
                groups[f"OR ({s})"] = [s]
                processed.add(s.lower())

        # Step 2: Hierarchical parent-child clustering
        # If multiple skills in the JD share the same parent concept (e.g. OOP, DSA, DBMS),
        # cluster them under that parent so candidates aren't penalized multiple times.
        parent_buckets: Dict[str, List[str]] = {}
        for s in skills_list:
            if s.lower() in processed:
                continue
            parent = get_parent_skill(s)
            if parent:
                if parent not in parent_buckets:
                    parent_buckets[parent] = []
                parent_buckets[parent].append(s)

        for parent_id, child_items in parent_buckets.items():
            if len(child_items) >= 2:
                parent_display = get_skill_display_name(parent_id)
                groups[f"{parent_display} Domain"] = child_items
                for s in child_items:
                    processed.add(s.lower())

        # Step 3: Standalone requirements (independent peer technologies like Java, Python, React, Docker)
        for s in skills_list:
            if s.lower() in processed:
                continue
            groups[s] = [s]
            processed.add(s.lower())

        # Step 4: Compute score per requirement group
        group_records = []
        scores = []
        for g_name, items in groups.items():
            if not items:
                continue

            # If it's an OR group: satisfied if ANY item is matched
            if g_name.startswith("OR Group") or g_name.startswith("OR ("):
                satisfied = any(check_dict.get(item) and check_dict[item].matched for item in items)
                g_score = 1.0 if satisfied else 0.0
                scores.append(g_score)
                group_records.append({
                    "group": g_name,
                    "items": items,
                    "score": g_score,
                    "status": "satisfied" if satisfied else "unsatisfied",
                })
            elif "Domain" in g_name:
                # Hierarchical domain group: compute coverage with parent mastery boost
                matched_count = sum(1 for item in items if check_dict.get(item) and check_dict[item].matched)
                raw_cov = matched_count / len(items)

                # Identify if candidate has the parent concept
                parent_canon = None
                for canon_id in SKILL_TAXONOMY:
                    if get_skill_display_name(canon_id) in g_name:
                        parent_canon = canon_id
                        break

                if parent_canon and parent_canon in candidate_canonical_set:
                    # Parent concept is mastered in resume -> guaranteed baseline 0.85, up to 1.0 with explicit children
                    g_score = min(1.0, 0.85 + 0.15 * raw_cov)
                else:
                    g_score = raw_cov

                scores.append(g_score)
                group_records.append({
                    "group": g_name,
                    "items": items,
                    "score": round(g_score, 2),
                    "status": "satisfied" if g_score >= 0.70 else ("partial" if g_score > 0 else "gap"),
                })
            else:
                # Standalone requirement
                item = items[0]
                is_matched = check_dict.get(item) and check_dict[item].matched
                g_score = 1.0 if is_matched else 0.0
                scores.append(g_score)
                group_records.append({
                    "group": g_name,
                    "items": items,
                    "score": g_score,
                    "status": "satisfied" if is_matched else "gap",
                })

        avg_score = sum(scores) / len(scores) if scores else 0.0
        return avg_score, group_records

    # Build check dict for fast lookup
    check_map: Dict[str, RequirementCheckItem] = {}
    for req in requirements:
        # Strip "(Preferred)" suffix if present for clean lookup
        clean_text = req.text.replace(" (Preferred)", "").strip()
        check_map[clean_text] = req

    req_coverage, req_group_records = compute_grouped_score(dedup_required, check_map)
    pref_coverage, pref_group_records = compute_grouped_score(dedup_preferred, check_map)

    # 9. Overall Match Score Computation
    if dedup_required and dedup_preferred:
        raw_score = (0.80 * req_coverage + 0.20 * pref_coverage) * 100
    elif dedup_required:
        raw_score = req_coverage * 100
    elif dedup_preferred:
        raw_score = pref_coverage * 100
    else:
        raw_score = 0.0

    match_score = int(round(max(0.0, min(100.0, raw_score))))

    return MatchAnalysisResponse(
        success=True,
        match_score=match_score,
        matched_skills=matched_skills,
        skill_gaps=skill_gaps,
        preferred_matches=preferred_matches,
        preferred_gaps=preferred_gaps,
        skills_found=skills_found_names,
        covered_through_parent=covered_through_parent_names,
        not_explicitly_evidenced=not_explicitly_evidenced_names,
        gap_skills=gap_skills_names,
        requirements=requirements,
        requirement_groups=req_group_records + pref_group_records,
        summary=MatchAnalysisSummary(
            total_required=len(dedup_required),
            matched_required=len(matched_skills),
            total_preferred=len(dedup_preferred),
            matched_preferred=len(preferred_matches),
            total_candidate_skills=len(candidate_skills),
            required_coverage=round(req_coverage, 3),
            preferred_coverage=round(pref_coverage, 3),
            threshold_used=threshold,
        ),
    )
