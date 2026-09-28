from cta_client.update import advertised_update, is_newer, pending_update, parse_version


def test_version_compare_treats_a_leading_v_as_noise():
    assert parse_version("v0.3.4") == (0, 3, 4)
    assert is_newer("0.3.5", "0.3.4")
    assert is_newer("1.0", "0.9.9")
    assert not is_newer("0.3.4", "0.3.4")
    assert not is_newer("0.3.4", "0.3.5")


def test_a_payload_naming_a_newer_cut_is_an_update():
    assert advertised_update(
        {
            "latest_client_version": "9.9.9",
            "client_release_url": "https://example/latest",
        },
        current="0.3.4",
    ) == ("9.9.9", "https://example/latest")


def test_the_same_cut_or_an_older_one_is_not_an_update():
    payload = {
        "latest_client_version": "0.3.4",
        "client_release_url": "https://example/latest",
    }
    assert advertised_update(payload, current="0.3.4") is None
    assert advertised_update(
        {**payload, "latest_client_version": "0.2.0"}, current="0.3.4"
    ) is None


def test_a_payload_without_a_version_or_url_is_ignored():
    assert advertised_update({"client_release_url": "https://example/latest"}, current="0.1.0") is None
    assert advertised_update({"latest_client_version": "9.9.9"}, current="0.1.0") is None
    assert advertised_update({}, current="0.1.0") is None


def test_pending_update_picks_the_newest_cut_ahead_of_this_build():
    assert pending_update(
        [
            ("0.3.5", "https://a/latest"),
            ("0.3.6", "https://b/latest"),
            ("0.3.4", "https://c/latest"),
        ],
        current="0.3.4",
    ) == ("0.3.6", "https://b/latest")


def test_later_hides_that_cut_until_a_newer_one_ships():
    advertised = [("0.3.5", "https://a/latest")]
    assert pending_update(advertised, current="0.3.4", dismissed="0.3.5") is None
    assert pending_update(
        [("0.3.6", "https://a/latest")],
        current="0.3.4",
        dismissed="0.3.5",
    ) == ("0.3.6", "https://a/latest")
