from sinhalasubs.fm_converter import fm_runs, script_runs, unicode_to_fm


def test_single_letters():
    assert unicode_to_fm("ක") == "l"
    assert unicode_to_fm("ල") == ","


def test_vowel_sign_before_letter():
    # "කෙ" is typed ක + ෙ in Unicode, but FM draws the ෙ sign first: "fl"
    assert unicode_to_fm("කෙ") == "fl"


def test_punctuation_is_not_converted_twice():
    # ":" -> "(" must stay "(", not become "^"
    assert unicode_to_fm(":") == "("
    assert unicode_to_fm("(") == "^"


def test_no_sinhala_left_after_conversion():
    out = unicode_to_fm("ශ්‍රී ලංකාව අපේ රට.")
    assert not any("඀" <= ch <= "෿" for ch in out)


def test_english_words_stay_english():
    runs = fm_runs("අලුත් layer එකක්")
    assert runs[1] == ("layer ", True)
    assert [english for _, english in runs] == [False, True, False]


def test_script_runs_keep_all_text():
    text = "මම YouTube video එකක් හැදුවා"
    assert "".join(chunk for chunk, _ in script_runs(text)) == text
