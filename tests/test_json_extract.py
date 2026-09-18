from cta_client.json_extract import extract_json_objects, iter_log_entries


def test_extracts_multiple_json_objects_and_nested_request():
    text = """
    ==> EventSetDeck {"id":"abc","request":"{\\"EventName\\":\\"Traditional_Ladder\\",\\"Deck\\":{\\"MainDeck\\":[{\\"cardId\\":1,\\"quantity\\":2}]}}"}
    leftover
    {"greToClientEvent":{"greToClientMessages":[{"type":"GREMessageType_ConnectResp"}]}}
    """
    objects = extract_json_objects(text)
    assert objects[0]["request"]["EventName"] == "Traditional_Ladder"
    assert objects[1]["greToClientEvent"]["greToClientMessages"][0]["type"] == "GREMessageType_ConnectResp"


def test_iter_log_entries_splits_on_headers():
    text = """[UnityCrossThreadLogger]9/17/2026 1:00:00 PM
==> EventJoin {"EventName":"Standard_Championship"}
[UnityCrossThreadLogger]9/17/2026 1:00:01 PM
{"authenticateResponse":{"screenName":"Tester","clientId":"ABC"}}
<== RankGetCombinedRankInfo(uuid)
{"constructedClass":"Mythic"}
"""
    entries = list(iter_log_entries(text))
    assert len(entries) == 3
    assert entries[0].direction == "request"
    assert entries[2].api_name == "RankGetCombinedRankInfo"
    assert entries[1].json_objects[0]["authenticateResponse"]["screenName"] == "Tester"
    assert entries[0].timestamp is not None
    assert entries[0].timestamp.hour == 13
