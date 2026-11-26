"""
Skill Taxonomy & Relationship Engine — Canonical Normalization, Parent-Child Hierarchies & OR-Group Parsing.

Provides:
1. Canonical skill normalization with extensive alias mapping.
2. Parent/Child domain taxonomies (e.g. OOP -> Encapsulation, Inheritance, Polymorphism, Abstraction;
   DSA -> Arrays, Strings, Linked Lists, Stacks, Queues, Trees, Graphs, Sorting, Searching, DP).
3. OR-requirement parsing (e.g. "Java / Python / C++ / JavaScript").
4. Distinct technology discrimination (e.g. Java != JavaScript, C != C++).
5. Evidence levels:
   - EXPLICIT_MATCH: Directly evidenced in candidate skills / resume text.
   - COVERED_THROUGH_PARENT: Parent competency is present (e.g. Polymorphism covered via OOP).
   - COVERED_THROUGH_ALIAS: Exact match under canonical synonym / alias.
   - COVERED_SEMANTICALLY: High vector similarity in embeddings.
   - NOT_EXPLICITLY_EVIDENCED: Concept covered under parent domain, but specific sub-topic not explicitly listed.
   - TRUE_GAP: Requirement has no matching skill, parent, child, or satisfied OR-group.
"""

import re
from typing import Optional, Set, Dict, List, Tuple


# ---------------------------------------------------------------------------
# Evidence Level Status Constants
# ---------------------------------------------------------------------------
STATUS_EXPLICIT_MATCH = "explicit_match"
STATUS_COVERED_THROUGH_PARENT = "covered_through_parent"
STATUS_COVERED_THROUGH_ALIAS = "covered_through_alias"
STATUS_COVERED_SEMANTICALLY = "covered_semantically"
STATUS_NOT_EXPLICITLY_EVIDENCED = "not_explicitly_evidenced"
STATUS_TRUE_GAP = "true_gap"


# ---------------------------------------------------------------------------
# Distinct Technology Pairs (MUST NEVER MATCH)
# ---------------------------------------------------------------------------
DISTINCT_TECHNOLOGY_PAIRS: Set[Tuple[str, str]] = {
    ("java", "javascript"),
    ("javascript", "java"),
    ("c", "c++"),
    ("c++", "c"),
    ("c", "c#"),
    ("c#", "c"),
    ("c++", "c#"),
    ("c#", "c++"),
    ("typescript", "javascript"),
    ("javascript", "typescript"),
    ("sql", "nosql"),
    ("nosql", "sql"),
    ("r", "rust"),
    ("rust", "r"),
}

# Protected slash terms that represent a SINGLE compound technology, NOT an OR group
PROTECTED_COMPOUND_TERMS: Set[str] = {
    "ci/cd",
    "cicd",
    "tcp/ip",
    "pl/sql",
    "plsql",
    "pl/pgsql",
    "i/o",
    "os/2",
    "client/server",
    "end-to-end",
    "full-stack",
    "front-end",
    "back-end",
}


