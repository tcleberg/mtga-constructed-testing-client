from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _card_id(obj: dict[str, Any]) -> int | None:
    for key in ("overlayGrpId", "grpId", "cardId"):
        value = obj.get(key)
        if isinstance(value, int) or isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _expand(cards: Any) -> list[int]:
    if not cards:
        return []
    if isinstance(cards, list) and cards and isinstance(cards[0], dict):
        result: list[int] = []
        for item in cards:
            card_id = item.get("cardId") or item.get("grpId") or item.get("CardId")
            if card_id is not None:
                result.extend([int(card_id)] * int(item.get("quantity") or item.get("Quantity") or 1))
        return result
    return [int(card) for card in cards if isinstance(card, int) or str(card).isdigit()]


@dataclass
class CompletedGame:
    match_id: str
    event_name: str | None
    game_number: int
    won: bool | None
    win_reason: str | None
    on_play: bool | None
    turns: int
    duration_seconds: int | None
    player_turns: int
    opponent_turns: int
    player_seat: int | None
    player_name: str | None
    player_arena_id: str | None
    opponent_name: str | None
    opponent_arena_id: str | None
    player_deck: list[int]
    player_sideboard: list[int]
    opponent_seen_cards: list[int]
    player_played_cards: list[int]
    opponent_played_cards: list[int]
    opening_hand: list[int]
    mulligans: list[list[int]]
    mulligan_count: int
    opponent_mulligan_count: int
    card_types_seen: dict[str, int]


@dataclass
class CompletedMatch:
    match_id: str
    event_name: str | None
    won: bool | None
    win_reason: str | None
    player_name: str | None
    player_arena_id: str | None
    opponent_name: str | None
    opponent_arena_id: str | None
    games: list[CompletedGame]


@dataclass
class Identity:
    screen_name: str | None = None
    arena_user_id: str | None = None


