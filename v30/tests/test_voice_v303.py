"""v30.3 regression: voice is browser-native, and missing prices are truthful.

Offline tests never claim to verify permissions or live source connectivity.
"""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_voice_component_and_persian_language():
    voice=(ROOT/'frontend/src/VoiceInput.jsx').read_text(encoding='utf-8')
    assert 'window.webkitSpeechRecognition' in voice
    assert "speech.lang='fa-IR'" in voice
    assert "onTranscriptRef.current?.(text)" in voice
    assert "e.error==='not-allowed'" in voice
    assert "e.error==='network'" in voice
    assert 'window.isSecureContext' in voice

def test_voice_connects_to_actual_estimate():
    main=(ROOT/'frontend/src/main.jsx').read_text(encoding='utf-8')
    assert "import VoiceInput from './VoiceInput.jsx'" in main
    assert 'onTranscript={fromVoice}' in main
    assert 'function fromVoice(text)' in main
    assert 'searchText(text)' in main

def test_missing_price_diagnostics_are_read_only():
    api=(ROOT/'backend/api.py').read_text(encoding='utf-8')
    assert "reason=('sources_inactive'" in api
    assert "'no_verified_prices'" in api
    assert "'insufficient_sample'" in api
    assert "'source_summary':summary" in api
    assert 'SELECT COUNT(*) AS total' in api

def test_approved_feed_is_required():
    connectors=(ROOT/'backend/connectors.py').read_text(encoding='utf-8')
    assert "ACCESS_NOT_CONFIGURED" in connectors
    assert "SOURCE_'+code.upper()+'_API_URL" in connectors