# ---------------------------------------------------------------------------
# Canonical Skill Taxonomy Definition
# ---------------------------------------------------------------------------
SKILL_TAXONOMY: Dict[str, dict] = {
    # --- Programming Languages ---
    "java": {
        "display": "Java",
        "aliases": ["java", "core java", "advanced java", "java 8", "java 11", "java 17", "java 21", "j2se", "j2ee"],
        "domain": "programming_languages",
        "is_language": True,
    },
    "python": {
        "display": "Python",
        "aliases": ["python", "python3", "python 3", "py"],
        "domain": "programming_languages",
        "is_language": True,
    },
    "javascript": {
        "display": "JavaScript",
        "aliases": ["javascript", "js", "java script", "ecmascript", "es6", "es6+", "vanilla javascript"],
        "domain": "programming_languages",
        "is_language": True,
    },
    "typescript": {
        "display": "TypeScript",
        "aliases": ["typescript", "ts"],
        "domain": "programming_languages",
        "is_language": True,
    },
    "cpp": {
        "display": "C++",
        "aliases": ["c++", "cpp", "c plus plus"],
        "domain": "programming_languages",
        "is_language": True,
    },
    "c": {
        "display": "C",
        "aliases": ["c language", "ansi c"],
        "domain": "programming_languages",
        "is_language": True,
    },
    "csharp": {
        "display": "C#",
        "aliases": ["c#", "csharp", "c sharp", ".net c#"],
        "domain": "programming_languages",
        "is_language": True,
    },
    "go": {
        "display": "Go",
        "aliases": ["go", "golang"],
        "domain": "programming_languages",
        "is_language": True,
    },
    "rust": {
        "display": "Rust",
        "aliases": ["rust", "rustlang"],
        "domain": "programming_languages",
        "is_language": True,
    },
    "ruby": {
        "display": "Ruby",
        "aliases": ["ruby", "ruby on rails"],
        "domain": "programming_languages",
        "is_language": True,
    },
    "php": {
        "display": "PHP",
        "aliases": ["php", "php7", "php8"],
        "domain": "programming_languages",
        "is_language": True,
    },
    "kotlin": {
        "display": "Kotlin",
        "aliases": ["kotlin"],
        "domain": "programming_languages",
        "is_language": True,
    },
    "swift": {
        "display": "Swift",
        "aliases": ["swift"],
        "domain": "programming_languages",
        "is_language": True,
    },
    "sql": {
        "display": "SQL",
        "aliases": ["sql", "structured query language", "ansi sql", "t-sql", "pl/sql", "plsql"],
        "domain": "database",
        "is_language": False,
    },

    # --- Core CS & OOP ---
    "oop": {
        "display": "OOP",
        "aliases": [
            "oop", "oops", "object oriented programming", "object-oriented programming",
            "object oriented programming concepts", "oop concepts", "object-oriented", "object oriented"
        ],
        "domain": "oop",
        "children": [
            "encapsulation", "inheritance", "polymorphism", "abstraction",
            "classes", "objects", "interfaces", "abstract classes",
            "method overriding", "method overloading", "composition",
            "aggregation", "design patterns", "solid principles"
        ],
    },
    "encapsulation": {
        "display": "Encapsulation",
        "aliases": ["encapsulation", "data hiding"],
        "parent": "oop",
        "domain": "oop",
    },
    "inheritance": {
        "display": "Inheritance",
        "aliases": ["inheritance", "multiple inheritance", "hierarchical inheritance"],
        "parent": "oop",
        "domain": "oop",
    },
    "polymorphism": {
        "display": "Polymorphism",
        "aliases": ["polymorphism", "runtime polymorphism", "compile time polymorphism", "dynamic dispatch"],
        "parent": "oop",
        "domain": "oop",
    },
    "abstraction": {
        "display": "Abstraction",
        "aliases": ["abstraction", "data abstraction"],
        "parent": "oop",
        "domain": "oop",
    },
    "classes_objects": {
        "display": "Classes & Objects",
        "aliases": ["classes", "objects", "class", "object", "classes and objects"],
        "parent": "oop",
        "domain": "oop",
    },
    "design_patterns": {
        "display": "Design Patterns",
        "aliases": ["design patterns", "gang of four", "singleton", "factory pattern", "observer pattern"],
        "parent": "oop",
        "domain": "oop",
    },

    # --- Data Structures & Algorithms (DSA) ---
    "dsa": {
        "display": "Data Structures & Algorithms",
        "aliases": [
            "dsa", "data structures & algorithms", "data structures and algorithms",
            "data structures", "algorithms", "ds & algo", "ds and algo",
            "data structure & algorithms", "data structure and algorithms", "data structure"
        ],
        "domain": "dsa",
        "children": [
            "arrays", "strings", "linked_lists", "stacks", "queues", "trees",
            "graphs", "hash_tables", "heaps", "sorting", "searching",
            "dynamic_programming", "recursion", "greedy_algorithms",
            "divide_and_conquer", "basic_algorithms", "time_complexity"
        ],
    },
    "arrays": {
        "display": "Arrays",
        "aliases": ["arrays", "array", "multidimensional arrays", "static arrays", "dynamic arrays"],
        "parent": "dsa",
        "domain": "dsa",
    },
    "strings": {
        "display": "Strings",
        "aliases": ["strings", "string manipulation", "string", "string algorithms"],
        "parent": "dsa",
        "domain": "dsa",
    },
    "linked_lists": {
        "display": "Linked Lists",
        "aliases": ["linked lists", "linked list", "singly linked list", "doubly linked list", "circular linked list"],
        "parent": "dsa",
        "domain": "dsa",
    },
    "stacks": {
        "display": "Stacks",
        "aliases": ["stacks", "stack", "lifo"],
        "parent": "dsa",
        "domain": "dsa",
    },
    "queues": {
        "display": "Queues",
        "aliases": ["queues", "queue", "fifo", "priority queue", "deque", "circular queue"],
        "parent": "dsa",
        "domain": "dsa",
    },
    "trees": {
        "display": "Trees",
        "aliases": [
            "trees", "tree", "binary tree", "binary search tree", "bst",
            "avl tree", "red-black tree", "trie", "n-ary tree", "binary trees"
        ],
        "parent": "dsa",
        "domain": "dsa",
    },
    "graphs": {
        "display": "Graphs",
        "aliases": [
            "graphs", "graph", "bfs", "dfs", "breadth first search",
            "depth first search", "shortest path", "dijkstra", "topological sort"
        ],
        "parent": "dsa",
        "domain": "dsa",
    },
    "hash_tables": {
        "display": "Hash Tables",
        "aliases": ["hash tables", "hash table", "hash map", "hashmap", "hashing"],
        "parent": "dsa",
        "domain": "dsa",
    },
    "heaps": {
        "display": "Heaps",
        "aliases": ["heaps", "heap", "min heap", "max heap", "priority queues"],
        "parent": "dsa",
        "domain": "dsa",
    },
    "sorting": {
        "display": "Sorting",
        "aliases": ["sorting", "sorting algorithms", "merge sort", "quick sort", "bubble sort", "insertion sort", "heap sort"],
        "parent": "dsa",
        "domain": "dsa",
    },
    "searching": {
        "display": "Searching",
        "aliases": ["searching", "searching algorithms", "binary search", "linear search"],
        "parent": "dsa",
        "domain": "dsa",
    },
    "dynamic_programming": {
        "display": "Dynamic Programming",
        "aliases": ["dynamic programming", "dp", "memoization", "tabulation"],
        "parent": "dsa",
        "domain": "dsa",
    },
    "basic_algorithms": {
        "display": "Basic Algorithms",
        "aliases": ["basic algorithms", "algorithm design", "algorithmic problem solving", "problem solving"],
        "parent": "dsa",
        "domain": "dsa",
    },
    "time_complexity": {
        "display": "Complexity Analysis",
        "aliases": ["time complexity", "space complexity", "big o", "asymptotic notation", "big-o notation"],
        "parent": "dsa",
        "domain": "dsa",
    },

    # --- Database & DBMS ---
    "dbms": {
        "display": "DBMS",
        "aliases": [
            "dbms", "database management systems", "database management system",
            "database management", "rdbms", "relational database", "relational databases",
            "database", "databases"
        ],
        "domain": "database",
        "children": [
            "sql", "joins", "queries", "normalization", "indexing",
            "transactions", "acid_properties", "stored_procedures"
        ],
    },
    "joins": {
        "display": "Joins",
        "aliases": ["joins", "sql joins", "inner join", "outer join", "left join", "right join", "cross join"],
        "parent": "dbms",
        "domain": "database",
    },
    "queries": {
        "display": "Queries",
        "aliases": ["queries", "sql queries", "query optimization", "subqueries", "complex queries", "querying"],
        "parent": "dbms",
        "domain": "database",
    },
    "normalization": {
        "display": "Normalization",
        "aliases": ["normalization", "database normalization", "1nf", "2nf", "3nf", "bcnf"],
        "parent": "dbms",
        "domain": "database",
    },
    "indexing": {
        "display": "Indexing",
        "aliases": ["indexing", "database indexing", "b-tree index", "indexes"],
        "parent": "dbms",
        "domain": "database",
    },
    "transactions": {
        "display": "Transactions & ACID",
        "aliases": ["transactions", "acid properties", "acid", "transaction management"],
        "parent": "dbms",
        "domain": "database",
    },

    # --- Web & Frontend ---
    "web_development": {
        "display": "Web Development",
        "aliases": ["web development", "web technologies", "web", "frontend", "front-end"],
        "domain": "web",
        "children": ["html", "css", "javascript", "dom_manipulation", "responsive_design"],
    },
    "html": {
        "display": "HTML",
        "aliases": ["html", "html5"],
        "parent": "web_development",
        "domain": "web",
    },
    "css": {
        "display": "CSS",
        "aliases": ["css", "css3", "sass", "scss", "tailwind", "tailwind css", "bootstrap"],
        "parent": "web_development",
        "domain": "web",
    },
    "dom_manipulation": {
        "display": "DOM Manipulation",
        "aliases": ["dom manipulation", "dom", "document object model"],
        "parent": "web_development",
        "domain": "web",
    },

    # --- Backend Development ---
    "backend_development": {
        "display": "Backend Development",
        "aliases": [
            "backend", "back-end", "backend development", "back-end development",
            "server-side development", "server side development", "server-side", "server side"
        ],
        "domain": "backend",
        "children": ["rest_apis", "server_side_development", "microservices", "api_design"],
    },
    "rest_apis": {
        "display": "REST APIs",
        "aliases": [
            "rest apis", "rest api", "restful apis", "restful api",
            "rest", "restful web services", "restful", "api development", "apis"
        ],
        "parent": "backend_development",
        "domain": "backend",
    },
    "server_side_development": {
        "display": "Server-side Development",
        "aliases": [
            "server-side development", "server side development",
            "server-side programming", "server side programming"
        ],
        "parent": "backend_development",
        "domain": "backend",
    },
    "microservices": {
        "display": "Microservices",
        "aliases": ["microservices", "microservice architecture", "distributed systems"],
        "parent": "backend_development",
        "domain": "backend",
    },

    # --- Software Engineering & DevOps ---
    "software_engineering": {
        "display": "Software Engineering",
        "aliases": [
            "software engineering", "software engineering principles",
            "software development", "software development practices"
        ],
        "domain": "software_engineering",
        "children": ["sdlc", "git", "testing", "debugging", "ci_cd", "version_control"],
    },
    "sdlc": {
        "display": "SDLC",
        "aliases": [
            "sdlc", "software development life cycle", "software development lifecycle",
            "software life cycle", "waterfall"
        ],
        "parent": "software_engineering",
        "domain": "software_engineering",
    },
    "git": {
        "display": "Git",
        "aliases": ["git", "github", "gitlab", "bitbucket", "version control", "vcs"],
        "parent": "software_engineering",
        "domain": "software_engineering",
    },
    "testing": {
        "display": "Testing",
        "aliases": [
            "testing", "unit testing", "integration testing", "system testing",
            "automated testing", "test-driven development", "tdd", "junit", "pytest"
        ],
        "parent": "software_engineering",
        "domain": "software_engineering",
    },
    "debugging": {
        "display": "Debugging",
        "aliases": ["debugging", "troubleshooting", "defect tracking", "root cause analysis"],
        "parent": "software_engineering",
        "domain": "software_engineering",
    },
    "ci_cd": {
        "display": "CI/CD",
        "aliases": ["ci/cd", "cicd", "continuous integration", "continuous deployment"],
        "parent": "software_engineering",
        "domain": "software_engineering",
    },

    # --- Operating Systems ---
    "operating_systems": {
        "display": "Operating Systems",
        "aliases": ["operating systems", "operating system", "os", "linux", "unix", "windows"],
        "domain": "operating_systems",
        "children": ["concurrency", "threads", "processes", "memory_management", "file_systems"],
    },
    "threads": {
        "display": "Threads & Concurrency",
        "aliases": ["threads", "concurrency", "multithreading", "multi-threading", "synchronization"],
        "parent": "operating_systems",
        "domain": "operating_systems",
    },

    # --- Cloud Computing ---
    "cloud_computing": {
        "display": "Cloud Computing",
        "aliases": ["cloud", "cloud computing", "cloud concepts", "basic cloud concepts", "cloud platforms"],
        "domain": "cloud",
        "children": ["basic_cloud_concepts", "aws", "azure", "gcp", "serverless"],
    },
    "basic_cloud_concepts": {
        "display": "Basic Cloud Concepts",
        "aliases": ["basic cloud concepts", "cloud concepts", "cloud fundamentals", "cloud basics"],
        "parent": "cloud_computing",
        "domain": "cloud",
    },
    "aws": {
        "display": "AWS",
        "aliases": ["aws", "amazon web services", "s3", "ec2", "lambda"],
        "parent": "cloud_computing",
        "domain": "cloud",
    },

    # --- Agile / Scrum ---
    "agile_scrum": {
        "display": "Agile / Scrum",
        "aliases": [
            "agile", "scrum", "agile/scrum", "agile methodology",
            "scrum methodology", "agile practices"
        ],
        "domain": "agile",
        "children": ["sprints", "user_stories", "team_collaboration", "standups", "kanban"],
    },
    "sprints": {
        "display": "Sprints",
        "aliases": ["sprints", "sprint planning", "sprint", "sprint review", "sprint retrospective"],
        "parent": "agile_scrum",
        "domain": "agile",
    },
    "user_stories": {
        "display": "User Stories",
        "aliases": ["user stories", "user story", "story pointing", "acceptance criteria"],
        "parent": "agile_scrum",
        "domain": "agile",
    },
    "team_collaboration": {
        "display": "Team Collaboration",
        "aliases": ["team collaboration", "collaboration", "cross-functional teams", "pair programming"],
        "parent": "agile_scrum",
        "domain": "agile",
    },
}


