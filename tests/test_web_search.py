from src.tools.web_search import source_trust_tier


def test_official_subdomains_are_tier_one():
    assert source_trust_tier("https://investor.tsmc.com/english/quarterly-results") == 1
    assert source_trust_tier("https://www.sec.gov/Archives/report.htm") == 1


def test_reputable_reporting_is_tier_two():
    assert source_trust_tier("https://www.reuters.com/technology/chips/") == 2


def test_unknown_and_deceptive_domains_are_not_promoted():
    assert source_trust_tier("https://example.com/post") == 3
    assert source_trust_tier("https://tsmc.com.attacker.example/post") == 3
