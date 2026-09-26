"""Shorts voice policy; no live services or production stores."""
from types import SimpleNamespace
import pytest
from config.settings import SHORTS_RECITERS, RECITERS, RECITER_MAPPING_V4
from core.shorts_policy import require_shorts_reciter


def test_only_the_three_requested_voices_are_allowed():
    assert SHORTS_RECITERS == ('minshawi_mujawwad', 'banna', 'yasser_dossari')
    for key in SHORTS_RECITERS:
        assert require_shorts_reciter(key) == key
    with pytest.raises(ValueError):
        require_shorts_reciter('alafasy')


def test_yasser_uses_verified_verse_source_without_invented_word_timings(monkeypatch):
    from core import word_timings
    assert RECITERS['yasser_dossari']['id'] == 'Yasser_Ad-Dussary_128kbps'
    assert 'yasser_dossari' not in RECITER_MAPPING_V4
    monkeypatch.setattr(word_timings, '_fetch_verse', lambda *a: pytest.fail('Wrong timing identity'))
    assert word_timings.get_word_timings('yasser_dossari', 108, 1) is None


@pytest.mark.parametrize('command', ['cmd_generate', '_run_auto_reel'])
def test_unapproved_short_voice_stops_before_selection_or_render(command, monkeypatch):
    import main
    import database.jobs as jobs
    import core.video_generator as generator
    monkeypatch.setattr(jobs, 'get_next_shorts_selection', lambda *a: pytest.fail('Selection must not run'))
    monkeypatch.setattr(generator, 'generate_reel', lambda **kw: pytest.fail('Rendering must not run'))
    result = getattr(main, command)(SimpleNamespace(reciter='alafasy', surah=108,
                                                   start=1, end=3, verses=3, dry_run=False, test=False))
    assert result['status'] == 'failed'
    assert 'minshawi' in result['error']