class MatchTracker:
    def __init__(self) -> None:
        self.identity = Identity()
        self.current_match_id: str | None = None
        self.current_event_id: str | None = None
        self.seat_id: int | None = None
        self.screen_names: dict[int, str] = {}
        self.arena_ids: dict[int, str] = {}
        self.submitted_maindeck: list[int] = []
        self.submitted_sideboard: list[int] = []
        self.game_maindeck: list[int] = []
        self.game_sideboard: list[int] = []
        self.game_number = 1
        self.finished_games: list[CompletedGame] = []
        self._emitted: set[tuple[str, int]] = set()
        self._reset_game(keep_match=True)

    def consume(self, obj: dict[str, Any], api_name: str | None = None, observed_at: datetime | None = None):
        if observed_at is not None:
            self.observed_at = observed_at
        emitted: list[CompletedGame | CompletedMatch | Identity] = []
        if "authenticateResponse" in obj:
            auth = obj["authenticateResponse"]
            self.identity.screen_name = auth.get("screenName") or self.identity.screen_name
            self.identity.arena_user_id = auth.get("clientId") or auth.get("sessionId") or self.identity.arena_user_id
            emitted.append(self.identity)
        if api_name and "SetDeck" in api_name or "EventName" in obj and "Deck" in obj:
            self._set_deck(obj)
        if "matchGameRoomStateChangedEvent" in obj:
            emitted.extend(self._room(obj["matchGameRoomStateChangedEvent"]))
        for message in (obj.get("greToClientEvent") or {}).get("greToClientMessages") or []:
            emitted.extend(self._gre(message))
        if "clientToGreMessage" in obj:
            self._client_gre(obj["clientToGreMessage"])
        return emitted

    def _set_deck(self, obj: dict[str, Any]) -> None:
        payload = obj.get("payload") or obj.get("request") or obj
        if isinstance(payload, str):
            return
        deck = payload.get("Deck") or payload.get("deck") or {}
        self.current_event_id = payload.get("EventName") or obj.get("EventName") or self.current_event_id
        self.submitted_maindeck = _expand(deck.get("MainDeck") or deck.get("deckCards"))
        self.submitted_sideboard = _expand(deck.get("Sideboard") or deck.get("sideboardCards"))

    def _room(self, event: dict[str, Any]):
        info = event.get("gameRoomInfo") or {}
        config = info.get("gameRoomConfig") or {}
        match_id = config.get("matchId") or (info.get("finalMatchResult") or {}).get("matchId")
        self.current_event_id = config.get("eventId") or config.get("eventName") or self.current_event_id
        if match_id and match_id != self.current_match_id:
            if self.current_match_id is not None:
                self._reset_game(False)
            self.current_match_id, self.game_number = match_id, 1
        for player in config.get("reservedPlayers") or []:
            if player.get("systemSeatId") is None:
                continue
            seat = int(player["systemSeatId"])
            name = (player.get("playerName") or "").split("#")[0]
            self.screen_names[seat], self.arena_ids[seat] = name, player.get("userId")
            if self.identity.screen_name and name == self.identity.screen_name:
                self.seat_id = seat
                self.identity.arena_user_id = player.get("userId") or self.identity.arena_user_id
        if info.get("stateType") == "MatchGameRoomStateType_MatchCompleted":
            return self._complete_match(info.get("finalMatchResult") or {})
        return []

    def _gre(self, message: dict[str, Any]):
        seats = message.get("systemSeatIds") or []
        if seats:
            self.seat_id = int(seats[0])
        if message.get("type") == "GREMessageType_ConnectResp":
            self.started_at = self.started_at or self.observed_at
            deck = (message.get("connectResp") or {}).get("deckMessage") or {}
            self.game_maindeck, self.game_sideboard = _expand(deck.get("deckCards")), _expand(deck.get("sideboardCards"))
        elif message.get("type") in {"GREMessageType_GameStateMessage", "GREMessageType_QueuedGameStateMessage"}:
            return self._state(message.get("gameStateMessage") or {})
        return []

    def _client_gre(self, message: dict[str, Any]) -> None:
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else message
        if payload.get("type") != "ClientMessageType_MulliganResp" and "mulliganResp" not in payload or self.seat_id is None:
            return
        self.hand_counts[self.seat_id] += 1
        if self.hands.get(self.seat_id):
            self.drawn_hands[self.seat_id].append(list(self.hands[self.seat_id]))

    def _state(self, state: dict[str, Any]):
        self.started_at = self.started_at or self.observed_at
        info, turn = state.get("gameInfo") or {}, state.get("turnInfo") or {}
        self.current_match_id = info.get("matchID") or info.get("matchId") or self.current_match_id
        self.game_number = int(info.get("gameNumber") or self.game_number)
        number = int(turn.get("turnNumber") or 0)
        self.turn_count = max(self.turn_count, number)
        if turn.get("activePlayer") is not None and number:
            self.turns_by_seat[int(turn["activePlayer"])].add(number)
        players = state.get("players") or []
        for player in players:
            seat = player.get("systemSeatNumber")
            if seat is not None and player.get("turnNumber") is not None:
                self.reported_turns[int(seat)] = max(self.reported_turns[int(seat)], int(player["turnNumber"]))
        for obj in state.get("gameObjects") or []:
            owner, instance, card = obj.get("ownerSeatId"), obj.get("instanceId"), _card_id(obj)
            if owner is None or instance is None or card is None:
                continue
            self.objects[int(owner)][int(instance)] = card
            if obj.get("cardTypes"):
                self.object_types[card] = [str(value).replace("CardType_", "") for value in obj["cardTypes"]]
        for zone in state.get("zones") or []:
            if zone.get("ownerSeatId") is None:
                continue
            owner, ids = int(zone["ownerSeatId"]), [int(value) for value in zone.get("objectInstanceIds") or []]
            if zone.get("type") in {"ZoneType_Stack", "ZoneType_Battlefield"}:
                self.played[owner].update(ids)
            if zone.get("type") == "ZoneType_Hand":
                self.hands[owner] = [self.objects[owner][value] for value in ids if value in self.objects[owner]]
        for player in players:
            if player.get("pendingMessageType") != "ClientMessageType_MulliganResp":
                continue
            seat, count = int(player["systemSeatNumber"]), int(player.get("mulliganCount") or 0)
            self.hand_counts[seat] += 1
            if count == len(self.drawn_hands[seat]):
                self.drawn_hands[seat].append(list(self.hands.get(seat) or []))
        if not self.opening_hand and turn.get("phase") == "Phase_Beginning" and number == 1:
            self.opening_hand = {seat: list(cards) for seat, cards in self.hands.items()}
        if info.get("stage") == "GameStage_GameOver" and info.get("matchState") == "MatchState_GameComplete":
            results = info.get("results") or []
            result = next((value for value in results if value.get("scope") == "MatchScope_Game"), results[0] if results else {})
            return self._complete_game(result)
        return []

    def _complete_game(self, result: dict[str, Any]):
        if not self.current_match_id or (self.current_match_id, self.game_number) in self._emitted:
            return []
        game = self._build_game(result)
        self._emitted.add((self.current_match_id, self.game_number))
        self.finished_games.append(game)
        self.game_number += 1
        self._reset_game(True)
        return [game]

    def _build_game(self, result: dict[str, Any]) -> CompletedGame:
        seat = self.seat_id
        opponent = next((value for value in self.screen_names if value != seat), None)
        winner = result.get("winningTeamId")
        deck = self.game_maindeck or self.submitted_maindeck
        duration = int((self.observed_at - self.started_at).total_seconds()) if self.started_at and self.observed_at else None
        types: defaultdict[str, int] = defaultdict(int)
        for card in deck:
            for card_type in self.object_types.get(card, []):
                types[card_type] += 1
        return CompletedGame(
            self.current_match_id or "", self.current_event_id, self.game_number,
            int(winner) == seat if winner is not None and seat is not None else None,
            result.get("reason"), self.starting_team == seat if self.starting_team is not None else None,
            self.turn_count, duration, self._turns(seat), self._turns(opponent), seat,
            self.screen_names.get(seat) if seat else self.identity.screen_name,
            self.arena_ids.get(seat) if seat else self.identity.arena_user_id,
            self.screen_names.get(opponent), self.arena_ids.get(opponent), list(deck),
            list(self.game_sideboard or self.submitted_sideboard),
            list(self.objects.get(opponent, {}).values()), self._played(seat), self._played(opponent),
            list(self.opening_hand.get(seat or -1) or []), list((self.drawn_hands.get(seat or -1) or [])[:-1]),
            max(0, self.hand_counts.get(seat or -1, 1) - 1),
            max(0, self.hand_counts.get(opponent or -1, 1) - 1), dict(types),
        )

    def _complete_match(self, final: dict[str, Any]):
        if not self.current_match_id:
            return []
        result = next((value for value in final.get("resultList") or [] if value.get("scope") == "MatchScope_Match"), {})
        winner = result.get("winningTeamId")
        match = CompletedMatch(
            self.current_match_id, self.current_event_id,
            int(winner) == self.seat_id if winner is not None and self.seat_id is not None else None,
            result.get("reason"), self.screen_names.get(self.seat_id), self.arena_ids.get(self.seat_id),
            self._opponent_name(), self._opponent_id(), list(self.finished_games),
        )
        self._reset_game(False)
        self.finished_games, self.game_number, self.current_match_id = [], 1, None
        return [match]

    def _turns(self, seat: int | None) -> int:
        return 0 if seat is None else max(len(self.turns_by_seat.get(seat, set())), self.reported_turns.get(seat, 0))

    def _played(self, seat: int | None) -> list[int]:
        if seat is None:
            return []
        return [self.objects[seat][key] for key in sorted(self.played.get(seat, set())) if key in self.objects[seat]]

    def _opponent_name(self):
        return next((name for seat, name in self.screen_names.items() if seat != self.seat_id), None)

    def _opponent_id(self):
        return next((value for seat, value in self.arena_ids.items() if seat != self.seat_id), None)

    def _reset_game(self, keep_match: bool) -> None:
        self.objects: dict[int, dict[int, int]] = defaultdict(dict)
        self.played: dict[int, set[int]] = defaultdict(set)
        self.object_types: dict[int, list[str]] = {}
        self.hands: dict[int, list[int]] = defaultdict(list)
        self.drawn_hands: dict[int, list[list[int]]] = defaultdict(list)
        self.opening_hand: dict[int, list[int]] = {}
        self.hand_counts: dict[int, int] = defaultdict(int)
        self.turn_count = 0
        self.turns_by_seat: dict[int, set[int]] = defaultdict(set)
        self.reported_turns: dict[int, int] = defaultdict(int)
        self.started_at: datetime | None = None
        self.observed_at: datetime | None = None
        self.starting_team: int | None = None
        if not keep_match:
            self.game_maindeck, self.game_sideboard = [], []
            self.screen_names, self.arena_ids, self._emitted = {}, {}, set()
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _card_id(game_object: dict[str, Any]) -> int | None:
    for key in ("overlayGrpId", "grpId", "cardId"):
        value = game_object.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _expand_card_list(cards: Any) -> list[int]:
    if not cards:
        return []
    if isinstance(cards, list) and cards and isinstance(cards[0], dict):
        expanded: list[int] = []
        for item in cards:
            card_id = item.get("cardId") or item.get("grpId") or item.get("CardId")
            qty = int(item.get("quantity") or item.get("Quantity") or 1)
            if card_id is None:
                continue
            expanded.extend([int(card_id)] * qty)
        return expanded
    result: list[int] = []
    for item in cards:
        if isinstance(item, int):
            result.append(item)
        elif isinstance(item, str) and item.isdigit():
            result.append(int(item))
    return result


