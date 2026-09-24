from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cta_client.formats import (
    best_of_from_event_name,
    best_of_from_win_condition,
    format_from_attributes,
    format_from_event_name,
)


def game_result_for_number(results: list[Any], game_number: int) -> dict[str, Any]:
    """Pick this game's row from Arena's cumulative results list.

    gameInfo.results appends every finished game. Taking the first
    MatchScope_Game row attributes G1's winner to G2 and G3.
    """
    game_results = [
        row for row in results if isinstance(row, dict) and row.get("scope") == "MatchScope_Game"
    ]
    if not game_results:
        return results[0] if results and isinstance(results[0], dict) else {}
    index = max(int(game_number) - 1, 0)
    if index < len(game_results):
        return game_results[index]
    return game_results[-1]


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
    format: str | None
    best_of: int | None
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
    format: str | None
    best_of: int | None
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
        self.current_format: str | None = None
        self.current_best_of: int | None = None
        self.format_by_event: dict[str, str] = {}
        self.seat_id: int | None = None
        self.screen_names: dict[int, str] = {}
        self.arena_ids: dict[int, str] = {}
        self.submitted_maindeck: list[int] = []
        self.submitted_sideboard: list[int] = []
        self.game_maindeck: list[int] = []
        self.game_sideboard: list[int] = []
        self.objects_by_owner: dict[int, dict[int, int]] = defaultdict(dict)
        self.objects_by_instance: dict[int, int] = {}
        self.owner_by_instance: dict[int, int] = {}
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
            series = best_of_from_event_name(summary_event)
            if series is not None:
                self.current_best_of = series
        declared = format_from_attributes(deck) or format_from_attributes(payload)
        if declared is None and summary_event:
            declared = format_from_event_name(summary_event)
        if declared is not None:
            self.current_format = declared
            if summary_event:
                self.format_by_event[summary_event] = declared
        self.submitted_maindeck = _expand_card_list(deck.get("MainDeck") or deck.get("deckCards"))
        self.submitted_sideboard = _expand_card_list(deck.get("Sideboard") or deck.get("sideboardCards"))

    def _handle_match_room(self, event: dict[str, Any]) -> list[CompletedGame | CompletedMatch]:
        info = event.get("gameRoomInfo") or {}
        config = info.get("gameRoomConfig") or {}
        match_id = config.get("matchId") or (info.get("finalMatchResult") or {}).get("matchId")
        event_id = config.get("eventId") or config.get("eventName")
        if event_id:
            self.current_event_id = event_id
            named = format_from_event_name(event_id)
            self.current_format = (
                self.format_by_event.get(event_id)
                or named
                or self.current_format
            )
            series = best_of_from_event_name(event_id)
            if series is not None:
                self.current_best_of = series
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
        win_condition = game_info.get("matchWinCondition") or game_info.get("winCondition")
        from_condition = best_of_from_win_condition(
            win_condition if isinstance(win_condition, str) else None
        )
        if from_condition is not None:
            self.current_best_of = from_condition
        elif self.current_best_of is None:
            self.current_best_of = best_of_from_event_name(self.current_event_id)
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

        public_zone_ids = {
            int(zone["zoneId"])
            for zone in state.get("zones") or []
            if zone.get("type") in {"ZoneType_Stack", "ZoneType_Battlefield"}
            and zone.get("zoneId") is not None
        }

        for game_object in state.get("gameObjects") or []:
            if game_object.get("type") not in {"GameObjectType_Card", "GameObjectType_SplitCard", None}:
                if game_object.get("type") and not str(game_object.get("type")).startswith("GameObjectType_"):
                    continue
            owner = game_object.get("ownerSeatId")
            if owner is None:
                owner = game_object.get("controllerSeatId")
            instance_id = game_object.get("instanceId")
            card_id = _card_id(game_object)
            if instance_id is None or card_id is None:
                continue
            instance_id = int(instance_id)
            self.objects_by_instance[instance_id] = card_id
            if owner is not None:
                owner = int(owner)
                self.objects_by_owner[owner][instance_id] = card_id
                self.owner_by_instance[instance_id] = owner
                zone_id = game_object.get("zoneId")
                if zone_id is not None and int(zone_id) in public_zone_ids:
                    self.played_instance_ids_by_owner[owner].add(instance_id)
            types = game_object.get("cardTypes") or []
            if types:
                self.object_types[card_id] = [str(t).replace("CardType_", "") for t in types]

        for zone in state.get("zones") or []:
            ids = [int(instance_id) for instance_id in (zone.get("objectInstanceIds") or [])]
            if zone.get("type") in {"ZoneType_Stack", "ZoneType_Battlefield"}:
                for instance_id in ids:
                    owner = self.owner_by_instance.get(instance_id)
                    if owner is not None:
                        self.played_instance_ids_by_owner[owner].add(instance_id)
            owner = zone.get("ownerSeatId")
            if owner is None or zone.get("type") != "ZoneType_Hand":
                continue
            owner = int(owner)
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

        if game_info.get("stage") == "GameStage_GameOver" and game_info.get("matchState") in {
            "MatchState_GameComplete",
            "MatchState_MatchComplete",
        }:
            if self._series_already_decided():
                return []
            results = game_info.get("results") or []
            return self._maybe_complete_game_from_result(
                game_result_for_number(results, self.game_number)
            )
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
            format=self.current_format,
            best_of=self.current_best_of,
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
            format=self.current_format,
            best_of=self.current_best_of,
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
        cards: list[int] = []
        for instance_id in sorted(self.played_instance_ids_by_owner.get(seat, set())):
            card_id = objects.get(instance_id, self.objects_by_instance.get(instance_id))
            if card_id is not None:
                cards.append(card_id)
        return cards

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
        self.objects_by_instance = {}
        self.owner_by_instance = {}
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
            self.current_format = None
            self.current_best_of = None

    def _series_already_decided(self) -> bool:
        """A Bo3 ends at two wins. A later GameOver is a different series."""
        if (self.current_best_of or 3) != 3:
            return False
        player_wins = sum(1 for game in self.finished_games if game.won is True)
        opponent_wins = sum(1 for game in self.finished_games if game.won is False)
        return player_wins >= 2 or opponent_wins >= 2