# ---------------------------------------------------------------------------
# Inverted Index for Fast Canonical Lookup
# ---------------------------------------------------------------------------
_ALIAS_TO_CANONICAL: Dict[str, str] = {}
for canonical_id, data in SKILL_TAXONOMY.items():
    _ALIAS_TO_CANONICAL[canonical_id] = canonical_id
    for alias in data.get("aliases", []):
        clean_alias = alias.strip().lower()
        _ALIAS_TO_CANONICAL[clean_alias] = canonical_id


def normalize_skill_name(skill_str: str) -> str:
    """
    Map an input skill string to its canonical taxonomy ID.
    If not in taxonomy, returns cleaned lowercase string.
    """
    clean = skill_str.strip().lower()
    if clean in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[clean]

    # Try punctuation-stripped variant
    stripped = re.sub(r"[^\w\s+#.]", "", clean).strip()
    if stripped in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[stripped]

    return clean


def get_skill_display_name(skill_str: str) -> str:
    """
    Return human-readable formatted display name for a skill.
    """
    canon = normalize_skill_name(skill_str)
    if canon in SKILL_TAXONOMY:
        return SKILL_TAXONOMY[canon].get("display", skill_str.title())
    return skill_str.strip()


def get_parent_skill(skill_str: str) -> Optional[str]:
    """
    Get canonical ID of the parent concept if one exists.
    """
    canon = normalize_skill_name(skill_str)
    if canon in SKILL_TAXONOMY:
        return SKILL_TAXONOMY[canon].get("parent")
    return None


