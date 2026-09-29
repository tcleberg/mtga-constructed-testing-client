from cta_client.instance import (
    ACTION_FOCUS,
    ACTION_TAKEOVER,
    ACTION_YIELD,
    decode_message,
    encode_message,
    takeover_action,
)


def test_newer_client_takes_over_a_silent_or_older_peer():
    assert takeover_action("0.3.5", None) == ACTION_TAKEOVER
    assert takeover_action("0.3.5", "") == ACTION_TAKEOVER
    assert takeover_action("0.3.5", "0.3.2") == ACTION_TAKEOVER
    assert takeover_action("v0.3.5", "0.3.4") == ACTION_TAKEOVER


def test_older_client_yields_to_a_newer_peer():
    assert takeover_action("0.3.2", "0.3.5") == ACTION_YIELD
    assert takeover_action("0.3.4", "v0.3.5") == ACTION_YIELD


def test_same_version_focuses_instead_of_fighting():
    assert takeover_action("0.3.5", "0.3.5") == ACTION_FOCUS
    assert takeover_action("0.3.5", "v0.3.5") == ACTION_FOCUS


def test_instance_messages_round_trip_as_json_lines():
    encoded = encode_message({"cmd": "probe", "version": "0.3.5"})
    assert encoded.endswith(b"\n")
    assert decode_message(encoded.strip()) == {"cmd": "probe", "version": "0.3.5"}
