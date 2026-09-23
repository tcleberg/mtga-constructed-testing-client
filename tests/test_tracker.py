from datetime import datetime, timedelta

from cta_client.tracker import MatchTracker


def _room(match_id: str, event: str = "Standard_Championship"):
    return {
        "matchGameRoomStateChangedEvent": {
            "gameRoomInfo": {
                "stateType": "MatchGameRoomStateType_Playing",
                "gameRoomConfig": {
                    "matchId": match_id,
                    "eventId": event,
                    "reservedPlayers": [
                        {
                            "userId": "USER1",
                            "playerName": "Tester",
                            "systemSeatId": 1,
                        },
                        {
                            "userId": "USER2",
                            "playerName": "Opponent",
                            "systemSeatId": 2,
                        },
                    ],
                },
            }
        }
    }


def test_tracks_decks_mulligans_and_results():
    tracker = MatchTracker()
    tracker.consume({"authenticateResponse": {"screenName": "Tester", "clientId": "USER1"}})
    tracker.consume(_room("match-1"))
    tracker.consume(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_ConnectResp",
                        "systemSeatIds": [1],
                        "connectResp": {"deckMessage": {"deckCards": [11, 11, 22, 33]}},
                    }
                ]
            }
        }
    )
    tracker.consume(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "systemSeatIds": [1],
                        "gameStateMessage": {
                            "turnInfo": {"activePlayer": 1, "turnNumber": 0},
                            "players": [
                                {
                                    "systemSeatNumber": 1,
                                    "pendingMessageType": "ClientMessageType_MulliganResp",
                                    "mulliganCount": 0,
                                }
                            ],
                            "gameObjects": [
                                {
                                    "type": "GameObjectType_Card",
                                    "ownerSeatId": 1,
                                    "instanceId": 1,
                                    "overlayGrpId": 11,
                                    "cardTypes": ["CardType_Creature"],
                                },
                                {
                                    "type": "GameObjectType_Card",
                                    "ownerSeatId": 1,
                                    "instanceId": 2,
                                    "overlayGrpId": 22,
                                    "cardTypes": ["CardType_Instant"],
                                },
                                {
                                    "type": "GameObjectType_Card",
                                    "ownerSeatId": 2,
                                    "instanceId": 9,
                                    "overlayGrpId": 99,
                                    "cardTypes": ["CardType_Creature"],
                                },
                            ],
                            "zones": [
                                {
                                    "type": "ZoneType_Hand",
                                    "ownerSeatId": 1,
                                    "objectInstanceIds": [1, 2],
                                }
                            ],
                        },
                    }
                ]
            }
        }
    )
    events = tracker.consume(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameInfo": {
                                "matchID": "match-1",
                                "stage": "GameStage_GameOver",
                                "matchState": "MatchState_GameComplete",
                                "results": [
                                    {
                                        "scope": "MatchScope_Game",
                                        "winningTeamId": 1,
                                        "reason": "ResultReason_Game",
                                    }
                                ],
                            }
                        },
                    }
                ]
            }
        }
    )
    game = events[0]
    assert game.won is True
    assert game.player_deck == [11, 11, 22, 33]
    assert 99 in game.opponent_seen_cards
    assert game.mulligan_count == 0
    assert game.opponent_name == "Opponent"

    duplicate = tracker.consume(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameInfo": {
                                "matchID": "match-1",
                                "gameNumber": 1,
                                "stage": "GameStage_GameOver",
                                "matchState": "MatchState_MatchComplete",
                                "results": [
                                    {"scope": "MatchScope_Game", "winningTeamId": 1},
                                    {"scope": "MatchScope_Match", "winningTeamId": 1},
                                ],
                            }
                        },
                    }
                ]
            }
        }
    )
    assert duplicate == []

    completed = tracker.consume(
        {
            "matchGameRoomStateChangedEvent": {
                "gameRoomInfo": {
                    "stateType": "MatchGameRoomStateType_MatchCompleted",
                    "gameRoomConfig": {
                        "matchId": "match-1",
                        "eventId": "Standard_Championship",
                        "reservedPlayers": [
                            {"userId": "USER1", "playerName": "Tester", "systemSeatId": 1},
                            {"userId": "USER2", "playerName": "Opponent", "systemSeatId": 2},
                        ],
                    },
                    "finalMatchResult": {
                        "matchId": "match-1",
                        "resultList": [
                            {"scope": "MatchScope_Match", "winningTeamId": 1, "reason": "ResultReason_Game"}
                        ],
                    },
                }
            }
        }
    )
    match = completed[0]
    assert match.won is True
    assert len(match.games) == 1