def get_child_skills(skill_str: str) -> Set[str]:
    """
    Get set of canonical IDs of all sub-concepts for a given parent.
    """
    canon = normalize_skill_name(skill_str)
    if canon in SKILL_TAXONOMY and "children" in SKILL_TAXONOMY[canon]:
        return set(SKILL_TAXONOMY[canon]["children"])
    return set()


def is_child_of(child_str: str, parent_str: str) -> bool:
    """
    Returns True if child_str is a known sub-concept of parent_str.
    """
    c_canon = normalize_skill_name(child_str)
    p_canon = normalize_skill_name(parent_str)
    if c_canon == p_canon:
        return False

    parent_of_c = get_parent_skill(c_canon)
    if parent_of_c == p_canon:
        return True

    # Also check if p_canon has c_canon in children list
    if c_canon in get_child_skills(p_canon):
        return True

    return False


def get_skill_domain(skill_str: str) -> Optional[str]:
    """
    Returns high-level domain grouping (e.g. 'programming_languages', 'dsa', 'oop', 'database').
    """
    canon = normalize_skill_name(skill_str)
    if canon in SKILL_TAXONOMY:
        return SKILL_TAXONOMY[canon].get("domain")
    return None


def is_distinct_technology_taxonomic(skill_a: str, skill_b: str) -> bool:
    """
    Check if two skills represent distinct technologies that should never match.
    """
    ca = normalize_skill_name(skill_a)
    cb = normalize_skill_name(skill_b)
    if ca == cb:
        return False

    if (ca, cb) in DISTINCT_TECHNOLOGY_PAIRS or (cb, ca) in DISTINCT_TECHNOLOGY_PAIRS:
        return True

    # Two distinct programming languages must never match each other
    info_a = SKILL_TAXONOMY.get(ca, {})
    info_b = SKILL_TAXONOMY.get(cb, {})
    if info_a.get("is_language") and info_b.get("is_language"):
        return ca != cb

    return False


