"""
Tests that RECITER_MAPPING_V4 points at the reciter it claims to.

Three entries pointed at the wrong person: husary resolved to Hani ar-Rifai,
shuraym to Al-Husary, and minshawi_mujawwad to ash-Shuraym. That was masked
because the timings endpoint returned no audio URL, so playback fell back to
everyayah with the correct reciter. The working endpoint supplies the audio
too, so a wrong ID would publish one reciter's voice under another's name.
"""
import pytest

from config.settings import RECITER_MAPPING_V4

# Snapshot of GET /api/v4/resources/recitations, verified 2026-08-08. Frozen so
# the check runs without network and a silent upstream renumbering is caught.
CANONICAL_RECITATIONS = {
    1: "AbdulBaset AbdulSamad (Mujawwad)",
    2: "AbdulBaset AbdulSamad (Murattal)",
    3: "Abdur-Rahman as-Sudais",
    4: "Abu Bakr al-Shatri",
    5: "Hani ar-Rifai",
    6: "Mahmoud Khalil Al-Husary",
    7: "Mishari Rashid al-`Afasy",
    8: "Mohamed Siddiq al-Minshawi (Mujawwad)",
    9: "Mohamed Siddiq al-Minshawi (Murattal)",
    10: "Sa`ud ash-Shuraym",
    11: "Mohamed al-Tablawi",
    12: "Mahmoud Khalil Al-Husary (Muallim)",
}

# The distinguishing surname (and style, where a reciter has several) that must
# appear in the canonical name for each project key.
EXPECTED_IDENTITY = {
    "alafasy": ["afasy"],
    "sudais": ["sudais"],
    "husary": ["husary"],
    "shuraym": ["shuraym"],
    "abdul_basit_murattal": ["abdulbaset", "murattal"],
    "abdul_basit_mujawwad": ["abdulbaset", "mujawwad"],
    "minshawi_mujawwad": ["minshawi", "mujawwad"],
    "shaatree": ["shatri"],
}


def _normalise(name):
    return name.lower().replace("-", "").replace("`", "").replace("'", "")


class TestReciterMapping:
    @pytest.mark.parametrize("key", sorted(RECITER_MAPPING_V4))
    def test_key_resolves_to_the_named_reciter(self, key):
        """A mapped key must resolve to a recitation bearing that reciter's name"""
        reciter_id = RECITER_MAPPING_V4[key]
        assert reciter_id in CANONICAL_RECITATIONS, (
            f"{key} -> id {reciter_id} is not a known recitation id"
        )

        canonical = _normalise(CANONICAL_RECITATIONS[reciter_id])
        expected = EXPECTED_IDENTITY.get(key)
        assert expected, f"{key} has no expected identity declared in this test"

        for token in expected:
            assert token in canonical, (
                f"{key} maps to id {reciter_id} = "
                f"'{CANONICAL_RECITATIONS[reciter_id]}', which is not {token}"
            )

    def test_no_two_keys_share_an_id(self):
        """Two keys resolving to one id means at least one is mislabelled"""
        seen = {}
        for key, rid in RECITER_MAPPING_V4.items():
            assert rid not in seen, f"{key} and {seen[rid]} both map to id {rid}"
            seen[rid] = key