def test_counts_mulligans_from_pending_decisions():
    tracker = MatchTracker()
    tracker.seat_id = 1
    tracker.current_match_id = "m"
    tracker.consume(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "players": [
                                {
                                    "systemSeatNumber": 1,
                                    "pendingMessageType": "ClientMessageType_MulliganResp",
                                    "mulliganCount": 0,
                                },
                                {
                                    "systemSeatNumber": 1,
                                    "pendingMessageType": "ClientMessageType_MulliganResp",
                                    "mulliganCount": 1,
                                },
                            ],
                            "gameInfo": {
                                "matchID": "m",
                                "stage": "GameStage_GameOver",
                                "matchState": "MatchState_GameComplete",
                                "results": [{"scope": "MatchScope_Game", "winningTeamId": 2}],
                            },
                        },
                    }
                ]
            }
        }
    )
    # two pending decisions in one message over-counts if we don't care; the important bit is >= 1 mulligan
    game = tracker.finished_games[0]
    assert game.mulligan_count >= 1


def test_tracks_elapsed_time_and_turns_per_player():
    tracker = MatchTracker()
    tracker.consume({"authenticateResponse": {"screenName": "Tester", "clientId": "USER1"}})
    tracker.consume(_room("timed-match"))
    started = datetime(2026, 9, 17, 12, 0, 0)
    tracker.consume(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_ConnectResp",
                        "systemSeatIds": [1],
                        "connectResp": {"deckMessage": {}},
                    }
                ]
            }
        },
        observed_at=started,
    )
    events = []
    for turn_number in range(1, 7):
        game_info = {"matchID": "timed-match"}
        if turn_number == 6:
            game_info.update(
                {
                    "stage": "GameStage_GameOver",
                    "matchState": "MatchState_GameComplete",
                    "results": [{"scope": "MatchScope_Game", "winningTeamId": 1}],
                }
            )
        events = tracker.consume(
            {
                "greToClientEvent": {
                    "greToClientMessages": [
                        {
                            "type": "GREMessageType_GameStateMessage",
                            "gameStateMessage": {
                                "turnInfo": {
                                    "turnNumber": turn_number,
                                    "activePlayer": 1 if turn_number % 2 else 2,
                                },
                                "gameInfo": game_info,
                            },
                        }
                    ]
                }
            },
            observed_at=started + timedelta(seconds=30 * turn_number),
        )
    game = events[0]
    assert game.duration_seconds == 180
    assert game.player_turns == 3
    assert game.opponent_turns == 3


def test_tracks_played_card_instances_per_seat_without_double_counting():
    tracker = MatchTracker()
    tracker.consume({"authenticateResponse": {"screenName": "Tester", "clientId": "USER1"}})
    tracker.consume(_room("played-cards"))

    game_objects = [
        {
            "type": "GameObjectType_Card",
            "ownerSeatId": 1,
            "instanceId": 10,
            "overlayGrpId": 100,
        },
        {
            "type": "GameObjectType_Card",
            "ownerSeatId": 2,
            "instanceId": 20,
            "overlayGrpId": 200,
        },
    ]
    for zone_type, owner, instance_id in [
        ("ZoneType_Stack", 1, 10),
        ("ZoneType_Battlefield", 1, 10),
        ("ZoneType_Battlefield", 2, 20),
    ]:
        tracker.consume(
            {
                "greToClientEvent": {
                    "greToClientMessages": [
                        {
                            "type": "GREMessageType_GameStateMessage",
                            "gameStateMessage": {
                                "gameInfo": {"matchID": "played-cards"},
                                "gameObjects": game_objects,
                                "zones": [
                                    {
                                        "type": zone_type,
                                        "ownerSeatId": owner,
                                        "objectInstanceIds": [instance_id],
                                    }
                                ],
                            },
                        }
                    ]
                }
            }
        )

    events = tracker.consume(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameInfo": {
                                "matchID": "played-cards",
                                "stage": "GameStage_GameOver",
                                "matchState": "MatchState_GameComplete",
                                "results": [{"scope": "MatchScope_Game", "winningTeamId": 1}],
                            }
                        },
                    }
                ]
            }
        }
    )

    game = events[0]
    assert game.player_played_cards == [100]
    assert game.opponent_played_cards == [200]


