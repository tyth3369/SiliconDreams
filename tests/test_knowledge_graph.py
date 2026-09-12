from src.knowledge_graph import KnowledgeGraph


def test_graph_is_closed_typed_and_collision_free():
    graph = KnowledgeGraph()
    report = graph.audit()
    assert report["node_types"]["term"] == 100
    assert report["node_types"]["company"] < 151
    assert report["missing_endpoints"] == []
    assert report["missing_inverse_edges"] == []
    assert report["alias_collisions"] == {}


def test_term_and_company_aliases_resolve_to_canonical_entities():
    graph = KnowledgeGraph()
    assert graph.resolve("BSPDN")["name"] == "背面供电"
    assert graph.resolve("平均销售价格")["name"] == "ASP (平均销售价格)"
    assert graph.resolve("NXP")["name"] == "恩智浦"
    assert graph.resolve("恩智浦 (NXP)")["name"] == "恩智浦"


def test_related_edges_are_bidirectional_and_stub_concepts_close_dangling_refs():
    graph = KnowledgeGraph()
    advanced = {node["name"] for node in graph.neighbors("先进制程", "related_to")}
    assert {"EUV光刻", "FinFET", "GAA"} <= advanced
    inverse = {node["name"] for node in graph.neighbors("GAA", "related_to")}
    assert "先进制程" in inverse
    leakage = graph.resolve("漏电流")
    assert leakage["type"] == "concept"


def test_associated_company_edges_use_normalized_company_names():
    graph = KnowledgeGraph()
    nxp_terms = {node["name"] for node in graph.neighbors("NXP", "associated_with")}
    assert nxp_terms
    assert all(node["name"] != "恩智浦 (NXP)" for node in graph.nodes.values())