@dataclass
class CompletedGame:
    match_id: str
    event_name: str | None
    game_number: int
    won: bool | None
    win_reason: str | None
    on_play: bool | None
    turns: int
    duration_seconds: int | None
    player_turns: int
    opponent_turns: int
    player_seat: int | None
    player_name: str | None
    player_arena_id: str | None
    opponent_name: str | None
    opponent_arena_id: str | None
    player_deck: list[int]
    player_sideboard: list[int]
    opponent_seen_cards: list[int]
    player_played_cards: list[int]
    opponent_played_cards: list[int]
    opening_hand: list[int]
    mulligans: list[list[int]]
    mulligan_count: int
    opponent_mulligan_count: int
    card_types_seen: dict[str, int]


@dataclass
class CompletedMatch:
    match_id: str
    event_name: str | None
    won: bool | None
    win_reason: str | None
    player_name: str | None
    player_arena_id: str | None
    opponent_name: str | None
    opponent_arena_id: str | None
    games: list[CompletedGame]


@dataclass
class Identity:
    screen_name: str | None = None
    arena_user_id: str | None = None


class MatchTracker:
    def __init__(self) -> None:
        self.identity = Identity()
        self.current_match_id: str | None = None
        self.current_event_id: str | None = None
        self.seat_id: int | None = None
        self.screen_names: dict[int, str] = {}
        self.arena_ids: dict[int, str] = {}
        self.submitted_maindeck: list[int] = []
        self.submitted_sideboard: list[int] = []
        self.game_maindeck: list[int] = []
        self.game_sideboard: list[int] = []
        self.objects_by_owner: dict[int, dict[int, int]] = defaultdict(dict)
        self.played_instance_ids_by_owner: dict[int, set[int]] = defaultdict(set)
        self.object_types: dict[int, list[str]] = {}
        self.cards_in_hand: dict[int, list[int]] = defaultdict(list)
        self.drawn_hands: dict[int, list[list[int]]] = defaultdict(list)
        self.opening_hand: dict[int, list[int]] = {}
        self.opening_hand_count_by_seat: dict[int, int] = defaultdict(int)
        self.turn_count = 0
        self.turn_numbers_by_seat: dict[int, set[int]] = defaultdict(set)
        self.reported_turns_by_seat: dict[int, int] = defaultdict(int)
        self.game_started_at: datetime | None = None
        self.observed_at: datetime | None = None
        self.starting_team_id: int | None = None
        self.game_number = 1
        self.finished_games: list[CompletedGame] = []
        self._emitted_game_keys: set[tuple[str, int]] = set()

    def consume(
        self,
        obj: dict[str, Any],
        api_name: str | None = None,
        observed_at: datetime | None = None,
    ) -> list[CompletedGame | CompletedMatch | Identity]:
        if observed_at is not None:
            self.observed_at = observed_at
        emitted: list[CompletedGame | CompletedMatch | Identity] = []
        if "authenticateResponse" in obj:
            auth = obj["authenticateResponse"]
            self.identity.screen_name = auth.get("screenName") or self.identity.screen_name
            self.identity.arena_user_id = auth.get("clientId") or auth.get("sessionId") or self.identity.arena_user_id
            emitted.append(self.identity)
        if api_name and "SetDeck" in api_name:
            self._handle_set_deck(obj)
        if "EventName" in obj and "Deck" in obj:
            self._handle_set_deck(obj)
        if "matchGameRoomStateChangedEvent" in obj:
            emitted.extend(self._handle_match_room(obj["matchGameRoomStateChangedEvent"]))
        if "greToClientEvent" in obj:
            messages = obj["greToClientEvent"].get("greToClientMessages") or []
            for message in messages:
                if not isinstance(message, dict):
                    continue
                emitted.extend(self._handle_gre_message(message))
        if "clientToGreMessage" in obj:
            self._handle_client_to_gre(obj["clientToGreMessage"])
        return emitted

    def _handle_set_deck(self, obj: dict[str, Any]) -> None:
        payload = obj.get("payload") or obj.get("request") or obj
        if isinstance(payload, str):
            return
        deck = payload.get("Deck") or payload.get("deck") or {}
        summary_event = payload.get("EventName") or obj.get("EventName")
        if summary_event:
            self.current_event_id = summary_event
        self.submitted_maindeck = _expand_card_list(deck.get("MainDeck") or deck.get("deckCards"))
        self.submitted_sideboard = _expand_card_list(deck.get("Sideboard") or deck.get("sideboardCards"))

    def _handle_match_room(self, event: dict[str, Any]) -> list[CompletedGame | CompletedMatch]:
        info = event.get("gameRoomInfo") or {}
        config = info.get("gameRoomConfig") or {}
        match_id = config.get("matchId") or (info.get("finalMatchResult") or {}).get("matchId")
        event_id = config.get("eventId") or config.get("eventName")
        if event_id:
            self.current_event_id = event_id
        if match_id and match_id != self.current_match_id:
            if self.current_match_id is not None:
                self._reset_game_state(keep_match=False)
            self.current_match_id = match_id
            self.game_number = 1
        for player in config.get("reservedPlayers") or []:
            seat = player.get("systemSeatId")
            if seat is None:
                continue
            name = (player.get("playerName") or "").split("#")[0]
            self.screen_names[int(seat)] = name
            self.arena_ids[int(seat)] = player.get("userId")
            if self.identity.screen_name and name == self.identity.screen_name:
                self.seat_id = int(seat)
                self.identity.arena_user_id = player.get("userId") or self.identity.arena_user_id
        state = info.get("stateType")
        if state == "MatchGameRoomStateType_MatchCompleted":
            return self._complete_match(info.get("finalMatchResult") or {})
        return []

    def _handle_gre_message(self, message: dict[str, Any]) -> list[CompletedGame | CompletedMatch]:
        msg_type = message.get("type")
        seats = message.get("systemSeatIds") or []
        if seats:
            self.seat_id = int(seats[0])
        if msg_type == "GREMessageType_ConnectResp":
            self.game_started_at = self.game_started_at or self.observed_at
            deck_info = (message.get("connectResp") or {}).get("deckMessage") or {}
            self.game_maindeck = _expand_card_list(deck_info.get("deckCards"))
            self.game_sideboard = _expand_card_list(deck_info.get("sideboardCards"))
            return []
        if msg_type in {"GREMessageType_GameStateMessage", "GREMessageType_QueuedGameStateMessage"}:
            return self._handle_game_state(message.get("gameStateMessage") or {})
        return []

    def _handle_client_to_gre(self, message: dict[str, Any]) -> None:
        payload = message
        if isinstance(message.get("payload"), dict):
            payload = message["payload"]
        if payload.get("type") != "ClientMessageType_MulliganResp" and "mulliganResp" not in payload:
            return
        if self.seat_id is None:
            return
        self.opening_hand_count_by_seat[self.seat_id] += 1
        hand = self.cards_in_hand.get(self.seat_id) or []
        if hand:
            self.drawn_hands[self.seat_id].append(list(hand))

    def _handle_game_state(self, state: dict[str, Any]) -> list[CompletedGame | CompletedMatch]:
        self.game_started_at = self.game_started_at or self.observed_at
        game_info = state.get("gameInfo") or {}
        match_id = game_info.get("matchID") or game_info.get("matchId")
        if match_id:
            self.current_match_id = match_id
        if game_info.get("gameNumber") is not None:
            self.game_number = int(game_info["gameNumber"])
        turn_info = state.get("turnInfo") or {}
        players = state.get("players") or []
        if turn_info.get("turnNumber"):
            turn_number = int(turn_info["turnNumber"])
            self.turn_count = max(self.turn_count, turn_number)
            active_player = turn_info.get("activePlayer")
            if active_player is not None and turn_number > 0:
                self.turn_numbers_by_seat[int(active_player)].add(turn_number)
        else:
            self.turn_count = max(self.turn_count, sum(int(p.get("turnNumber") or 0) for p in players))
        for player in players:
            seat = player.get("systemSeatNumber")
            if seat is not None and player.get("turnNumber") is not None:
                self.reported_turns_by_seat[int(seat)] = max(
                    self.reported_turns_by_seat[int(seat)],
                    int(player["turnNumber"]),
                )

        for game_object in state.get("gameObjects") or []:
            if game_object.get("type") not in {"GameObjectType_Card", "GameObjectType_SplitCard", None}:
                if game_object.get("type") and not str(game_object.get("type")).startswith("GameObjectType_"):
                    continue
            owner = game_object.get("ownerSeatId")
            instance_id = game_object.get("instanceId")
            card_id = _card_id(game_object)
            if owner is None or instance_id is None or card_id is None:
                continue
            self.objects_by_owner[int(owner)][int(instance_id)] = card_id
            types = game_object.get("cardTypes") or []
            if types:
                self.object_types[card_id] = [str(t).replace("CardType_", "") for t in types]

        for zone in state.get("zones") or []:
            owner = zone.get("ownerSeatId")
            if owner is None:
                continue
            owner = int(owner)
            ids = [int(instance_id) for instance_id in (zone.get("objectInstanceIds") or [])]
            if zone.get("type") in {"ZoneType_Stack", "ZoneType_Battlefield"}:
                self.played_instance_ids_by_owner[owner].update(ids)
            if zone.get("type") != "ZoneType_Hand":
                continue
            self.cards_in_hand[owner] = [
                self.objects_by_owner[owner][instance_id]
                for instance_id in ids
                if instance_id in self.objects_by_owner[owner]
            ]

        deciding = [
            (int(p["systemSeatNumber"]), int(p.get("mulliganCount") or 0))
            for p in players
            if p.get("pendingMessageType") == "ClientMessageType_MulliganResp" and "systemSeatNumber" in p
        ]
        for player_id, mulligan_count in deciding:
            if self.starting_team_id is None:
                self.starting_team_id = turn_info.get("activePlayer")
            self.opening_hand_count_by_seat[player_id] += 1
            if mulligan_count == len(self.drawn_hands[player_id]):
                self.drawn_hands[player_id].append(list(self.cards_in_hand.get(player_id) or []))

        if (
            not self.opening_hand
            and turn_info.get("phase") == "Phase_Beginning"
            and turn_info.get("step") == "Step_Upkeep"
            and int(turn_info.get("turnNumber") or 0) == 1
        ):
            for owner, hand in self.cards_in_hand.items():
                self.opening_hand[owner] = list(hand)

        if game_info.get("stage") == "GameStage_GameOver" and game_info.get("matchState") == "MatchState_GameComplete":
            results = game_info.get("results") or []
            game_result = next((r for r in results if r.get("scope") == "MatchScope_Game"), results[0] if results else {})
            return self._maybe_complete_game_from_result(game_result)
        return []

    def _maybe_complete_game_from_result(self, result: dict[str, Any]) -> list[CompletedGame | CompletedMatch]:
        if not self.current_match_id:
            return []
        key = (self.current_match_id, self.game_number)
        if key in self._emitted_game_keys:
            return []
        game = self._build_completed_game(result)
        self._emitted_game_keys.add(key)
        self.finished_games.append(game)
        self.game_number += 1
        self._reset_game_state(keep_match=True)
        return [game]

    def _complete_match(self, final_result: dict[str, Any]) -> list[CompletedGame | CompletedMatch]:
        if not self.current_match_id:
            return []
        match_result = next(
            (r for r in (final_result.get("resultList") or []) if r.get("scope") == "MatchScope_Match"),
            {},
        )
        won = None
        winning_team = match_result.get("winningTeamId")
        if winning_team is not None and self.seat_id is not None:
            won = int(winning_team) == int(self.seat_id)
        match = CompletedMatch(
            match_id=self.current_match_id,
            event_name=self.current_event_id,
            won=won,
            win_reason=match_result.get("reason"),
            player_name=self.screen_names.get(self.seat_id) if self.seat_id else self.identity.screen_name,
            player_arena_id=self.arena_ids.get(self.seat_id) if self.seat_id else self.identity.arena_user_id,
            opponent_name=self._opponent_name(),
            opponent_arena_id=self._opponent_arena_id(),
            games=list(self.finished_games),
        )
        self._reset_game_state(keep_match=False)
        self.finished_games = []
        self.game_number = 1
        self.current_match_id = None
        return [match]

    def _build_completed_game(self, result: dict[str, Any]) -> CompletedGame:
        seat = self.seat_id
        opponent_seat = next((s for s in self.screen_names if s != seat), None)
        winning_team = result.get("winningTeamId")
        won = None
        if winning_team is not None and seat is not None:
            won = int(winning_team) == int(seat)
        player_deck = self.game_maindeck or self.submitted_maindeck
        opponent_cards: list[int] = []
        if opponent_seat is not None:
            opponent_cards = list(self.objects_by_owner.get(opponent_seat, {}).values())
        player_played_cards = self._played_cards_for_seat(seat)
        opponent_played_cards = self._played_cards_for_seat(opponent_seat)
        type_counts: dict[str, int] = defaultdict(int)
        for card_id in player_deck:
            for card_type in self.object_types.get(card_id, []):
                type_counts[card_type] += 1
        mulligan_count = max(0, self.opening_hand_count_by_seat.get(seat or -1, 1) - 1)
        if seat is not None and seat in self.opening_hand_count_by_seat and self.opening_hand_count_by_seat[seat] == 0:
            mulligan_count = 0
        opponent_mulls = 0
        if opponent_seat is not None:
            opponent_mulls = max(0, self.opening_hand_count_by_seat.get(opponent_seat, 1) - 1)
        drawn = self.drawn_hands.get(seat or -1) or []
        duration_seconds = None
        if self.game_started_at is not None and self.observed_at is not None:
            duration_seconds = max(0, int((self.observed_at - self.game_started_at).total_seconds()))
        player_turns = self._turns_for_seat(seat)
        opponent_turns = self._turns_for_seat(opponent_seat)
        return CompletedGame(
            match_id=self.current_match_id or "",
            event_name=self.current_event_id,
            game_number=self.game_number,
            won=won,
            win_reason=result.get("reason"),
            on_play=(self.starting_team_id == seat) if self.starting_team_id is not None else None,
            turns=self.turn_count,
            duration_seconds=duration_seconds,
            player_turns=player_turns,
            opponent_turns=opponent_turns,
            player_seat=seat,
            player_name=self.screen_names.get(seat) if seat else self.identity.screen_name,
            player_arena_id=self.arena_ids.get(seat) if seat else self.identity.arena_user_id,
            opponent_name=self._opponent_name(),
            opponent_arena_id=self._opponent_arena_id(),
            player_deck=list(player_deck),
            player_sideboard=list(self.game_sideboard or self.submitted_sideboard),
            opponent_seen_cards=opponent_cards,
            player_played_cards=player_played_cards,
            opponent_played_cards=opponent_played_cards,
            opening_hand=list(self.opening_hand.get(seat or -1) or (drawn[-1] if drawn else [])),
            mulligans=list(drawn[:-1] if drawn else []),
            mulligan_count=mulligan_count,
            opponent_mulligan_count=opponent_mulls,
            card_types_seen=dict(type_counts),
        )

    def _played_cards_for_seat(self, seat: int | None) -> list[int]:
        if seat is None:
            return []
        objects = self.objects_by_owner.get(seat, {})
        return [
            objects[instance_id]
            for instance_id in sorted(self.played_instance_ids_by_owner.get(seat, set()))
            if instance_id in objects
        ]

    def _turns_for_seat(self, seat: int | None) -> int:
        if seat is None:
            return 0
        observed = len(self.turn_numbers_by_seat.get(seat, set()))
        return max(observed, self.reported_turns_by_seat.get(seat, 0))

    def _opponent_name(self) -> str | None:
        seat = self.seat_id
        for other, name in self.screen_names.items():
            if other != seat:
                return name
        return None

    def _opponent_arena_id(self) -> str | None:
        seat = self.seat_id
        for other, arena_id in self.arena_ids.items():
            if other != seat:
                return arena_id
        return None

    def _reset_game_state(self, keep_match: bool) -> None:
        self.objects_by_owner = defaultdict(dict)
        self.played_instance_ids_by_owner = defaultdict(set)
        self.cards_in_hand = defaultdict(list)
        self.drawn_hands = defaultdict(list)
        self.opening_hand = {}
        self.opening_hand_count_by_seat = defaultdict(int)
        self.turn_count = 0
        self.turn_numbers_by_seat = defaultdict(set)
        self.reported_turns_by_seat = defaultdict(int)
        self.game_started_at = None
        self.starting_team_id = None
        if not keep_match:
            self.game_maindeck = []
            self.game_sideboard = []
            self.screen_names = {}
            self.arena_ids = {}
            self._emitted_game_keys = set()