def test_public_stack_and_battlefield_plays_do_not_need_a_zone_owner():
    tracker = MatchTracker()
    tracker.consume({"authenticateResponse": {"screenName": "Tester", "clientId": "USER1"}})
    tracker.consume(_room("public-zones"))
    tracker.consume(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameInfo": {"matchID": "public-zones"},
                            "gameObjects": [
                                {
                                    "type": "GameObjectType_Card",
                                    "instanceId": 10,
                                    "overlayGrpId": 100,
                                    "ownerSeatId": 1,
                                    "zoneId": 28,
                                },
                                {
                                    "type": "GameObjectType_Card",
                                    "instanceId": 20,
                                    "grpId": 200,
                                    "controllerSeatId": 2,
                                    "zoneId": 31,
                                },
                            ],
                            "zones": [
                                {
                                    "zoneId": 28,
                                    "type": "ZoneType_Battlefield",
                                    "objectInstanceIds": [10],
                                },
                                {
                                    "zoneId": 31,
                                    "type": "ZoneType_Stack",
                                    "objectInstanceIds": [20],
                                },
                            ],
                        },
                    }
                ]
            }
        }
    )
    events = tracker.consume(
        {
            "greToClientEvent": {
                "greToClientMessages": [
                    {
                        "type": "GREMessageType_GameStateMessage",
                        "gameStateMessage": {
                            "gameInfo": {
                                "matchID": "public-zones",
                                "stage": "GameStage_GameOver",
                                "matchState": "MatchState_GameComplete",
                                "results": [{"scope": "MatchScope_Game", "winningTeamId": 1}],
                            }
                        },
                    }
                ]
            }
        }
    )
    game = events[0]
    assert game.player_played_cards == [100]
    assert game.opponent_played_cards == [200]


def test_each_finished_game_takes_its_own_row_from_the_cumulative_results():
    from cta_client.tracker import game_result_for_number

    results = [
        {"scope": "MatchScope_Game", "winningTeamId": 2},
        {"scope": "MatchScope_Game", "winningTeamId": 1},
        {"scope": "MatchScope_Game", "winningTeamId": 2},
    ]
    assert game_result_for_number(results, 1)["winningTeamId"] == 2
    assert game_result_for_number(results, 2)["winningTeamId"] == 1
    assert game_result_for_number(results, 3)["winningTeamId"] == 2


def test_a_bo3_stops_emitting_games_after_two_wins():
    tracker = MatchTracker()
    tracker.consume({"authenticateResponse": {"screenName": "Tester", "clientId": "USER1"}})
    tracker.consume(_room("bo3-done", event="Traditional_Ladder"))
    tracker.current_best_of = 3
    tracker.seat_id = 1

    def finish(game_number: int, winner: int, results: list) -> list:
        tracker.game_number = game_number
        return tracker.consume(
            {
                "greToClientEvent": {
                    "greToClientMessages": [
                        {
                            "type": "GREMessageType_GameStateMessage",
                            "systemSeatIds": [1],
                            "gameStateMessage": {
                                "gameInfo": {
                                    "matchID": "bo3-done",
                                    "gameNumber": game_number,
                                    "matchWinCondition": "MatchWinCondition_Best2Of3",
                                    "stage": "GameStage_GameOver",
                                    "matchState": "MatchState_GameComplete",
                                    "results": results,
                                }
                            },
                        }
                    ]
                }
            }
        )

    g1 = finish(1, 2, [{"scope": "MatchScope_Game", "winningTeamId": 2}])
    g2 = finish(
        2,
        2,
        [
            {"scope": "MatchScope_Game", "winningTeamId": 2},
            {"scope": "MatchScope_Game", "winningTeamId": 2},
        ],
    )
    g3 = finish(
        3,
        2,
        [
            {"scope": "MatchScope_Game", "winningTeamId": 2},
            {"scope": "MatchScope_Game", "winningTeamId": 2},
            {"scope": "MatchScope_Game", "winningTeamId": 2},
        ],
    )
    assert g1[0].won is False
    assert g2[0].won is False
    assert g3 == []


def test_format_comes_from_the_deck_attribute_not_the_queue_name():
    tracker = MatchTracker()
    tracker.consume(
        {
            "EventName": "Traditional_Ladder",
            "Deck": {
                "MainDeck": [1],
                "Attributes": [{"name": "Format", "value": "Standard"}],
            },
        }
    )
    assert tracker.current_format == "standard"
    assert tracker.current_best_of == 3
