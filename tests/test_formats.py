from cta_client.formats import (
    best_of_from_event_name,
    event_id_from_room,
    format_from_event_name,
    format_from_room,
    is_excluded_event,
    super_format_from_game_info,
)


def test_draft_events_are_excluded_and_super_format_is_independent():
    assert is_excluded_event("PremierDraft_FRA_20260929")
    assert is_excluded_event("Sealed_FRA_20260929")
    assert not is_excluded_event("Constructed_BestOf3")
    assert not is_excluded_event("DirectGame")
    assert not is_excluded_event("Traditional_Ladder")
    assert super_format_from_game_info("SuperFormat_Constructed") == "constructed"
    assert super_format_from_game_info("SuperFormat_Limited") == "limited"


def test_constructed_challenge_queues_are_not_formats():
    assert format_from_event_name("Constructed_BestOf3") is None
    assert format_from_event_name("Constructed_BestOf1") is None
    assert format_from_event_name("DirectGame") is None
    assert format_from_event_name("DirectChallenge") is None
    assert format_from_event_name("Traditional_Ladder") is None


def test_constructed_best_of_three_is_bo3_and_direct_game_does_not_guess():
    assert best_of_from_event_name("Constructed_BestOf3") == 3
    assert best_of_from_event_name("Constructed_BestOf1") == 1
    assert best_of_from_event_name("Traditional_Ladder") == 3
    assert best_of_from_event_name("DirectGame") is None
    assert best_of_from_event_name("DirectChallenge") is None


def test_event_id_falls_back_to_reserved_players():
    assert (
        event_id_from_room(
            {
                "reservedPlayers": [
                    {"playerName": "Tester", "eventId": "Constructed_BestOf3"},
                    {"playerName": "Opponent", "eventId": "Constructed_BestOf3"},
                ]
            },
            screen_name="Tester",
        )
        == "Constructed_BestOf3"
    )


def test_room_format_reads_client_metadata():
    assert (
        format_from_room(
            {
                "eventId": "DirectGame",
                "clientMetadata": {"Format": "Standard"},
            }
        )
        == "standard"
    )
    assert (
        format_from_room(
            {
                "reservedPlayers": [
                    {
                        "playerName": "Tester",
                        "eventId": "Constructed_BestOf3",
                        "clientMetadata": [{"name": "Format", "value": "Standard"}],
                    }
                ]
            }
        )
        == "standard"
    )