# ---------------------------------------------------------------------------
# OR / Alternative Requirement Parsing
# ---------------------------------------------------------------------------
def is_or_requirement(req_text: str) -> bool:
    """
    Detects if a requirement string defines an OR / alternative group.
    Examples:
        - "Java / Python / C++ / JavaScript"
        - "Java or Python or C++"
        - "either Java or Python"
    Excludes protected compound terms like "CI/CD".
    """
    cleaned = req_text.strip().lower()
    if cleaned in PROTECTED_COMPOUND_TERMS:
        return False

    if "/" in req_text:
        # Check that it's not simply "CI/CD" or "TCP/IP"
        parts = [p.strip() for p in req_text.split("/") if p.strip()]
        if len(parts) >= 2:
            # Check if at least one part is recognized or length indicates distinct terms
            return True

    if re.search(r"\b(?:or|either)\b", req_text, re.IGNORECASE):
        return True

    return False


def split_or_requirement(req_text: str) -> List[str]:
    """
    Split an OR requirement string into its constituent alternative options.
    Example:
        "Java / Python / C++ / JavaScript" -> ["Java", "Python", "C++", "JavaScript"]
        "Java or Python or C++" -> ["Java", "Python", "C++"]
    """
    cleaned = req_text.strip()
    if cleaned.lower() in PROTECTED_COMPOUND_TERMS:
        return [cleaned]

    if "/" in cleaned:
        options = [p.strip() for p in cleaned.split("/") if p.strip()]
        if len(options) >= 2:
            return options

    if re.search(r"\b(?:or|either)\b", cleaned, re.IGNORECASE):
        options = re.split(r"\b(?:or|either)\b", cleaned, flags=re.IGNORECASE)
        cleaned_options = [o.strip() for o in options if o.strip()]
        if len(cleaned_options) >= 2:
            return cleaned_options

    return [cleaned]


def detect_or_chains_in_jd(raw_jd_text: str) -> List[Set[str]]:
    """
    Scans raw JD text to detect alternative chains such as:
    'Java / Python / C++ / JavaScript'
    Returns a list of sets containing the canonical skill IDs that belong together in an OR group.
    """
    if not raw_jd_text:
        return []

    or_groups: List[Set[str]] = []
    # Match sequences of skills separated by /
    # e.g. Java / Python / C++ / JavaScript
    slash_patterns = re.findall(r"([A-Za-z0-9#+.]+(?:\s*/\s*[A-Za-z0-9#+.]+)+)", raw_jd_text)
    for pattern in slash_patterns:
        low = pattern.strip().lower()
        if low in PROTECTED_COMPOUND_TERMS:
            continue
        parts = [p.strip() for p in pattern.split("/") if p.strip()]
        canon_set = set()
        for p in parts:
            canon = normalize_skill_name(p)
            if canon in SKILL_TAXONOMY or len(p) >= 2:
                canon_set.add(canon)
        if len(canon_set) >= 2:
            or_groups.append(canon_set)

    return or_groups


# ---------------------------------------------------------------------------
# Text Mention Scanner (Detects explicitly evidenced concepts in raw text)
# ---------------------------------------------------------------------------
def scan_text_for_skills(text: str) -> Set[str]:
    """
    Scans raw text (such as candidate resume or project details) for explicit
    mentions of canonical taxonomy concepts and sub-concepts.
    Ensures that bullet points mentioning 'arrays', 'linked lists', 'trees',
    'graphs', 'dynamic programming', etc. are captured as explicit evidence.
    """
    if not text:
        return set()

    found_skills: Set[str] = set()
    low_text = text.lower()

    for canon_id, data in SKILL_TAXONOMY.items():
        # Check all aliases with word boundary protection
        for alias in data.get("aliases", [canon_id]):
            # Escape regex special characters like ++, #, etc.
            escaped = re.escape(alias)
            # Ensure word boundaries (with lookbehind/lookahead for special characters like C++)
            pattern = rf"(?:\b|(?<=[^a-zA-Z0-9])){escaped}(?:\b|(?=[^a-zA-Z0-9]))"
            if re.search(pattern, low_text):
                found_skills.add(data.get("display", canon_id))
                break

    return found_skills
